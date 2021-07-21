import asyncio
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

from discord import Activity, Game, Intents, TextChannel, VoiceChannel
from discord.ext.commands import BadArgument, Bot, Cog
from discord_slash import SlashCommand, SlashContext, cog_ext  # type: ignore
from discord_slash.utils.manage_commands import create_option  # type: ignore
from sxm.models import XMChannel
from sxm_player.models import Episode, PlayerState, Song
from sxm_player.queue import EventMessage, EventTypes
from sxm_player.signals import TerminateInterrupt
from sxm_player.workers import (
    HLSStatusSubscriber,
    InterruptableWorker,
    SXMStatusSubscriber,
)

from sxm_discord.music import AudioPlayer, PlayType
from sxm_discord.sxm import SXMArchivedCommands, SXMCommands
from sxm_discord.utils import (
    SXM_COG_NAME,
    generate_embed_from_archived,
    generate_now_playing_embed,
    get_recent_songs,
    get_root_command,
    send_message,
)

from .checks import is_playing, no_pm, require_voice
from .converters import CountConverter
from .models import (
    ArchivedSongCarousel,
    ReactionCarousel,
    SongActivity,
    SXMActivity,
    SXMCutCarousel,
    UpcomingSongCarousel,
)

CAROUSEL_TIMEOUT = 30


class DiscordWorker(
    InterruptableWorker,
    HLSStatusSubscriber,
    SXMStatusSubscriber,
    SXMCommands,
    Cog,
    name=SXM_COG_NAME,
):
    bot: Bot
    slash: SlashCommand
    root_command: str
    token: str
    output_channel: Optional[TextChannel] = None
    player: AudioPlayer
    carousels: Dict[int, ReactionCarousel] = {}

    _output_channel_id: Optional[int] = None
    _last_update: float = 0
    _update_interval: float = 5
    _pending: Optional[Tuple[XMChannel, VoiceChannel]] = None

    def __init__(
        self,
        token: str,
        description: str,
        output_channel_id: Optional[int],
        processed_folder: str,
        sxm_status: bool,
        stream_data: Tuple[Optional[str], Optional[str]] = (None, None),
        channels: Optional[List[dict]] = None,
        raw_live_data: Tuple[
            Optional[datetime], Optional[timedelta], Optional[dict]
        ] = (
            None,
            None,
            None,
        ),
        *args,
        **kwargs,
    ):
        sxm_status_queue = kwargs.pop("sxm_status_queue")
        SXMStatusSubscriber.__init__(self, sxm_status_queue)
        hls_stream_queue = kwargs.pop("hls_stream_queue")
        HLSStatusSubscriber.__init__(self, hls_stream_queue)

        kwargs["name"] = "Music"
        super().__init__(*args, **kwargs)

        self._state = PlayerState()
        self._state.sxm_running = sxm_status
        self._state.update_stream_data(stream_data)
        self._state.processed_folder = processed_folder
        self._state.update_channels(channels)
        self._state.set_raw_live(raw_live_data)
        self._event_queues = [self.sxm_status_queue, self.hls_stream_queue]

        self.root_command = get_root_command()

        self.token = token
        self.bot = Bot(
            command_prefix=f"/{self.root_command}",
            description=description,
            intents=Intents.default(),
            help_command=None,
        )
        self.slash = SlashCommand(self.bot, sync_commands=True, sync_on_cog_reload=True)
        self.bot.add_cog(self)
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
                    self.output_channel = channel  # type: ignore
                    break

            if self.output_channel is None:
                self._log.warn(
                    f"could not find output channel: {self._output_channel_id}"
                )
            else:
                self._log.info(f"output channel: {self.output_channel.id}")

        self._log.info(f"logged in as {user} (id: {user.id})")
        await self.bot_output(f"Accepting `{self.root_command}` commands")

        if self._state.sxm_running:
            await self._sxm_running_message()

    @Cog.listener()
    async def on_reaction_add(self, reaction, user):
        # ignore bot user reactions
        if user.id == self.bot.user.id:
            return

        carousel = self.carousels.get(reaction.message.id)
        if carousel is not None:
            carousel.message = reaction.message
            await carousel.handle_reaction(self._state, reaction.emoji)

    # helper methods
    async def bot_output(self, message: str):
        self._log.info(f"Bot output: {message}")
        if self.output_channel is not None:
            await send_message(self.output_channel, message)

    async def _sxm_running_message(self):
        await self.bot_output(
            "SXM now available for streaming. "
            f"{len(self._state.channels)} channels available"
        )

    async def _event_loop(self):
        while not self.shutdown_event.is_set():
            was_connected = self._state.sxm_running

            for queue in self._event_queues:
                event = queue.safe_get()

                if event:
                    self._log.debug(
                        f"Received event: {event.msg_src}, " f"{event.msg_type.name}"
                    )
                    await self._handle_event(event)

            if self._state.sxm_running and not was_connected:
                await self._sxm_running_message()
                if self._pending is not None:
                    await self.bot_output(
                        "Automatically resuming previous channel: "
                        f"`{self._pending[0].id}`"
                    )
                    await self._reset_live(self._pending[1], self._pending[0])
            elif not self._state.sxm_running and was_connected:
                await self.bot_output(
                    "Connection to SXM was lost. Will automatically reconnect"
                )
                if self.player.is_playing and self.player.play_type == PlayType.LIVE:
                    await self.player.stop(disconnect=False)

            if time.time() > (self._last_update + self._update_interval):
                await self.update()
                self._last_update = time.monotonic()

            await asyncio.sleep(0.1)

    async def event_loop(self):
        try:
            await self._event_loop()
        except Exception:
            self._log.exception("Error doing event loop!")

    async def create_carousel(self, ctx: SlashContext, carousel: ReactionCarousel):
        await carousel.update(self._state, ctx)

        if len(carousel.items) > 1 and carousel.message is not None:
            self.carousels[carousel.message.id] = carousel

    async def update(self):
        activity: Optional[Activity] = None
        if self.player.is_playing:
            if self.player.play_type == PlayType.LIVE:
                if self._state.live is not None:
                    xm_channel = self._state.get_channel(self._state.stream_channel)
                    activity = SXMActivity(
                        start=self._state.start_time,
                        radio_time=self._state.radio_time,
                        channel=xm_channel,
                        live_channel=self._state.live,
                    )
                else:
                    self._log.debug("Could not update status, live is none")
            elif self.player.current is not None and isinstance(
                self.player.current.audio_file, Song
            ):
                activity = SongActivity(song=self.player.current.audio_file)
            else:
                activity = Game(name=self.player.current.audio_file.pretty_name)

        self._log.debug(f"Updating bot's status: {activity}")
        try:
            await self.bot.change_presence(activity=activity)
        except AttributeError:
            pass

        for key, carousel in list(self.carousels.items()):
            seconds_ago = (datetime.now() - carousel.last_update).total_seconds()
            if seconds_ago > CAROUSEL_TIMEOUT:
                self._log.info(f"Deleting carousel for message ID {key}")
                await carousel.refresh_message(self.bot)
                await carousel.clear_reactions()
                del self.carousels[key]

    async def _handle_event(self, event: EventMessage):
        if event.msg_type == EventTypes.SXM_STATUS:
            self._state.sxm_running = event.msg
        elif event.msg_type == EventTypes.HLS_STREAM_STARTED:
            self._state.update_stream_data(event.msg)

            if self.player.play_type == PlayType.LIVE or self.player.play_type is None:

                if self.player.play_type == PlayType.LIVE:
                    await self.player.stop(disconnect=False)

                xm_channel = self._state.get_channel(event.msg[0])

                if xm_channel is not None:
                    await self.player.add_live_stream(xm_channel, event.msg[1])
            else:
                self._log.debug("Ignoring new HLS stream")
        elif event.msg_type == EventTypes.UPDATE_METADATA:
            self._state.set_raw_live(event.msg)
        elif event.msg_type == EventTypes.UPDATE_CHANNELS:
            self._state.update_channels(event.msg)
        elif event.msg_type == EventTypes.KILL_HLS_STREAM:
            await self.player.stop(kill_hls=False)
            if event.msg_src == self.name:
                self._pending = None
            elif self._pending is not None and self._state.sxm_running:
                self.bot.loop.create_task(
                    self._reset_live(self._pending[1], self._pending[0])
                )
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )

    async def _play_file(
        self,
        ctx: SlashContext,
        item: Union[Song, Episode],
        message: bool = True,
    ) -> None:
        """Queues a file to be played"""

        if self.player.is_playing:
            if self.player.play_type != PlayType.FILE:
                self._pending = None
                await self.player.stop(disconnect=False)
                await asyncio.sleep(0.5)
        else:
            await self._summon(ctx)

        try:
            self._log.info(f"play: {item.file_path}")
            await self.player.add_file(item)
        except Exception:
            self._log.error("error while trying to add file to play queue:")
            self._log.error(traceback.format_exc())
        else:
            if message:
                await send_message(ctx, f"added {item.bold_name} to now playing queue")

    async def _reset_live(self, voice_channel: VoiceChannel, xm_channel: XMChannel):
        await self.player.stop(kill_hls=False)
        await self.player.cleanup()
        self.player = AudioPlayer(self.event_queue, self.bot.loop)
        await asyncio.sleep(10)
        await self.player.set_voice(voice_channel)
        await self.player.add_live_stream(xm_channel)

    @cog_ext.cog_subcommand(base=get_root_command())
    async def playing(self, ctx: SlashContext) -> None:
        """Responds with what the bot currently playing"""

        if not await is_playing(ctx):
            return

        channel: VoiceChannel = self.player.voice.channel  # type: ignore
        if self.player.play_type == PlayType.LIVE:
            if self._state.stream_channel is None or self.player.voice is None:
                return

            xm_channel, embed = generate_now_playing_embed(self._state)
            message = (
                f"Currently playing **{xm_channel.pretty_name}** on "
                f"**{channel.mention}**"
            )
            await send_message(ctx, message, embed=embed)
        elif (
            self.player.current is not None
            and self.player.current.audio_file is not None
            and self.player.voice is not None
        ):
            name = self.player.current.audio_file.bold_name
            await send_message(
                ctx,
                f"Currently playing {name} on **{channel.mention}**",
                embed=generate_embed_from_archived(self.player.current.audio_file),
            )

    async def _recent_live(self, ctx, count):
        if self._state.stream_channel is None or self.player.voice is None:
            return

        xm_channel, song_cuts, latest_cut = get_recent_songs(self._state, count)

        total = len(song_cuts)
        if total > 0:
            if total == 1:
                message = f"Most recent song for **{xm_channel.pretty_name}**:"
            else:
                message = (
                    f"{total} most recent songs for " f"**{xm_channel.pretty_name}**:"
                )

            carousel = SXMCutCarousel(
                items=song_cuts,
                latest=latest_cut,
                channel=xm_channel,
                body=message,
            )
            await self.create_carousel(ctx, carousel)
        else:
            await send_message(ctx, "No recent songs played")

    @cog_ext.cog_subcommand(
        base=get_root_command(),
        options=[
            create_option(
                name="count",
                description="Number of songs to return (1-10)",
                option_type=4,
                required=False,
            )
        ],
    )
    async def recent(self, ctx: SlashContext, count: int = 3) -> None:
        """Responds with the last 1-10 songs that been
        played on this channel"""

        try:
            count = await CountConverter().convert(ctx, count)
        except BadArgument as e:
            await send_message(ctx, str(e))
            return

        if not await is_playing(ctx):
            return

        if self.player.play_type == PlayType.LIVE:
            return await self._recent_live(ctx, count)

        carousel = ArchivedSongCarousel(
            items=list(self.player.recent[:count]), body="Recent songs/shows"
        )
        await self.create_carousel(ctx, carousel)

    @cog_ext.cog_subcommand(
        base=get_root_command(),
        options=[
            create_option(
                name="do_repeat",
                description="On/Off",
                option_type=5,
                required=False,
            )
        ],
    )
    async def repeat(self, ctx: SlashContext, do_repeat: Optional[bool] = None) -> None:
        """Set/Unset play queue to repeat infinitely"""

        if not await is_playing(ctx):
            return

        if do_repeat is None:
            status = "on" if self.player.repeat else "off"
            await send_message(ctx, f"Repeat is currently {status}")
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
            self.player.repeat = do_repeat
            status = "on" if self.player.repeat else "off"
            await send_message(ctx, f"Set repeat to {status}")

    @cog_ext.cog_subcommand(base=get_root_command())
    async def reset(self, ctx: SlashContext) -> None:
        """Forces bot to leave voice and hard resets audio player"""

        if not await require_voice(ctx):
            return

        await self._summon(ctx)
        self._pending = None
        await self.player.stop()
        await self.player.cleanup()

        self.player = AudioPlayer(self.event_queue, self.bot.loop)

        await send_message(ctx, "Bot reset successfully")

    @cog_ext.cog_subcommand(base=get_root_command())
    async def stop(self, ctx: SlashContext) -> None:
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """

        if not await no_pm(ctx) or not await is_playing(ctx):
            return

        self._pending = None
        await self.player.stop()
        await send_message(ctx, "Stopped playing music")

    async def _summon(self, ctx: SlashContext) -> None:
        if not await no_pm(ctx) or not await require_voice(ctx):
            return

        summoned_channel = ctx.author.voice.channel
        await self.player.set_voice(summoned_channel)

    @cog_ext.cog_subcommand(base=get_root_command())
    async def summon(self, ctx: SlashContext) -> None:
        """Summons the bot to join your voice channel"""

        await self._summon(ctx)
        await send_message(
            ctx, f"Successfully joined {ctx.author.voice.channel.mention}"
        )


class DiscordArchivedWorker(
    SXMArchivedCommands,
    DiscordWorker,
    name=SXM_COG_NAME,
):
    @cog_ext.cog_subcommand(base=get_root_command())
    async def skip(self, ctx: SlashContext) -> None:
        """Skips current song. Does not work for SXM"""

        if not await no_pm(ctx) or not await is_playing(ctx):
            return

        if self.player.play_type == PlayType.LIVE:
            await send_message(ctx, "Cannot skip. SXM radio is playing")
            return

        await self.player.skip()
        await send_message(ctx, "Song skipped")

    @cog_ext.cog_subcommand(base=get_root_command())
    async def upcoming(self, ctx: SlashContext) -> None:
        """Displaying the songs/shows on play queue. Does not
        work for live SXM radio"""

        if not await is_playing(ctx):
            return

        if self.player.play_type == PlayType.LIVE:
            await send_message(ctx, "Live radio playing, cannot get upcoming")
        elif self.player.current is not None:
            carousel = UpcomingSongCarousel(
                items=list(self.player.upcoming),
                body="Upcoming songs/shows:",
                latest=self.player.current.audio_file,
            )
            await self.create_carousel(ctx, carousel)
