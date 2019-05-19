import asyncio
import traceback
from typing import Optional, Union

from discord import Message, TextChannel, TextChannel
from discord.ext.commands import Bot, Context, command, errors

from plexapi.server import PlexServer

from ...models import Episode, Song
from ..base import BaseRunner
from .checks import is_playing, require_matching_voice, require_voice
from .converters import CountConverter, VolumeConverter
from .models import MusicCommand
from .player import AudioPlayer, RepeatSetException
from .plex import PlexCommands
from .sxm import SXMCommands
from .utils import send_message


class BotRunner(BaseRunner, PlexCommands, SXMCommands):
    """ Discord Bot to play music """

    bot: Bot
    player: AudioPlayer
    prefix: str
    token: str
    output_channel: Optional[TextChannel] = None
    plex_library: Union[None, PlexServer] = None
    _output_channel_id: Optional[int] = None

    def __init__(
        self,
        prefix: str,
        description: str,
        token: str,
        output_channel_id: Optional[int],
        plex_username: Union[str, None] = None,
        plex_password: Union[str, None] = None,
        plex_server_name: Union[str, None] = None,
        plex_library_name: Union[str, None] = None,
        *args,
        **kwargs,
    ):
        kwargs["name"] = "bot"
        super().__init__(*args, **kwargs)

        self.prefix = prefix
        self.token = token
        self.bot = Bot(
            command_prefix=self.prefix, description=description, pm_help=True
        )
        self.bot.add_cog(self)

        self.bot.cogs["Music"] = self.bot.cogs.pop("BotRunner")

        if output_channel_id is not None:
            self._output_channel_id = output_channel_id

        self.player = AudioPlayer(self.bot, self.state)

        if (
            plex_username is not None
            and plex_password is not None
            and plex_server_name is not None
            and plex_library_name is not None
        ):
            self.plex_library = self._get_plex_server(
                plex_username,
                plex_password,
                plex_server_name,
                plex_library_name,
            )

        if self.state.output is None:
            self.bot.remove_command("songs")
            self.bot.remove_command("song")
            self.bot.remove_command("shows")
            self.bot.remove_command("show")
            self.bot.remove_command("skip")
            self.bot.remove_command("playlist")
            self.bot.remove_command("upcoming")

        if self.plex_library is None:
            self.bot.remove_command("plex")

    async def __before_invoke(self, ctx: Context) -> None:
        if self.state.runners.get("server") is None:
            raise errors.CommandError("SXM server is not running yet")

    async def _play_file(
        self, ctx: Context, item: Union[Song, Episode], message: bool = True
    ) -> None:
        """ Queues a file to be played """

        if not self.player.is_playing:
            await ctx.invoke(self.summon)

        if self.state.active_channel_id is not None:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)

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
