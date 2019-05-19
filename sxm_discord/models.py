from dataclasses import dataclass
from typing import Union, Optional
from discord import AudioSource
from sxm_player.models import Song, Episode
from discord.ext.commands import Command, Group


@dataclass
class QueuedItem:
    audio_file: Union[Song, Episode, None] = None
    live: Optional[str] = None

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
