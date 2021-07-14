from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Tuple, Union

from discord import AudioSource, Game, Message, Embed, errors
from discord.ext.commands import Command, Group
from discord_slash import SlashContext
from humanize import naturaltime

from sxm.models import XMChannel, XMLiveChannel, XMSong, XMCut
from sxm_player.models import Episode, Song, PlayerState

from .utils import (
    generate_embed_from_archived,
    get_art_url_by_size,
    send_message,
    generate_embed_from_cut,
)


@dataclass
class QueuedItem:
    audio_file: Union[Song, Episode, None] = None
    stream_data: Optional[Tuple[XMChannel, str]] = None

    source: AudioSource = None


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


class SXMActivity(Game):
    def __init__(
        self,
        start: Optional[int],
        radio_time: Optional[int],
        channel: XMChannel,
        live_channel: XMLiveChannel,
        **kwargs,
    ):

        self.timestamps = {"start": start}
        self._start = start
        self.details = "Test"

        self.assets = kwargs.pop("assets", {})
        self.party = kwargs.pop("party", {})
        self.application_id = kwargs.pop("application_id", None)
        self.url = kwargs.pop("url", None)
        self.flags = kwargs.pop("flags", 0)
        self.sync_id = kwargs.pop("sync_id", None)
        self.session_id = kwargs.pop("session_id", None)
        self._end = 0

        self.update_status(channel, live_channel, radio_time)

    def update_status(
        self,
        channel: XMChannel,
        live_channel: XMLiveChannel,
        radio_time: Optional[int],
    ) -> None:
        """Updates activity object from current channel playing"""

        self.state = "Playing music from SXM"
        self.name = f"SXM {channel.pretty_name}"
        self.large_image_url = None
        self.large_image_text = None

        latest_cut = live_channel.get_latest_cut(now=radio_time)
        if latest_cut is not None and isinstance(latest_cut.cut, XMSong):
            song = latest_cut.cut
            pretty_name = Song.get_pretty_name(song.title, song.artists[0].name)
            self.name = f"{pretty_name} on {self.name}"

            if song.album is not None:
                album = song.album
                if album.title is not None:
                    self.large_image_text = f"{album.title} by {song.artists[0].name}"

                self.large_image_url = get_art_url_by_size(album.arts, "MEDIUM")


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
    items: list[XMCut]
    latest: XMCut
    channel: XMChannel
    body: str

    @property
    def current(self) -> XMCut:
        return super().current

    def _get_footer(self, state: PlayerState):
        if self.current == self.latest:
            return f"Now Playing | {self.index+1}/{len(self.items)} Recent Songs"

        now = state.radio_time
        seconds_ago = int((now - self.current.time) / 1000)
        time_delta = timedelta(seconds=seconds_ago)
        time_string = naturaltime(time_delta)

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
