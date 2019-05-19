from typing import Optional, Union

from discord import Message, TextChannel
from discord.ext.commands import Bot, Cog, Context, command, errors

from sxm_player.signals import TerminateInterrupt
from sxm_player.workers import InterruptableWorker

from .checks import is_playing, require_voice, require_matching_voice
from .converters import CountConverter, VolumeConverter
from .models import MusicCommand
from .music import AudioPlayer, PlayType
from .utils import send_message


class DiscordWorker(InterruptableWorker, Cog, name="Music"):
    bot: Bot
    prefix: str
    token: str
    output_channel: Optional[TextChannel] = None
    player: AudioPlayer

    _output_channel_id: Optional[int] = None

    def __init__(
        self,
        token: str,
        prefix: str,
        description: str,
        output_channel_id: Optional[int],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.prefix = prefix
        self.token = token
        self.bot = Bot(
            command_prefix=self.prefix, description=description, pm_help=True
        )
        self.bot.add_cog(self)

        self.player = AudioPlayer()

        if output_channel_id is not None:
            self._output_channel_id = output_channel_id

    def run(self):
        self._log.info("Discord bot has started")
        try:
            self.bot.run(self.token)
        except (KeyboardInterrupt, TerminateInterrupt):
            pass

    def __unload(self):
        if self.player is not None:
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
        await self.bot_output(f"Accepting `{self.prefix}` commands")

    @Cog.listener()
    async def on_command_error(
        self, ctx: Context, error: errors.CommandError
    ) -> None:
        if isinstance(error, errors.BadArgument):
            message = f"`{self.prefix}{ctx.command.name}`: {error.args[0]}"
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

    @Cog.listener()
    async def on_message(self, message: Message) -> None:
        ctx = await self.bot.get_context(message)
        author = ctx.message.author

        if message.content.startswith(self.prefix.strip()):
            if isinstance(ctx.message.channel, TextChannel):
                await ctx.message.delete()

        if ctx.valid:
            self._log.info(f"{author}: {message.content}")
        elif message.content == self.prefix.strip():
            await self._invalid_command(ctx)

    # helper methods
    async def bot_output(self, message: str):
        if self.output_channel is not None:
            await send_message(self.output_channel, message)

    async def _invalid_command(self, ctx: Context, group: str = ""):
        help_command = f"{self.prefix}help {group}".strip()
        message = (
            f"`{ctx.message.content}`: invalid command. "
            f"Use `{help_command}` for a list of commands"
        )
        await send_message(ctx, message)

    @command(pass_context=True, cls=MusicCommand)
    async def playing(self, ctx: Context) -> None:
        """Responds with what the bot currently playing"""

        if not await is_playing(ctx):
            return

        if self.player.play_type == PlayType.HLS:
            # TODO
            pass
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

        if self.player.play_type == PlayType.HLS:
            # TODO
            pass
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
        """Sets/Unsets play queue to repeat infinitely"""

        if not await is_playing(ctx):
            return

        if do_repeat is None:
            status = "on" if self.player.repeat else "off"
            await send_message(ctx, f"repeat is currently {status}")
        elif self.player.play_type == PlayType.HLS:
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
        """Forces bot to leave voice"""

        if not await require_voice(ctx):
            return

        await ctx.invoke(self.summon)
        await self.player.stop()

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def skip(self, ctx: Context) -> None:
        """Skips current song. Does not work for SXM"""

        if not await is_playing(ctx):
            return

        channel = ctx.message.channel
        author = ctx.message.author

        if self.player.play_type == PlayType.HLS:
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

        if self.player.play_type == PlayType.HLS:
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
