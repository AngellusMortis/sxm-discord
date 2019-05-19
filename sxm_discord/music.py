from enum import Enum, auto
from typing import List, Optional, Union

from discord import VoiceChannel, VoiceClient

from sxm_player.models import Episode, Song

from .models import QueuedItem


class PlayType(Enum):
    FILE = auto()
    HLS = auto()
    RANDOM = auto()


class AudioPlayer:
    play_type: Optional[PlayType] = None
    recent: List[Union[Episode, Song]]
    upcoming: List[Union[Episode, Song]]
    repeat: bool = False

    _current: Optional[QueuedItem] = None
    _voice: Optional[VoiceClient] = None
    _volume: float = 0.25

    def __init__(self):
        self.recent = []
        self.upcoming = []

    @property
    def is_playing(self) -> bool:
        """ Returns if `AudioPlayer` is playing audio """

        if self._voice is None or self._current is None:
            return False

        return self._voice.is_playing()

    @property
    def voice(self) -> Optional[VoiceClient]:
        """ Gets the voice client for audio player """
        return self._voice

    async def set_voice(self, channel: VoiceChannel) -> None:
        """ Sets voice channel for audio player """

        if self._voice is None:
            self._voice = await channel.connect()
        else:
            await self._voice.move_to(channel)

    @property
    def current(self) -> Optional[QueuedItem]:
        """ Returns current `Song` or `Episode` that is being played """

        if self._current is not None:
            return self._current
        return None

    @property
    def volume(self) -> float:
        """ Gets current volume level """

        return self._volume

    @volume.setter
    def volume(self, volume: float) -> None:
        """ Sets current volume level """

        if volume < 0.0:
            volume = 0.0
        elif volume > 1.0:
            volume = 1.0

        self._volume = volume
        if self._current is not None:
            self._current.source.volume = self._volume

    async def stop(self):
        self.play_type = None
        if self._voice is not None:
            await self._voice.disconnect()
            self._voice = None

    async def skip(self) -> bool:
        """ Skips current `QueueItem` """

        pass
