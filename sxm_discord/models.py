from dataclasses import dataclass
from typing import Optional, Tuple, Union

from discord import AudioSource, Game
from discord.ext.commands import Command, Group

from sxm.models import XMChannel, XMLiveChannel, XMSong
from sxm_player.models import Episode, Song

from .utils import get_art_url_by_size


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
        """ Updates activity object from current channel playing """

        self.state = "Playing music from SXM"
        self.name = f"SXM {channel.pretty_name}"
        self.large_image_url = None
        self.large_image_text = None

        latest_cut = live_channel.get_latest_cut(now=radio_time)
        if latest_cut is not None and isinstance(latest_cut.cut, XMSong):
            song = latest_cut.cut
            pretty_name = Song.get_pretty_name(
                song.title, song.artists[0].name
            )
            self.name = f"{pretty_name} on {self.name}"

            if song.album is not None:
                album = song.album
                if album.title is not None:
                    self.large_image_text = (
                        f"{album.title} by {song.artists[0].name}"
                    )

                self.large_image_url = get_art_url_by_size(
                    album.arts, "MEDIUM"
                )
