"""Tests of the store between the GDS pipeline and the terminal UI"""
import threading

import pytest

from fprime_gds.common.models.serialize.numerical_types import F32Type
from fprime_gds.tui.model import MAX_FIELD_LENGTH, TuiModel, sanitize

from .helpers import make_channel, make_event


def test_sanitize_replaces_control_characters():
    assert sanitize("a\x1b[31mb\nc\x07") == "a\ufffd[31mb\ufffdc\ufffd"


def test_sanitize_caps_length():
    assert len(sanitize("x" * (MAX_FIELD_LENGTH + 500))) == MAX_FIELD_LENGTH + 1


def test_channels_keep_latest_reading():
    model = TuiModel()
    model.data_callback(make_channel(1, "B", 5))
    model.data_callback(make_channel(2, "A", 7))
    model.data_callback(make_channel(1, "B", 6))
    rows = model.channels()
    assert [(row.name, row.value) for row in rows] == [("comp.A", "7"), ("comp.B", "6")]


def test_drain_returns_updates_once():
    model = TuiModel()
    model.data_callback(make_channel(1, "B", 5))
    model.data_callback(make_channel(1, "B", 6))
    model.data_callback(make_event(1, "EV", "ACTIVITY_HI", "hello"))
    channels, events = model.drain()
    assert [row.value for row in channels] == ["6"]
    assert [(row.severity, row.name, row.message) for row in events] == [("ACTIVITY_HI", "comp.EV", "hello")]
    assert model.drain() == ([], [])
    assert len(model.channels()) == 1 and len(model.events()) == 1


def test_events_are_capped_and_sequenced():
    model = TuiModel(max_events=3)
    for index in range(5):
        model.data_callback(make_event(1, "EV", "COMMAND", f"message {index}"))
    assert [row.message for row in model.events()] == ["message 2", "message 3", "message 4"]
    assert [row.sequence for row in model.events()] == [3, 4, 5]
    _, pending = model.drain()
    assert [row.sequence for row in pending] == [3, 4, 5]


def test_clear_events():
    model = TuiModel()
    model.data_callback(make_event(1, "EV", "COMMAND", "x"))
    model.clear_events()
    assert model.events() == [] and model.drain() == ([], [])


def test_event_text_is_sanitized():
    model = TuiModel()
    model.data_callback(make_event(1, "EV", "WARNING_HI", "bad \x1b]0;title\x07 [bold]text[/bold]"))
    message = model.events()[0].message
    assert "\x1b" not in message and "\x07" not in message
    assert "[bold]text[/bold]" in message


@pytest.mark.parametrize(
    "value, expected",
    [(50.0, None), (81.0, "yellow"), (91.0, "orange"), (99.0, "red"), (-1.0, "red"), (5.0, "yellow")],
)
def test_channel_limits(value, expected):
    model = TuiModel()
    model.data_callback(
        make_channel(
            1, "T", value, type_class=F32Type, low_red=0.0, low_yellow=10.0, high_yellow=80.0, high_orange=90.0, high_red=95.0
        )
    )
    assert model.channels()[0].limit == expected


def test_unrelated_and_malformed_data_do_not_raise():
    model = TuiModel()
    model.data_callback(b"raw bytes")
    model.data_callback(None)
    broken = make_channel(1, "B", 5)
    broken.template = None
    model.data_callback(broken)
    assert model.dropped == 1
    assert model.channels() == []


def test_concurrent_producers():
    model = TuiModel(max_events=100)
    per_thread = 500

    def produce(offset):
        for index in range(per_thread):
            model.data_callback(make_event(1, "EV", "COMMAND", f"{offset}-{index}"))
            model.data_callback(make_channel(offset, f"C{offset}", index))

    threads = [threading.Thread(target=produce, args=(offset,)) for offset in range(4)]
    for thread in threads:
        thread.start()
    drained = 0
    while any(thread.is_alive() for thread in threads):
        drained += len(model.drain()[1])
    for thread in threads:
        thread.join()
    sequences = [row.sequence for row in model.events()]
    assert len(sequences) == 100
    assert sequences == list(range(4 * per_thread - 99, 4 * per_thread + 1))
    assert len(model.channels()) == 4
