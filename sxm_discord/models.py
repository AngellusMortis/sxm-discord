from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple, Union

from discord import Embed, Game, Message, PCMVolumeTransformer, errors
from discord.ext.commands import Command, Group
from discord_slash import SlashContext  # type: ignore
from humanize import naturaltime  # type: ignore
from sxm.models import XMChannel, XMCutMarker, XMLiveChannel, XMSong
from sxm_player.models import Episode, PlayerState, Song

from .utils import (
    generate_embed_from_archived,
    generate_embed_from_cut,
    get_art_url_by_size,
    send_message,
)


@dataclass
class QueuedItem:
    audio_file: Union[Song, Episode, None] = None
    stream_data: Optional[Tuple[XMChannel, str]] = None

    source: Optional[PCMVolumeTransformer] = None


class AudioQueuedItem(QueuedItem):
    audio_file: Union[Song, Episode]


class MusicCommand(Command):
    @property
    def cog_name(self):
        return "Music"


class MusicPlayerGroup(Group):
    @property
    def cog_name(self):
        return "Music Player"


class SXMCommand(Command):
    @property
    def cog_name(self):
        return "SXM Player"


class SongActivity(Game):
    def __init__(
        self,
        song: Song,
        **kwargs,
    ):
        self._start = self._end = 0.0
        self.assets = kwargs.pop("assets", {})
        self.party = kwargs.pop("party", {})
        self.application_id = kwargs.pop("application_id", None)
        self.url = kwargs.pop("url", None)
        self.flags = kwargs.pop("flags", 0)
        self.sync_id = kwargs.pop("sync_id", None)
        self.session_id = kwargs.pop("session_id", None)

        self.update_status(song)

    def update_status(
        self, song: Optional[Song], state: str = "Playing music", name_suffix: str = ""
    ) -> None:
        """Updates activity object from current channel playing"""

        self.state = state
        self.name = self.details = name_suffix

        if song is not None:
            self.name = self.details = song.pretty_name + name_suffix
            self.large_image_url = song.image_url
            if song.album is not None:
                self.large_image_text = f"{song.album} by {song.artist}"


class SXMActivity(SongActivity):
    def __init__(
        self,
        start: Optional[datetime],
        radio_time: Optional[datetime],
        channel: XMChannel,
        live_channel: XMLiveChannel,
        **kwargs,
    ):

        if start is None:
            self._start = 0.0
        else:
            self._start = start.timestamp() * 1000.0
        self._end = 0.0
        self.assets = kwargs.pop("assets", {})
        self.party = kwargs.pop("party", {})
        self.application_id = kwargs.pop("application_id", None)
        self.url = kwargs.pop("url", None)
        self.flags = kwargs.pop("flags", 0)
        self.sync_id = kwargs.pop("sync_id", None)
        self.session_id = kwargs.pop("session_id", None)

        suffix = f"SXM {channel.pretty_name}"
        song = self.create_song(channel, live_channel, radio_time)
        if song is None:
            episode = live_channel.get_latest_episode(now=radio_time)
            if episode is not None:
                suffix = f'"{episode.episode.long_title}" on {suffix}'
        else:
            suffix = f" on {suffix}"

        self.update_status(
            song,
            state="Playing music from SXM",
            name_suffix=suffix,
        )

    def create_song(
        self,
        channel: XMChannel,
        live_channel: XMLiveChannel,
        radio_time: Optional[datetime],
    ) -> Optional[Song]:
        """Updates activity object from current channel playing"""

        latest_cut = live_channel.get_latest_cut(now=radio_time)
        if latest_cut is not None and isinstance(latest_cut.cut, XMSong):
            image_url = (
                None
                if latest_cut.cut.album is None
                else get_art_url_by_size(latest_cut.cut.album.arts, "MEDIUM")
            )
            return Song(
                guid="",
                title=latest_cut.cut.title,
                artist=latest_cut.cut.artists[0].name,
                air_time=latest_cut.time,
                channel=channel.id,
                file_path="",
                image_url=image_url,
            )

        return None


class ReactionCarousel:
    items: list
    index: int = 0
    last_update: Optional[datetime] = None
    message: Optional[Message] = None

    @property
    def current(self):
        return self.items[self.index]

    def get_message_kwargs(self, state: PlayerState) -> dict:
        raise NotImplementedError()

    async def update_message(
        self, message: Optional[str] = None, embed: Optional[Embed] = None
    ):
        raise NotImplementedError()

    async def refresh_message(self, client):
        try:
            self.message = await client.get_channel(
                self.message.channel.id
            ).fetch_message(self.message.id)
        except errors.NotFound:
            self.message = None

    async def clear_reactions(self):
        if self.message is None:
            return

        for reaction in self.message.reactions:
            await reaction.clear()

    async def handle_reaction(self, state: PlayerState, emoji: str):
        if emoji == "⬅️":
            self.index = max(0, self.index - 1)
        elif emoji == "➡️":
            self.index = min(len(self.items), self.index + 1)

        await self.update(state)

    async def update(self, state: PlayerState, ctx: Optional[SlashContext] = None):
        if self.message is None:
            self.message = await send_message(ctx, **self.get_message_kwargs(state))
        else:
            await self.update_message(**self.get_message_kwargs(state))

        await self.clear_reactions()

        if self.index > 0:
            await self.message.add_reaction("⬅️")
        if self.index < (len(self.items) - 1):
            await self.message.add_reaction("➡️")

        self.last_update = datetime.now()


@dataclass
class SXMCutCarousel(ReactionCarousel):
    items: list[XMCutMarker]
    latest: XMCutMarker
    channel: XMChannel
    body: str

    @property
    def current(self) -> XMCutMarker:
        return super().current

    def _get_footer(self, state: PlayerState):
        if self.current == self.latest:
            return f"Now Playing | {self.index+1}/{len(self.items)} Recent Songs"

        now = state.radio_time or datetime.now(timezone.utc)
        time_string = naturaltime(now - self.current.time)

        return (
            f"About {time_string} ago | "
            f"{self.index+1}/{len(self.items)} Recent Songs"
        )

    async def update_message(
        self, message: Optional[str] = None, embed: Optional[Embed] = None
    ):
        if self.message is not None and embed is not None:
            await self.message.edit(embed=embed)

    def get_message_kwargs(self, state: PlayerState) -> dict:
        if state.live is None:
            raise ValueError("Nothing is playing")

        episode = state.live.get_latest_episode(self.latest.time)

        return {
            "message": self.body,
            "embed": generate_embed_from_cut(
                self.channel,
                self.current,
                episode,
                footer=self._get_footer(state),
            ),
        }


@dataclass
class ArchivedSongCarousel(ReactionCarousel):
    items: list[Union[Song, Episode]]
    body: str

    @property
    def current(self) -> Song:
        return super().current

    def _get_footer(self):
        return f"GUID: {self.current.guid} | {self.index+1}/{len(self.items)} Songs"

    async def update_message(
        self, message: Optional[str] = None, embed: Optional[Embed] = None
    ):
        if self.message is not None and embed is not None:
            await self.message.edit(embed=embed)

    def get_message_kwargs(self, state: PlayerState) -> dict:
        return {
            "message": self.body,
            "embed": generate_embed_from_archived(
                self.current, footer=self._get_footer()
            ),
        }


@dataclass
class UpcomingSongCarousel(ArchivedSongCarousel):
    latest: Union[Song, Episode, None] = None

    def _get_footer(self):
        if self.current == self.latest:
            message = "Playing Next"
        else:
            message = f"{self.index+1} Away"

        return f"{message} | {self.index+1}/{len(self.items)} Songs"
