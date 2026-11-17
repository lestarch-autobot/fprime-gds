"""
fprime_gds.tui.model:

Thread-safe store between the GDS pipeline and the terminal UI. The pipeline's decoders (or a data transport that
decodes itself, e.g. yamcs) call `data_callback` on their own threads; the UI drains the store on a timer from its own
thread. Memory is bounded: one entry per channel and a capped event list.
"""
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.handlers import DataHandler

DEFAULT_MAX_EVENTS = 5000
# Longest text kept for one displayed field: bounds the width of table cells fed by downlinked data
MAX_FIELD_LENGTH = 1024
SEVERITY_ORDER = (
    "FATAL",
    "WARNING_HI",
    "WARNING_LO",
    "ACTIVITY_HI",
    "ACTIVITY_LO",
    "COMMAND",
    "DIAGNOSTIC",
)


def sanitize(value) -> str:
    """Make downlinked text safe to display

    Text from the flight software or ground system is untrusted: control characters (including ESC, which starts
    terminal escape sequences) are replaced and the length is capped.

    Args:
        value: value to display
    Returns:
        printable single-line text
    """
    text = str(value)
    if len(text) > MAX_FIELD_LENGTH:
        text = text[:MAX_FIELD_LENGTH] + "…"
    return "".join(char if char.isprintable() else "\N{REPLACEMENT CHARACTER}" for char in text)


def readable_time(time_obj) -> str:
    """Readable time of a GDS data object, tolerating a missing or malformed time"""
    try:
        readable = sanitize(time_obj.to_readable())
        # Time of day to the millisecond, as displayed; a format without a date part is kept whole
        return readable.split("T", 1)[1][:12] if "T" in readable else readable
    except Exception:  # A bad time must not drop the datum
        return "--"


@dataclass(frozen=True)
class EventRow:
    """One event as displayed"""

    sequence: int
    time: str
    severity: str
    name: str
    message: str

    @property
    def text(self) -> str:
        """Text the filter is matched against: the displayed row"""
        return f"{self.time} {self.severity} {self.name} {self.message}"


@dataclass(frozen=True)
class ChannelRow:
    """Latest reading of one channel as displayed"""

    channel_id: int
    time: str
    name: str
    value: str
    limit: Optional[str]

    @property
    def text(self) -> str:
        """Text the filter is matched against: the displayed row"""
        return f"{self.time} {self.name} {self.value}"


def channel_limit(ch_data: ChData) -> Optional[str]:
    """Limit band a channel reading falls in: "red", "orange", "yellow", or None when in limits or not numeric"""
    value = ch_data.get_val()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    template = ch_data.template
    bands = (
        ("red", template.get_low_red(), template.get_high_red()),
        ("orange", template.get_low_orange(), template.get_high_orange()),
        ("yellow", template.get_low_yellow(), template.get_high_yellow()),
    )
    for name, low, high in bands:
        if (low is not None and value < low) or (high is not None and value > high):
            return name
    return None


class TuiModel(DataHandler):
    """Store of the latest channel readings and recent events, fed by the pipeline and drained by the UI"""

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS):
        """Create the store

        Args:
            max_events: number of most recent events retained
        """
        assert max_events > 0, "max_events must be positive"
        self._lock = threading.Lock()
        self._channels: Dict[int, ChannelRow] = {}
        self._dirty_channels: Dict[int, None] = {}  # Insertion-ordered set
        self._events: Deque[EventRow] = deque(maxlen=max_events)
        self._pending_events: Deque[EventRow] = deque(maxlen=max_events)
        self._sequence = 0
        self._dropped = 0

    def data_callback(self, data, sender=None):
        """Receive a decoded channel or event from the pipeline; other data is ignored

        Called on pipeline/transport threads. Never raises: one malformed datum must not stop the data flow.
        """
        try:
            if isinstance(data, ChData):
                self._add_channel(data)
            elif isinstance(data, EventData):
                self._add_event(data)
        except Exception:
            with self._lock:
                self._dropped += 1

    def _add_channel(self, ch_data: ChData):
        """Record the latest reading of a channel"""
        row = ChannelRow(
            channel_id=ch_data.template.get_id(),
            time=readable_time(ch_data.time),
            name=sanitize(ch_data.template.get_full_name()),
            value=sanitize(ch_data.get_display_text()),
            limit=channel_limit(ch_data),
        )
        with self._lock:
            self._channels[row.channel_id] = row
            self._dirty_channels[row.channel_id] = None

    def _add_event(self, event_data: EventData):
        """Record an event"""
        severity = str(getattr(event_data.get_severity(), "name", event_data.get_severity()))
        with self._lock:
            self._sequence += 1
            row = EventRow(
                sequence=self._sequence,
                time=readable_time(event_data.time),
                severity=sanitize(severity),
                name=sanitize(event_data.template.get_full_name()),
                message=sanitize(event_data.get_display_text()),
            )
            self._events.append(row)
            self._pending_events.append(row)

    def drain(self) -> Tuple[List[ChannelRow], List[EventRow]]:
        """Take the channels updated and the events received since the last drain

        Returns:
            tuple of updated channel rows and new event rows (oldest first)
        """
        with self._lock:
            channels = [self._channels[channel_id] for channel_id in self._dirty_channels]
            events = list(self._pending_events)
            self._dirty_channels.clear()
            self._pending_events.clear()
        return channels, events

    def channels(self) -> List[ChannelRow]:
        """Latest reading of every channel seen, sorted by channel name"""
        with self._lock:
            rows = list(self._channels.values())
        return sorted(rows, key=lambda row: row.name)

    def events(self) -> List[EventRow]:
        """Retained events, oldest first"""
        with self._lock:
            return list(self._events)

    def event_count(self) -> int:
        """Number of events retained"""
        with self._lock:
            return len(self._events)

    def clear_events(self):
        """Forget all retained events"""
        with self._lock:
            self._events.clear()
            self._pending_events.clear()

    @property
    def dropped(self) -> int:
        """Number of data items that could not be displayed"""
        with self._lock:
            return self._dropped
