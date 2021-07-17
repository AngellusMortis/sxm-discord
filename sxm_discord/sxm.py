import asyncio
import logging
import os
import traceback
from typing import List, Optional, Tuple, Union

from discord import VoiceChannel
from discord.ext.commands import BadArgument, Context
from discord_slash import SlashContext, cog_ext  # type: ignore
from discord_slash.utils.manage_commands import create_option  # type: ignore
from sqlalchemy import or_
from sxm.models import XMChannel
from sxm_player.models import DBEpisode, DBSong, Episode, PlayerState, Song
from tabulate import tabulate

from .checks import require_sxm, require_voice
from .converters import XMChannelConverter, XMChannelListConverter
from .models import ArchivedSongCarousel, ReactionCarousel
from .music import AudioPlayer
from .utils import send_message


class SXMCommands:
    _log: logging.Logger

    player: AudioPlayer
    _state: PlayerState
    _pending: Optional[Tuple[XMChannel, VoiceChannel]] = None

    async def _play_archive_file(
        self, ctx: Context, guid: str = None, is_song: bool = False
    ) -> None:
        """Queues a song/show file from SXM archive to be played"""

        search_type = "shows"
        if is_song:
            search_type = "songs"

        if not await require_voice(ctx):
            return

        if guid is None:
            await send_message(ctx, f"Please provide a {search_type} id")
            return

        audio_file: Union[Song, Episode, None] = None
        if self._state.db is not None:
            if is_song:
                db_song = self._state.db.query(DBSong).filter_by(guid=guid).first()
                if db_song is not None:
                    audio_file = Song.from_orm(db_song)
            else:
                db_episode = (
                    self._state.db.query(DBEpisode).filter_by(guid=guid).first()
                )
                if db_episode is not None:
                    audio_file = Episode.from_orm(db_episode)

        if audio_file is not None and not os.path.exists(audio_file.file_path):
            self._log.warn(f"File does not exist: {audio_file.file_path}")
            audio_file = None

        if audio_file is None:
            await send_message(ctx, f"Invalid {search_type} id")
            return

        await self._play_file(ctx, audio_file)

    async def _play_file(
        self, ctx: Context, item: Union[Song, Episode], message: bool = True
    ) -> None:
        raise NotImplementedError()

    async def _search_archive(self, ctx: Context, search: str, is_song: bool) -> None:
        """Searches song/show database and responds with results"""

        if self._state.db is None:
            await send_message(ctx, "No active db connection")
            return

        search_type = "shows"
        if is_song:
            search_type = "songs"

        items: List[Union[Song, Episode]] = []
        if is_song:
            db_songs = (
                self._state.db.query(DBSong)
                .filter(
                    or_(
                        DBSong.guid.ilike(f"{search}%"),
                        DBSong.title.ilike(f"{search}%"),
                        DBSong.artist.ilike(f"{search}%"),
                    )
                )
                .order_by(DBSong.air_time.desc())[:10]
            )
            items = [Song.from_orm(i) for i in db_songs]
        else:
            db_episodes = (
                self._state.db.query(DBEpisode)
                .filter(
                    or_(
                        DBEpisode.guid.ilike(f"{search}%"),
                        DBEpisode.title.ilike(f"{search}%"),
                        DBEpisode.show.ilike(f"{search}%"),
                    )
                )
                .order_by(DBEpisode.air_time.desc())[:10]
            )
            items = [Episode.from_orm(i) for i in db_episodes]

        if len(items) > 0:
            message = f"{search_type.title()} matching `{search}`:"
            if is_song:
                carousel = ArchivedSongCarousel(items=list(items), body=message)
                await self.create_carousel(ctx, carousel)
            else:
                message += "\n\n"
                for item in items:
                    message += f"{item.guid}: {item.bold_name}\n"

                await send_message(ctx, message)
        else:
            await send_message(ctx, f"No {search_type} results found for `{search}`")

    async def _summon(self, ctx: SlashContext) -> None:
        raise NotImplementedError()

    async def create_carousel(
        self, ctx: SlashContext, carousel: ReactionCarousel
    ) -> None:
        raise NotImplementedError()

    @cog_ext.cog_subcommand(
        base="music",
        subcommand_group="sxm",
        name="channel",
        options=[
            create_option(
                name="channel",
                description="SXM Channel",
                option_type=3,
                required=False,
            )
        ],
    )
    async def sxm_channel(self, ctx: SlashContext, *, channel: str) -> None:
        """Plays a specific SXM channel"""

        if not await require_voice(ctx) or not await require_sxm(ctx):
            return

        try:
            xm_channel = await XMChannelConverter().convert(ctx, channel)
        except BadArgument as e:
            await send_message(ctx, str(e))
            return

        if self.player.is_playing:
            self._pending = None
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await self._summon(ctx)

        try:
            self._log.info(f"play: {xm_channel.id}")
            await self.player.add_live_stream(xm_channel)
        except Exception:
            self._log.error("error while trying to add channel to play queue:")
            self._log.error(traceback.format_exc())
            await self.player.stop()
            await send_message(ctx, "Something went wrong starting stream")
        else:
            if self.player.voice is not None:
                self._pending = (xm_channel, self.player.voice.channel)  # type: ignore
                await send_message(
                    ctx,
                    (
                        f"Started playing **{xm_channel.pretty_name}** in "
                        f"**{ctx.author.voice.channel.mention}**"
                    ),
                )

    @cog_ext.cog_subcommand(base="music", subcommand_group="sxm", name="channels")
    async def sxm_channels(self, ctx: SlashContext) -> None:
        """Bot will PM with list of possible SXM channel"""

        if not await require_sxm(ctx):
            return

        display_channels: List[Tuple[str, int, str, str]] = []
        for channel in self._state.channels:
            display_channels.append(
                (
                    channel.id,
                    int(channel.channel_number),
                    channel.name,
                    channel.short_description,
                )
            )

        display_channels = sorted(display_channels, key=lambda l: l[1])
        channel_table = tabulate(
            display_channels, headers=["ID", "#", "Name", "Description"]
        )

        self._log.debug(f"sending {len(display_channels)} for {ctx.author}")
        await ctx.author.send("SXM Channels:")
        await send_message(ctx, "PM'd list of channels")
        while len(channel_table) > 0:
            message = ""
            if len(channel_table) < 1900:
                message = channel_table
                channel_table = ""
            else:
                index = channel_table[:1900].rfind("\n")
                message = channel_table[:index]
                start = index + 1
                channel_table = channel_table[start:]

            await ctx.author.send(f"```{message}```")

    @cog_ext.cog_subcommand(
        base="music",
        subcommand_group="sxm",
        name="playlist",
        options=[
            create_option(
                name="channels",
                description="SXM Channels to pick from",
                option_type=3,
                required=True,
            ),
            create_option(
                name="threshold",
                description="Number of songs for channel to be considered",
                option_type=4,
                required=False,
            ),
        ],
    )
    async def sxm_playlist(
        self,
        ctx: SlashContext,
        channels: str,
        threshold: int = 40,
    ) -> None:
        """Play a random playlist from archived songs for a SXM channel."""

        if not await require_voice(ctx):
            return

        try:
            xm_channels = await XMChannelListConverter().convert(ctx, channels)
        except BadArgument as e:
            await send_message(ctx, str(e))
            return

        if self._state.db is None:
            return

        channel_ids = [x.id for x in xm_channels]
        unique_songs_query = self._state.db.query(DBSong.title, DBSong.artist).filter(
            DBSong.channel.in_(channel_ids)
        )
        unique_songs = unique_songs_query.distinct().all()

        if len(unique_songs) < threshold:
            await send_message(ctx, "not enough archived songs in provided channels")
            return

        if self.player.is_playing:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await self._summon(ctx)

        try:
            await self.player.add_playlist(xm_channels, self._state.db)
        except Exception:
            self._log.error("error while trying to create playlist:")
            self._log.error(traceback.format_exc())
            await self.player.stop()
            await send_message(ctx, "something went wrong starting playlist")
        else:
            voice_channel = ctx.author.voice.channel
            if len(xm_channels) == 1:
                await send_message(
                    ctx,
                    (
                        "Started playing a playlist of random songs from"
                        f"**{xm_channels[0].pretty_name}** in "
                        f"**{voice_channel.mention}**"
                    ),
                )
            else:
                channel_nums = ", ".join([f"#{x.channel_number}" for x in xm_channels])
                await send_message(
                    ctx,
                    (
                        "Started playing a playlist of random songs from"
                        f"**{channel_nums}** in **{voice_channel.mention}**"
                    ),
                )

    @cog_ext.cog_subcommand(
        base="music",
        subcommand_group="sxm",
        name="show",
        options=[
            create_option(
                name="show_id",
                description="Show GUID",
                option_type=3,
                required=True,
            )
        ],
    )
    async def sxm_show(self, ctx: SlashContext, show_id: Optional[str] = None) -> None:
        """Adds a show to a play queue"""

        await self._play_archive_file(ctx, show_id, False)

    @cog_ext.cog_subcommand(
        base="music",
        subcommand_group="sxm",
        name="shows",
        options=[
            create_option(
                name="search",
                description="Search Query",
                option_type=3,
                required=True,
            )
        ],
    )
    async def sxm_shows(self, ctx: SlashContext, search: str) -> None:
        """Searches for an archived show to play.
        Only returns the first 10 shows"""

        await self._search_archive(ctx, search, False)

    @cog_ext.cog_subcommand(
        base="music",
        subcommand_group="sxm",
        name="song",
        options=[
            create_option(
                name="song_id",
                description="Song GUID",
                option_type=3,
                required=True,
            )
        ],
    )
    async def sxm_song(self, ctx: SlashContext, song_id: str) -> None:
        """Adds a song to a play queue"""

        await self._play_archive_file(ctx, song_id, True)

    @cog_ext.cog_subcommand(
        base="music",
        subcommand_group="sxm",
        name="songs",
        options=[
            create_option(
                name="search",
                description="Search Query",
                option_type=3,
                required=True,
            )
        ],
    )
    async def sxm_songs(self, ctx: SlashContext, search: str) -> None:
        """Searches for an archived song to play.
        Only returns the first 10 songs"""

        await self._search_archive(ctx, search, True)
