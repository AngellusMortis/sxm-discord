import asyncio
import datetime
import time
import traceback
from typing import List, Optional, Tuple, Union

from discord import Activity, Game, Message, TextChannel, VoiceChannel
from discord.ext.commands import Bot, Cog, Context, command, errors
from humanize import naturaltime

from sxm.models import XMChannel
from sxm_player.models import Episode, PlayerState, Song
from sxm_player.queue import Event, EventMessage
from sxm_player.signals import TerminateInterrupt
from sxm_player.workers import (
    HLSStatusSubscriber,
    InterruptableWorker,
    SXMStatusSubscriber,
)

from .checks import is_playing, require_matching_voice, require_voice
from .converters import CountConverter, VolumeConverter
from .models import MusicCommand, SXMActivity
from .music import AudioPlayer, PlayType
from .sxm import SXMCommands
from .utils import generate_now_playing_embed, get_recent_songs, send_message


class DiscordWorker(
    InterruptableWorker,
    HLSStatusSubscriber,
    SXMStatusSubscriber,
    SXMCommands,
    Cog,
    name="Music",
):
    bot: Bot
    global_prefix: str
    local_prefix: dict
    token: str
    output_channel: Optional[TextChannel] = None
    player: AudioPlayer

    _output_channel_id: Optional[int] = None
    _last_update: float = 0
    _update_interval: float = 5
    _pending: Optional[Tuple[XMChannel, VoiceChannel]] = None

    def __init__(
        self,
        token: str,
        global_prefix: str,
        sxm_prefix: str,
        description: str,
        output_channel_id: Optional[int],
        processed_folder: str,
        sxm_status: bool,
        stream_data: Tuple[Optional[str], Optional[str]] = (None, None),
        channels: Optional[List[dict]] = None,
        raw_live_data: Tuple[
            Optional[float], Optional[float], Optional[dict]
        ] = (None, None, None),
        *args,
        **kwargs,
    ):
        sxm_status_queue = kwargs.pop("sxm_status_queue")
        SXMStatusSubscriber.__init__(self, sxm_status_queue)
        hls_stream_queue = kwargs.pop("hls_stream_queue")
        HLSStatusSubscriber.__init__(self, hls_stream_queue)
        super().__init__(*args, **kwargs)

        self._state = PlayerState()
        self._state.sxm_running = sxm_status
        self._state.stream_data = stream_data
        self._state.processed_folder = processed_folder
        self._state.channels = channels  # type: ignore
        self._state.set_raw_live(raw_live_data)
        self._event_queues = [self.sxm_status_queue, self.hls_stream_queue]

        self.global_prefix = global_prefix
        self.local_prefix = {"sxm": sxm_prefix}

        self.token = token
        self.bot = Bot(
            command_prefix=self.global_prefix,
            description=description,
            pm_help=True,
        )
        self.bot.add_cog(self)

        # commands that depend on SQLite DB
        if self._state.processed_folder is None:
            self.bot.remove_command("skip")
            self.bot.remove_command("upcoming")

            sxm = self.bot.get_command("sxm")
            sxm.remove_command("song")
            sxm.remove_command("songs")
            sxm.remove_command("show")
            sxm.remove_command("shows")
            sxm.remove_command("playlist")

        self.player = AudioPlayer(self.event_queue, self.bot.loop)

        if output_channel_id is not None:
            self._output_channel_id = output_channel_id

        self.bot.loop.create_task(self.event_loop())

    def run(self):
        self._log.info("Discord bot has started")
        try:
            self.bot.run(self.token)
        except (KeyboardInterrupt, TerminateInterrupt, RuntimeError):
            pass

    def __unload(self):
        self.bot.loop.create_task(self.bot_output("Music bot shutting down"))

        if self.player is not None:
            self.player.cleanup()
            self.bot.loop.create_task(self.player.stop())

    @Cog.listener()
    async def on_ready(self) -> None:
        user = self.bot.user

        if self._output_channel_id is not None:
            for channel in self.bot.get_all_channels():
                if channel.id == self._output_channel_id:
                    self.output_channel = channel
                    break

            if self.output_channel is None:
                self._log.warn(
                    f"could not find output channel: {self._output_channel_id}"
                )
            else:
                self._log.info(f"output channel: {self.output_channel.id}")

        self._log.info(f"logged in as {user} (id: {user.id})")
        await self.bot_output(f"Accepting `{self.global_prefix}` commands")

    @Cog.listener()
    async def on_command_error(
        self, ctx: Context, error: errors.CommandError
    ) -> None:
        if isinstance(error, errors.BadArgument):
            message = (
                f"`{self.global_prefix}{ctx.command.name}`: {error.args[0]}"
            )
            await send_message(ctx, message)
        elif isinstance(error, errors.CommandNotFound):
            self._log.info(
                f"{ctx.message.author}: invalid command: {ctx.message.content}"
            )
            await self._invalid_command(ctx)

        elif isinstance(error, errors.MissingRequiredArgument):
            self._log.info(
                f"{ctx.message.author}: missing arg: {ctx.message.content}"
            )

            arg = str(error).split(" ")[0]
            arg = arg.replace("xm_channel", "channel_id")

            message = f"`{ctx.message.content}`: `{arg}` is missing"
            await send_message(ctx, message)
        elif not isinstance(error, errors.CheckFailure):
            self._log.error(f"{type(error)}: {error}")
            await send_message(ctx, "something went wrong ☹")

    # @Cog.listener()
    # async def on_socket_raw_receive(
    #     self, message: Union[str, bytes]
    # ) -> Union[str, bytes]:
    #     for command_group, prefix in self.local_prefix.items():
    #         if message.startswith(prefix.strip()):
    #             command = message.replace(prefix, "")
    #             message = f"{self.global_prefix}{command_group} {command}"

    #     return message

    @Cog.listener()
    async def on_message(self, message: Message) -> None:
        ctx = await self.bot.get_context(message)
        author = ctx.message.author

        if message.content.startswith(self.global_prefix.strip()):
            if isinstance(ctx.message.channel, TextChannel):
                await ctx.message.delete()

        if ctx.valid:
            self._log.info(f"{author}: {message.content}")
        elif message.content == self.global_prefix.strip():
            await self._invalid_command(ctx)

    # helper methods
    async def bot_output(self, message: str):
        if self.output_channel is not None:
            await send_message(self.output_channel, message)

    async def _invalid_command(self, ctx: Context, group: str = ""):
        help_command = f"{self.global_prefix}help {group}".strip()
        message = (
            f"`{ctx.message.content}`: invalid command. "
            f"Use `{help_command}` for a list of commands"
        )
        await send_message(ctx, message)

    async def event_loop(self):
        while not self.shutdown_event.is_set():
            was_connected = self._state.sxm_running

            for queue in self._event_queues:
                event = queue.safe_get()

                if event:
                    self._log.debug(
                        f"Received event: {event.msg_src}, "
                        f"{event.msg_type.name}"
                    )
                    await self._handle_event(event)

            if self._state.sxm_running and not was_connected:
                await self.bot_output(
                    "SXM now available for streaming. "
                    f"{len(self._state.channels)} channels available"
                )
                if self._pending is not None:
                    await self.bot_output(
                        "Automatically resuming previous channel: "
                        f"`{self._pending[0].id}`"
                    )
                    await self.player.set_voice(self._pending[1])
                    await self.player.add_live_stream(self._pending[0])
                    self._pending = None
            elif not self._state.sxm_running and was_connected:
                await self.bot_output(
                    "Connection to SXM was lost. Will automatically reconnect"
                )
                if (
                    self.player.is_playing
                    and self.player.play_type == PlayType.LIVE
                ):
                    xm_channel = self.player.current.stream_data[0]
                    self._pending = (xm_channel, self.player.voice.channel)
                    await self.player.stop(False)

            if time.time() > (self._last_update + self._update_interval):
                await self.update()
                self._last_update = time.time()

            await asyncio.sleep(0.1)

    async def update(self):
        activity: Optional[Activity] = None
        if self.player.is_playing:
            if self.player.play_type == PlayType.LIVE:
                if self._state.live is not None:
                    xm_channel = self._state.get_channel(
                        self._state.stream_channel
                    )
                    activity = SXMActivity(
                        start=self._state.start_time,
                        radio_time=self._state.radio_time,
                        channel=xm_channel,
                        live_channel=self._state.live,
                    )
            else:
                activity = Game(
                    name=self.player.current.audio_file.pretty_name
                )

        try:
            await self.bot.change_presence(activity=activity)
        except AttributeError:
            pass

    async def _handle_event(self, event: EventMessage):
        if event.msg_type == Event.SXM_STATUS:
            self._state.sxm_running = event.msg
        elif event.msg_type == Event.HLS_STREAM_STARTED:
            self._state.stream_data = event.msg

            if (
                self.player.play_type == PlayType.LIVE
                or self.player.play_type is None
            ):

                if self.player.play_type == PlayType.LIVE:
                    await self.player.stop(False)

                await self.player.add_live_stream(
                    self._state.get_channel(event.msg[0]), event.msg[1]
                )
            else:
                self._log.debug("Ignoring new HLS stream")
        elif event.msg_type == Event.UPDATE_METADATA:
            self._state.set_raw_live(event.msg)
        elif event.msg_type == Event.UPDATE_CHANNELS:
            self._state.channels = event.msg
        elif event.msg_type == Event.KILL_HLS_STREAM:
            await self.player.stop()
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )

    async def _play_file(
        self, ctx: Context, item: Union[Song, Episode], message: bool = True
    ) -> None:
        """ Queues a file to be played """

        if self.player.is_playing:
            if self.player.play_type != PlayType.FILE:
                await self.player.stop(disconnect=False)
                await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        try:
            self._log.info(f"play: {item.file_path}")
            await self.player.add_file(item)
        except Exception:
            self._log.error("error while trying to add file to play queue:")
            self._log.error(traceback.format_exc())
        else:
            if message:
                await send_message(
                    ctx, f"added {item.bold_name} to now playing queue"
                )

    @command(pass_context=True, cls=MusicCommand)
    async def playing(self, ctx: Context) -> None:
        """Responds with what the bot currently playing"""

        if not await is_playing(ctx):
            return

        if self.player.play_type == PlayType.LIVE:
            if self._state.stream_channel is None or self.player.voice is None:
                return

            xm_channel, embed = generate_now_playing_embed(self._state)
            message = (
                f"currently playing **{xm_channel.pretty_name}** on "
                f"**{self.player.voice.channel.mention}**"
            )
            await send_message(ctx, message, embed=embed)
        else:
            name = self.player.current.audio_file.bold_name  # type: ignore
            channel = self.player.voice.channel  # type: ignore

            await send_message(
                ctx, (f"current playing {name} on **{channel.mention}**")
            )

    @command(pass_context=True, cls=MusicCommand)
    async def recent(  # type: ignore
        self, ctx: Context, count: CountConverter = 3
    ) -> None:
        """Responds with the last 1-10 songs that been
        played on this channel"""

        if not await is_playing(ctx):
            return

        if self.player.play_type == PlayType.LIVE:
            if self._state.stream_channel is None or self.player.voice is None:
                return

            xm_channel, song_cuts, latest_cut = get_recent_songs(
                self._state, count
            )
            now = self._state.radio_time

            if len(song_cuts) > 0:
                message = f"Recent songs for **{xm_channel.pretty_name}**:\n\n"

                for song_cut in song_cuts:
                    seconds_ago = int((now - song_cut.time) / 1000)
                    time_delta = datetime.timedelta(seconds=seconds_ago)
                    time_string = naturaltime(time_delta)

                    pretty_name = Song.get_pretty_name(
                        song_cut.cut.title, song_cut.cut.artists[0].name, True
                    )
                    if song_cut == latest_cut:
                        message += f"now: {pretty_name}\n"
                    else:
                        message += f"about {time_string}: {pretty_name}\n"

                await send_message(ctx, message, sep="\n\n")
            else:
                await send_message(ctx, "no recent songs played")
        else:
            message = f"Recent songs/shows:\n\n"

            index = 0
            for item in self.player.recent[:count]:
                if item == self.player.current:
                    message += f"now: {item.bold_name}\n"
                else:
                    message += f"{index}: {item.bold_name}\n"
                index -= 1

            await send_message(ctx, message, sep="\n\n")

    @command(pass_context=True, cls=MusicCommand)
    async def repeat(
        self, ctx: Context, do_repeat: Union[bool, None] = None
    ) -> None:
        """Set/Unset play queue to repeat infinitely"""

        if not await is_playing(ctx):
            return

        if do_repeat is None:
            status = "on" if self.player.repeat else "off"
            await send_message(ctx, f"repeat is currently {status}")
        elif self.player.play_type == PlayType.LIVE:
            await send_message(
                ctx, "Cannot change repeat while playing a SXM live channel"
            )
        elif self.player.play_type == PlayType.RANDOM:
            await send_message(
                ctx,
                "Cannot change repeat while playing a SXM Archive playlist",
            )
        else:
            await send_message(ctx, f"set repeat to {status}")

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def reset(self, ctx: Context) -> None:
        """Forces bot to leave voice and hard resets audio player"""

        if not await require_voice(ctx):
            return

        await ctx.invoke(self.summon)
        await self.player.stop()
        await self.player.cleanup()

        self.player = AudioPlayer(self.event_queue, self.bot.loop)

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def skip(self, ctx: Context) -> None:
        """Skips current song. Does not work for SXM"""

        if not await is_playing(ctx):
            return

        channel = ctx.message.channel
        author = ctx.message.author

        if self.player.play_type == PlayType.LIVE:
            await channel.send(
                f"{author.mention}, cannot skip. SXM radio is playing"
            )
            return

        await self.player.skip()

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def stop(self, ctx: Context) -> None:
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """

        if not await is_playing(ctx):
            return

        await self.player.stop()
        await ctx.message.channel.send(
            f"{ctx.message.author.mention} stopped playing music"
        )

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def summon(self, ctx: Context) -> None:
        """Summons the bot to join your voice channel"""

        if not await require_voice(ctx):
            return

        summoned_channel = ctx.message.author.voice.channel
        await self.player.set_voice(summoned_channel)

    @command(pass_context=True, cls=MusicCommand)
    async def upcoming(self, ctx: Context) -> None:
        """ Displaying the songs/shows on play queue. Does not
        work for live SXM radio """

        if not await is_playing(ctx):
            return

        if self.player.play_type == PlayType.LIVE:
            await send_message(ctx, "live radio playing, cannot get upcoming")
        else:
            message = f"Upcoming songs/shows:\n\n"

            index = 1
            for item in self.player.upcoming:
                if item == self.player.current:
                    message += f"next: {item.bold_name}\n"
                else:
                    message += f"{index}: {item.bold_name}\n"
                index += 1

            await send_message(ctx, message, sep="\n\n")

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def volume(
        self, ctx: Context, amount: VolumeConverter = None
    ) -> None:
        """Changes the volume of music
        """

        if not await require_matching_voice(ctx):
            return

        channel = ctx.message.channel
        author = ctx.message.author

        if amount is None:
            await channel.send(
                f"{author.mention}, volume is currently "
                f"{int(self.player.volume * 100)}%"
            )
        else:
            self.player.volume = amount
            await channel.send(
                f"{author.mention}, set volume to "
                f"{int(self.player.volume * 100)}%"
            )
