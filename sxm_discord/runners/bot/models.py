import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Union

from discord import AudioSource, FFmpegPCMAudio, Game
from discord.ext.commands import Command, CommandError, Group

from sxm.models import XMChannel, XMImage, XMLiveChannel, XMSong

from ...models import Song, Episode, XMState


class MusicCommand(Command):
    @property
    def cog_name(self):
        return "Music"


class MusicPlayerGroup(Group):
    @property
    def cog_name(self):
        return "Music Player"


class PlexCommand(Command):
    @property
    def cog_name(self):
        return "Plex Player"


class SXMCommand(Command):
    @property
    def cog_name(self):
        return
