import logging
import os
import time
from datetime import datetime
from multiprocessing import Lock
from typing import List, Optional, Union

from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.session import Session

from sxm.models import XMChannel, XMLiveChannel

Base = declarative_base()


class Song(Base):  # type: ignore
    __tablename__ = "songs"

    guid: str = Column(String, primary_key=True)
    title: str = Column(String, index=True)
    artist: str = Column(String, index=True)
    album: str = Column(String, nullable=True)
    air_time: datetime = Column(DateTime)
    channel: str = Column(String)
    file_path: str = Column(String)

    @staticmethod
    def get_pretty_name(title: str, artist: str, bold: bool = False) -> str:
        """ Returns a formatted name of song """

        mod = ""
        if bold:
            mod = "**"

        return f'{mod}"{title}"{mod} by {mod}{artist}{mod}'

    @property
    def pretty_name(self) -> str:
        """ Returns a formatted name of song """

        return Song.get_pretty_name(self.title, self.artist)

    @property
    def bold_name(self) -> str:
        """ Returns a formatted name of song """

        return Song.get_pretty_name(self.title, self.artist, True)


class Episode(Base):  # type: ignore
    __tablename__ = "episodes"

    guid: str = Column(String, primary_key=True)
    title: str = Column(String, index=True)
    show: str = Column(String, nullable=True, index=True)
    air_time: datetime = Column(DateTime)
    channel: str = Column(String)
    file_path: str = Column(String)

    @staticmethod
    def get_pretty_name(
        title: str, show: str, air_time: datetime, bold: bool = False
    ) -> str:
        """ Returns a formatted name of show """

        mod = ""
        if bold:
            mod = "**"

        return f'{mod}"{title}"{mod} ({show}) from {air_time}'

    @property
    def pretty_name(self) -> str:
        """ Returns a formatted name of show """

        return Episode.get_pretty_name(self.title, self.show, self.air_time)

    @property
    def bold_name(self) -> str:
        """ Returns a formatted name of show """

        return Episode.get_pretty_name(
            self.title, self.show, self.air_time, True
        )


class DictState:
    """Class that uses a shared memory dictionary to populate attributes"""

    lock: Lock  # type: ignore
    _state_dict: dict
    _log: logging.Logger
    _lock_debuging: bool = False

    def __init__(self, state_dict: dict, lock: Lock):  # type: ignore
        self._lock = lock  # type: ignore
        self._state_dict = state_dict
        self._log = logging.getLogger("sxm_discord.shared_dict")

    def __getattr__(self, attr: str):
        if not attr.startswith("_") and self._state_dict is not None:
            acquired = self._optional_lock(f"get {attr}")

            if attr in self._state_dict:
                value = self._state_dict[attr]
                if acquired:
                    self._lock.release()
                return value
        else:
            raise AttributeError(
                "--%r object has no attribute %r" % (type(self).__name__, attr)
            )

    def __setattr__(self, attr: str, value) -> None:
        if not attr.startswith("_") and self._state_dict is not None:
            self._lock_debug(f"acquiring lock: set {attr}")
            with self._lock:
                self._lock_debug(f"acquired lock: set {attr}")
                if attr in self._state_dict:
                    self._state_dict[attr] = value
            self._lock_debug(f"released lock: set {attr}")
        super().__setattr__(attr, value)

    def _optional_lock(self, name):
        acquired = self._lock.acquire(False)
        if not acquired:
            self._lock_debug(f"failed to acquire lock: {name}")
        return acquired

    def _lock_debug(self, message):
        if self._lock_debuging:
            self._log.debug(message)


class XMState(DictState):
    """Class to store state SXM Radio player for Discord Bot"""

    _channels: Optional[List[XMChannel]] = None
    _live_update_time: Optional[int] = None
    _live: Optional[XMLiveChannel] = None
    _archive_folder: Optional[str] = None
    _processed_folder: Optional[str] = None
    _stream_folder: Optional[str] = None

    _db: Session = None
    _db_reset: bool = False

    def __init__(
        self,
        state_dict: dict,
        lock: Lock,  # type: ignore
        db_reset: bool = False,
    ):
        super().__init__(state_dict, lock)

        self._db_reset = False

    @staticmethod
    def init_state(state_dict: dict) -> None:
        """ Initializes a dictionary that will be used
        for a `XMState` object """

        state_dict["active_channel_id"] = None
        state_dict["stream_url"] = None
        state_dict["channels"] = []
        state_dict["start_time"] = None
        state_dict["live"] = None
        state_dict["processing_file"] = False
        state_dict["live_update_time"] = None
        state_dict["time_offset"] = None
        state_dict["output"] = None
        state_dict["hls_errors"] = None
        state_dict["runners"] = {}

    @property
    def channels(self) -> List[XMChannel]:
        """ Returns list of `XMChannel` """

        if self._channels is None:
            acquired = self._optional_lock("property.get channels")

            self._channels = []
            for channel in self._state_dict["channels"]:
                self._channels.append(XMChannel(channel))

            if acquired:
                self._lock.release()
        return self._channels

    @channels.setter
    def channels(self, value: dict) -> None:
        """ Sets channel key in internal `state_dict`. """

        self._lock_debug("acquiring lock: property.set channels")
        with self._lock:
            self._lock_debug("acquired lock: property.set channels")
            self._channels = None
            self._state_dict["channels"] = value
        self._lock_debug("released lock: property.set channels")

    @property
    def live(self) -> Union[XMLiveChannel, None]:
        """ Returns current `XMLiveChannel` """

        acquired = self._optional_lock("property.get live")
        last_update = self._state_dict["live_update_time"]
        now = int(time.time() * 1000)
        if self._live is None or self._live_update_time != last_update:
            if self._state_dict["live"] is not None:
                self._live_update_time = last_update
                self._live = XMLiveChannel(self._state_dict["live"])

                if self._live.tune_time is not None:
                    self._state_dict["time_offset"] = (
                        now - self._live.tune_time
                    )

                if self._state_dict["start_time"] is None:
                    if self._live.tune_time is None:
                        self._state_dict["start_time"] = now
                    else:
                        self._state_dict["start_time"] = self._live.tune_time
            else:
                self._state_dict["time_offset"] = 0

        if acquired:
            self._lock.release()
        return self._live

    @live.setter
    def live(self, value: dict) -> None:
        """ Sets live key in internal `state_dict`. """

        self._lock_debug("acquiring lock: property.set live")
        with self._lock:
            self._lock_debug("acquired lock: property.set live")
            self._live = None
            self._state_dict["start_time"] = None
            self._state_dict["live"] = value
            if value is not None:
                self._state_dict["live_update_time"] = time.time()
        self._lock_debug("released lock: property.set live")

    @property
    def radio_time(self) -> Union[int, None]:
        """ Returns current time for the radio """

        if self.live is None:
            return None
        # still working on offset:  - self.time_offset
        return int(time.time() * 1000)

    @property
    def start_time(self) -> Union[int, None]:
        """ Returns the start time for the current SXM channel """

        if self.live is None:
            return None
        return self._state_dict["start_time"]

    @property
    def archive_folder(self) -> Union[str, None]:
        """ Returns path to archive folder """

        if self._archive_folder is None:
            if self.output is not None:
                self._archive_folder = os.path.join(self.output, "archive")
        return self._archive_folder

    @property
    def processed_folder(self) -> Union[str, None]:
        """ Returns path to processed folder """

        if self._processed_folder is None:
            if self.output is not None:
                self._processed_folder = os.path.join(self.output, "processed")
        return self._processed_folder

    @property
    def stream_folder(self) -> Union[str, None]:
        """ Returns path to stream folder """

        if self._stream_folder is None:
            if self.output is not None:
                self._stream_folder = os.path.join(self.output, "streams")
        return self._stream_folder

    @property
    def db(self) -> Union[Session, None]:
        if self._db is None and self.processed_folder is not None:
            from .utils import init_db

            self._db = init_db(self.processed_folder, self._db_reset)
        return self._db

    def get_channel(self, name: str) -> Union[XMChannel, None]:
        """ Returns channel from list of `channels` with given name """

        name = name.lower()
        for channel in self.channels:
            if (
                channel.name.lower() == name
                or channel.id.lower() == name
                or channel.channel_number == name
            ):
                return channel
        return None

    def set_channel(self, channel_id: str) -> None:
        """ Sets active SXM channel """

        self._lock_debug("acquiring lock: set_channel")
        with self._lock:
            self._state_dict["active_channel_id"] = channel_id
            self._state_dict["live"] = None
            self._live = None
            self._state_dict["start_time"] = None

    def reset_channel(self) -> None:
        """ Removes active SXM channel """

        self._lock_debug("acquiring lock: reset_channel")
        with self._lock:
            self._state_dict["active_channel_id"] = None
            self._state_dict["live"] = None
            self._live = None
            self._state_dict["start_time"] = None

    def pop_hls_errors(self) -> Union[List[str], None]:
        errors = None

        self._lock_debug("acquiring lock: property.get hls_errors")
        with self._lock:
            self._lock_debug("acquired lock: property.get hls_errors")
            if self._state_dict["hls_errors"] is not None:
                errors = self._state_dict["hls_errors"]
                self._state_dict["hls_errors"] = None
        self._lock_debug("released lock: property.get hls_errors")
        return errors

    def push_hls_errors(self, errors) -> None:
        self._lock_debug("acquiring lock: property.set hls_errors")
        with self._lock:
            self._lock_debug("acquired lock: property.set hls_errors")
            if self._state_dict["hls_errors"] is not None:
                errors = self._state_dict["hls_errors"] + errors
            self._state_dict["hls_errors"] = errors
        self._lock_debug("released lock: property.set hls_errors")

    def set_runner(self, name, pid):
        self._lock_debug("acquiring lock: property.set runner")
        with self._lock:
            self._lock_debug("acquired lock: property.set runner")
            runners = self._state_dict["runners"]
            runners[name] = pid
            self._state_dict["runners"] = runners
        self._lock_debug("released lock: property.set runner")
