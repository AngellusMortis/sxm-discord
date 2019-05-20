import asyncio
import logging
import traceback
from enum import Enum, auto
from random import SystemRandom
from typing import List, Optional, Tuple, Union

from discord import (
    FFmpegPCMAudio,
    PCMVolumeTransformer,
    VoiceChannel,
    VoiceClient,
)
from sqlalchemy import and_
from sqlalchemy.orm.session import Session

from sxm.models import XMChannel
from sxm_player.models import Episode, Song
from sxm_player.queue import Event, EventMessage

from .models import QueuedItem


class PlayType(Enum):
    FILE = auto()
    LIVE = auto()
    RANDOM = auto()


class AudioPlayer:
    play_type: Optional[PlayType] = None
    recent: List[Union[Episode, Song]]
    upcoming: List[Union[Episode, Song]]
    repeat: bool = False

    _event_queue: Event
    _log: logging.Logger
    _loop: asyncio.AbstractEventLoop
    _player_event: asyncio.Event
    _player_queue: asyncio.Queue
    _random: SystemRandom
    _shutdown_event: asyncio.Event

    _current: Optional[QueuedItem] = None
    _playlist_data: Optional[Tuple[List[XMChannel], Session]] = None
    _voice: Optional[VoiceClient] = None
    _volume: float = 0.25

    def __init__(self, event_queue: Event, loop: asyncio.AbstractEventLoop):

        self._event_queue = event_queue
        self._log = logging.getLogger("sxm_discord.player")
        self._loop = loop
        self._player_event = asyncio.Event()
        self._player_queue = asyncio.Queue()
        self._random = SystemRandom()
        self._shutdown_event = asyncio.Event()

        self.recent = []
        self.upcoming = []

        self._loop.create_task(self._audio_player())

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

    async def stop(self, disconnect=True):
        """ Stops the `AudioPlayer` """

        self._log.debug(f"player stop: {disconnect}")

        while not self._player_queue.empty():
            self._player_queue.get_nowait()

        if self._current is not None:
            if self._current.source is not None:
                try:
                    self._current.source.cleanup()
                except ProcessLookupError:
                    pass
            self._current = None

        self.recent = []
        self.upcoming = []
        self._playlist_data = None

        if self._voice is not None:
            if self._voice.is_playing():
                self._voice.stop()

            if disconnect:
                # clean up any existing HLS stream
                if self.play_type == PlayType.LIVE:
                    self._event_queue.safe_put(
                        EventMessage("discord", Event.KILL_HLS_STREAM, None)
                    )

                # reset voice
                await self._voice.disconnect()
                self._voice = None

        self.play_type = None

    async def skip(self) -> bool:
        """ Skips current `QueueItem` """

        self._log.debug("skiping song")
        if self._voice is not None:
            if self._player_queue.qsize() < 1:
                await self.stop()
            else:
                self._voice.stop()
            return True
        return False

    async def cleanup(self):
        self._song_end()
        self._shutdown_event.set()

        if self._current is not None and self._current.source is not None:
            self._current.source.cleanup()

    async def add_live_stream(
        self, channel: XMChannel, stream_url=None
    ) -> bool:
        """ Adds HLS live stream to playing queue """

        if self.play_type is None:
            self.play_type = PlayType.LIVE
            self._log.debug(f"adding live stream: {channel} ({stream_url})")
            await self._add(stream_data=(channel, stream_url))
            return True

        self._log.warning(
            "Could not add HLS stream, something is already playing: "
            f"{self.play_type}"
        )
        return False

    async def add_playlist(
        self, xm_channels: List[XMChannel], db: Session
    ) -> bool:
        """ Creates a playlist of random songs from an channel """

        if self.play_type is None:
            self._log.debug(f"adding playlist: {xm_channels}")
            self._playlist_data = (xm_channels, db)

            for _ in range(5):
                await self._add_random_playlist_song()

            self.play_type = PlayType.RANDOM
            return True

        self._log.warning(
            "Could not add random playlist, something is already playing: "
            f"{self.play_type}"
        )
        return False

    async def add_file(self, file_info: Union[Song, Episode]) -> bool:
        """ Adds file to playing queue """

        if self.play_type == PlayType.LIVE:
            self._log.warning(
                "Could not add file stream, HLS stream is already playing"
            )
            return False
        elif self.play_type is None:
            self.play_type = PlayType.FILE

        self._log.debug(f"adding file: {file_info}")
        await self._add(file_info=file_info)
        return True

    async def _add(
        self,
        file_info: Union[Song, Episode, None] = None,
        stream_data: Optional[Tuple[XMChannel, Optional[str]]] = None,
    ) -> None:
        """ Adds item to playing queue """

        if self._voice is None:
            self._discard("Voice client is not set")
            return

        item: Optional[QueuedItem] = None
        if stream_data is None:
            item = QueuedItem(audio_file=file_info, stream_data=None)
            self.upcoming.append(item.audio_file)
        elif stream_data[1] is None:
            self._log.debug(
                f"trigging HLS stream for channel {stream_data[0].id}"
            )
            success = self._event_queue.safe_put(
                EventMessage(
                    "discord",
                    Event.TRIGGER_HLS_STREAM,
                    (stream_data[0].id, "udp"),
                )
            )

            if not success:
                self._log.warning("Could not trigger HLS stream")
        else:
            item = QueuedItem(
                audio_file=None, stream_data=(stream_data[0], stream_data[1])
            )

        if item is not None:
            self._log.debug(f"adding queued item: {item}")
            await self._player_queue.put(item)

    async def _add_random_playlist_song(self) -> bool:
        if self._playlist_data is None:
            self._discard("Playlist data missing")
            return False

        channel_ids = [x.id for x in self._playlist_data[0]]

        songs = (
            self._playlist_data[1]
            .query(Song.title, Song.artist)
            .filter(Song.channel.in_(channel_ids))  # type: ignore
        )
        songs = songs.distinct().all()

        song = self._random.choice(songs)
        song = (
            self._playlist_data[1]
            .query(Song)
            .filter(
                and_(
                    Song.channel.in_(channel_ids),  # type: ignore
                    Song.title == song[0],
                    Song.artist == song[1],
                )
            )
            .first()
        )

        return await self.add_file(file_info=song)

    async def _audio_player(self) -> None:
        """ Bot task to manage and run the audio player """

        while not self._shutdown_event.is_set():
            self._player_event.clear()
            self._current = await self._player_queue.get()
            self._log.debug(f"audio player, new item: {self._current}")

            # validate event before starting to block
            if self._shutdown_event.is_set():
                return

            if self._voice is None:
                self._discard("No voice channel")
                continue

            log_item = ""
            # wait until player is instructed to start playing
            if self.play_type is None or self._current is None:
                self._discard("nothing playing")
                continue
            elif self.play_type == PlayType.LIVE:
                if self._current.audio_file is not None:
                    self._discard("not HLS")
                    continue
                elif self._current.stream_data is None:
                    self._discard("missing HLS")
                    continue

                log_item = self._current.stream_data[0].id
                self._current.source = FFmpegPCMAudio(
                    self._current.stream_data[1],
                    before_options="-f mpegts",
                    options="-loglevel fatal",
                )
            else:
                if self._current.stream_data is not None:
                    self._discard("not file")
                    continue
                elif self._current.audio_file is None:
                    self._discard("missing file")
                    continue

                if len(self.upcoming) > 0:
                    self.upcoming.pop(0)

                self.recent.insert(0, self._current.audio_file)
                self.recent = self.recent[:10]

                log_item = self._current.audio_file.file_path
                self._current.source = FFmpegPCMAudio(
                    self._current.audio_file.file_path
                )

            self._current.source = PCMVolumeTransformer(
                self._current.source, volume=self._volume
            )
            self._log.info(f"playing {log_item}")

            self._voice.play(self._current.source, after=self._song_end)

            await self._player_event.wait()

            if (
                self.play_type == PlayType.RANDOM
                and self._player_queue.qsize() < 5
            ):
                await self._add_random_playlist_song()
            elif self.repeat and self.play_type == PlayType.FILE:
                try:
                    await self._add(file_info=self._current.audio_file)
                except Exception:
                    self._log.error(
                        "Exception while re-add song to queue for repeat:"
                    )
                    self._log.error(traceback.format_exc())

            self._current = None

    def _discard(self, message: str):
        self._log.debug(f"discarding item, {message}")
        self.play_type = None
        self._current = None

    def _song_end(self, error: Optional[Exception] = None) -> None:
        """ Callback for `discord.AudioPlayer`/`discord.VoiceClient` """

        self._log.debug("song end")
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._player_event.set)
