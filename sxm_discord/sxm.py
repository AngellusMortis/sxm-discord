import asyncio
import logging
import os
import traceback
from typing import Optional, Union

from discord.ext.commands import Context, command
from sqlalchemy import or_
from tabulate import tabulate

from sxm_player.models import Episode, PlayerState, Song

from .checks import require_voice, require_sxm
from .converters import XMChannelConverter, XMChannelListConverter
from .models import MusicPlayerGroup, SXMCommand
from .music import AudioPlayer
from .utils import send_message


class SXMCommands:
    _log: logging.Logger

    player: AudioPlayer
    _state: PlayerState

    async def _invalid_command(self, ctx: Context, group: str = "") -> None:
        raise NotImplementedError()

    async def _play_archive_file(
        self, ctx: Context, guid: str = None, is_song: bool = False
    ) -> None:
        """ Queues a song/show file from SXM archive to be played"""

        channel = ctx.message.channel
        author = ctx.message.author
        search_type = "shows"
        if is_song:
            search_type = "songs"

        if not await require_voice(ctx):
            return

        if guid is None:
            await channel.send(
                f"{author.mention}, please provide a {search_type} id"
            )
            return

        db_item = None
        if self._state.db is not None:
            if is_song:
                db_item = (
                    self._state.db.query(Song).filter_by(guid=guid).first()
                )
            else:
                db_item = (
                    self._state.db.query(Episode).filter_by(guid=guid).first()
                )

        if db_item is not None and not os.path.exists(db_item.file_path):
            self._log.warn(f"file does not exist: {db_item.file_path}")
            db_item = None

        if db_item is None:
            await channel.send(f"{author.mention}, invalid {search_type} id")
            return

        await self._play_file(ctx, db_item)

    async def _play_file(
        self, ctx: Context, item: Union[Song, Episode], message: bool = True
    ) -> None:
        raise NotImplementedError()

    async def _search_archive(
        self, ctx: Context, search: str, is_song: bool
    ) -> None:
        """ Searches song/show database and responds with results """

        search_type = "shows"
        if is_song:
            search_type = "songs"

        items = None
        if is_song:
            items = (
                self._state.db.query(Song)  # type: ignore
                .filter(
                    or_(
                        Song.guid.ilike(f"{search}%"),  # type: ignore
                        Song.title.ilike(f"{search}%"),  # type: ignore
                        Song.artist.ilike(f"{search}%"),  # type: ignore
                    )
                )
                .order_by(Song.air_time.desc())[:10]  # type: ignore
            )
        else:
            items = (
                self._state.db.query(Episode)  # type: ignore
                .filter(
                    or_(
                        Episode.guid.ilike(f"{search}%"),  # type: ignore
                        Episode.title.ilike(f"{search}%"),  # type: ignore
                        Episode.show.ilike(f"{search}%"),  # type: ignore
                    )
                )
                .order_by(Episode.air_time.desc())[:10]  # type: ignore
            )
        if len(items) > 0:
            message = f"{search_type.title()} matching `{search}`:\n\n"
            for item in items:
                message += f"{item.guid}: {item.bold_name}\n"

            await send_message(ctx, message, sep="\n\n")
        else:
            await send_message(
                ctx, f"no {search_type} results found for `{search}`"
            )

    async def summon(self, ctx: Context) -> None:
        raise NotImplementedError()

    @command(cls=MusicPlayerGroup)
    async def sxm(self, ctx: Context) -> None:
        """Command for playing music from SXM"""
        if ctx.invoked_subcommand is None:
            await self._invalid_command(ctx, group="sxm")

    @sxm.command(name="channel", pass_context=True, no_pm=True, cls=SXMCommand)
    async def sxm_channel(
        self, ctx: Context, *, xm_channel: XMChannelConverter
    ) -> None:
        """Plays a specific SXM channel"""

        if not await require_voice(ctx) or not await require_sxm(ctx):
            return

        channel = ctx.message.channel
        author = ctx.message.author

        if self.player.is_playing:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        try:
            self._log.info(f"play: {xm_channel.id}")
            await self.player.add_live_stream(xm_channel)
        except Exception:
            self._log.error("error while trying to add channel to play queue:")
            self._log.error(traceback.format_exc())
            await self.player.stop()
            await channel.send(
                f"{author.mention}, something went wrong starting stream"
            )
        else:
            await channel.send(
                f"{author.mention} starting playing "
                f"**{xm_channel.pretty_name}** in "
                f"**{author.voice.channel.mention}**"
            )

    @sxm.command(name="channels", pass_context=True, cls=SXMCommand)
    async def sxm_channels(self, ctx: Context) -> None:
        """Bot will PM with list of possible SXM channel"""

        if not await require_sxm(ctx):
            return

        author = ctx.message.author

        display_channels = []
        for channel in self._state.channels:
            display_channels.append(
                [
                    channel.id,
                    channel.channel_number,
                    channel.name,
                    channel.short_description,
                ]
            )

        channel_table = tabulate(
            display_channels, headers=["ID", "#", "Name", "Description"]
        )

        self._log.debug(f"sending {len(display_channels)} for {author}")
        await author.send("SXM Channels:")
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

            await author.send(f"```{message}```")

    @sxm.command(
        name="playlist", pass_context=True, no_pm=True, cls=SXMCommand
    )
    async def sxm_playlist(
        self,
        ctx: Context,
        xm_channels: XMChannelListConverter,
        threshold: int = 40,
    ) -> None:
        """ Play a random playlist from archived songs
        for a SXM channel. Can use comma seperated list of channel_ids
        to play from multiple channels (max 5 channels) """

        if not await require_voice(ctx):
            return

        if self._state.db is None:
            return

        channel_ids = [x.id for x in xm_channels]
        unique_songs = self._state.db.query(Song.title, Song.artist).filter(
            Song.channel.in_(channel_ids)  # type: ignore
        )
        unique_songs = unique_songs.distinct().all()

        if len(unique_songs) < threshold:
            await send_message(
                ctx, "not enough archived songs in provided channels"
            )
            return

        if self.player.is_playing:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        try:
            await self.player.add_playlist(xm_channels, self._state.db)
        except Exception:
            self._log.error("error while trying to create playlist:")
            self._log.error(traceback.format_exc())
            await self.player.stop()
            await send_message(ctx, "something went wrong starting playlist")
        else:
            if len(xm_channels) == 1:
                await ctx.message.channel.send(
                    f"{ctx.message.author.mention} starting playing a "
                    f"playlist of random songs from "
                    f"**{xm_channels[0].pretty_name}** in "
                    f"**{ctx.message.author.voice.channel.mention}**"
                )
            else:
                channel_nums = ", ".join(
                    [f"#{x.channel_number}" for x in xm_channels]
                )
                await ctx.message.channel.send(
                    f"{ctx.message.author.mention} starting playing a "
                    f"playlist of random songs from **{channel_nums}** in "
                    f"**{ctx.message.author.voice.channel.mention}**"
                )

    @sxm.command(name="show", pass_context=True, no_pm=True, cls=SXMCommand)
    async def sxm_show(
        self, ctx: Context, show_id: Optional[str] = None
    ) -> None:
        """Adds a show to a play queue"""

        await self._play_archive_file(ctx, show_id, False)

    @sxm.command(name="shows", pass_context=True, cls=SXMCommand)
    async def sxm_shows(self, ctx: Context, search: str) -> None:
        """Searches for an archived show to play.
        Only returns the first 10 shows"""

        await self._search_archive(ctx, search, False)

    @sxm.command(name="song", pass_context=True, no_pm=True, cls=SXMCommand)
    async def sxm_song(
        self, ctx: Context, song_id: Optional[str] = None
    ) -> None:
        """Adds a song to a play queue"""

        await self._play_archive_file(ctx, song_id, True)

    @sxm.command(name="songs", pass_context=True, cls=SXMCommand)
    async def sxm_songs(self, ctx: Context, search: str) -> None:
        """Searches for an archived song to play.
        Only returns the first 10 songs"""

        await self._search_archive(ctx, search, True)
