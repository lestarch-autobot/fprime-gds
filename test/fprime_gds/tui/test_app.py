"""Headless tests of the terminal UI driven through Textual's pilot"""
import asyncio
import threading

import pytest

pytest.importorskip("textual")

from textual.widgets import Checkbox, DataTable, Input, OptionList, Select, Static  # noqa: E402

from fprime_gds.tui.app import SEVERITY_STYLES, FprimeTui, HelpScreen  # noqa: E402
from fprime_gds.tui.model import TuiModel  # noqa: E402

from .helpers import make_channel, make_commands, make_event  # noqa: E402


class Sender:
    """Stand-in for the pipeline's send_command"""

    def __init__(self):
        self.sent = []
        self.error = None
        self.thread_names = []

    def __call__(self, name, arguments):
        self.thread_names.append(threading.current_thread().name)
        if self.error is not None:
            raise self.error
        self.sent.append((name, list(arguments)))


def run(scenario, max_events=5000, size=(160, 48)):
    """Run an async scenario(app, pilot, model, sender) against a headless app"""

    async def runner():
        model = TuiModel(max_events=max_events)
        sender = Sender()
        app = FprimeTui(model, make_commands(), sender, "yamcs", "Dictionary.json", max_events=max_events)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app, pilot, model, sender)

    asyncio.run(runner())


async def refresh(app, pilot):
    """Move model data into the tables now instead of waiting for the timer"""
    app.refresh_data()
    await pilot.pause()


async def settle(app, pilot):
    """Wait for send workers and the messages they post"""
    await app.workers.wait_for_complete()
    await pilot.pause()


def column(table, key):
    """Plain text of one column of a table, top to bottom"""
    return [table.get_cell(row_key, key).plain for row_key in table.rows]


def text_of(app, selector):
    """Plain text of a Static"""
    return str(app.query_one(selector, Static).render())


async def type_text(pilot, text):
    """Type text into the focused widget"""
    await pilot.press(*["space" if char == " " else char for char in text])
    await pilot.pause()


# ---- Telemetry ----


def test_telemetry_shows_latest_values_sorted():
    async def scenario(app, pilot, model, sender):
        model.data_callback(make_channel(1, "Zeta", 1))
        model.data_callback(make_channel(2, "Alpha", 2))
        await refresh(app, pilot)
        table = app.query_one("#telemetry-table", DataTable)
        assert column(table, "name") == ["comp.Alpha", "comp.Zeta"]
        model.data_callback(make_channel(1, "Zeta", 42, seconds=2000))
        await refresh(app, pilot)
        assert column(table, "value") == ["2", "42"]
        assert table.row_count == 2

    run(scenario)


def test_telemetry_filter():
    async def scenario(app, pilot, model, sender):
        for index, name in enumerate(["cpu0", "cpu1", "memory", "disk"]):
            model.data_callback(make_channel(index, name, index))
        await refresh(app, pilot)
        table = app.query_one("#telemetry-table", DataTable)
        await pilot.press("f3", "slash")
        assert app.focused.id == "telemetry-filter"
        await type_text(pilot, "CPU")
        assert column(table, "name") == ["comp.cpu0", "comp.cpu1"]
        await type_text(pilot, " -or- disk")
        assert column(table, "name") == ["comp.cpu0", "comp.cpu1", "comp.disk"]
        # A channel first seen while filtered appears only when it matches
        model.data_callback(make_channel(10, "cpu2", 9))
        model.data_callback(make_channel(11, "other", 9))
        await refresh(app, pilot)
        assert column(table, "name") == ["comp.cpu0", "comp.cpu1", "comp.cpu2", "comp.disk"]
        assert "4/6" in str(app.query_one("#telemetry").border_subtitle)
        app.query_one("#telemetry-filter", Input).value = ""
        await pilot.pause()
        assert table.row_count == 6

    run(scenario)


def test_telemetry_filter_on_value_follows_updates():
    async def scenario(app, pilot, model, sender):
        model.data_callback(make_channel(1, "mode", 111))
        await refresh(app, pilot)
        app.query_one("#telemetry-filter", Input).value = "111"
        await pilot.pause()
        table = app.query_one("#telemetry-table", DataTable)
        assert table.row_count == 1
        model.data_callback(make_channel(1, "mode", 222))
        await refresh(app, pilot)
        assert table.row_count == 0
        model.data_callback(make_channel(1, "mode", 111))
        await refresh(app, pilot)
        assert table.row_count == 1

    run(scenario)


# ---- Events ----


def test_events_listed_in_order_and_coloured_by_severity():
    async def scenario(app, pilot, model, sender):
        for index, severity in enumerate(SEVERITY_STYLES):
            model.data_callback(make_event(index, f"E{index}", severity, f"message {index}"))
        await refresh(app, pilot)
        table = app.query_one("#events-table", DataTable)
        assert column(table, "severity") == list(SEVERITY_STYLES)
        assert column(table, "message") == [f"message {index}" for index in range(len(SEVERITY_STYLES))]
        for row_key, severity in zip(table.rows, SEVERITY_STYLES):
            assert str(table.get_cell(row_key, "message").style) == SEVERITY_STYLES[severity]
        assert len(set(SEVERITY_STYLES.values())) == len(SEVERITY_STYLES)

    run(scenario)


def test_event_text_filter_and_severity_toggles():
    async def scenario(app, pilot, model, sender):
        model.data_callback(make_event(1, "Started", "ACTIVITY_HI", "engine started"))
        model.data_callback(make_event(2, "Hot", "WARNING_HI", "engine hot"))
        model.data_callback(make_event(3, "Ping", "DIAGNOSTIC", "ping"))
        await refresh(app, pilot)
        table = app.query_one("#events-table", DataTable)
        await pilot.press("f4", "slash")
        assert app.focused.id == "events-filter"
        await type_text(pilot, "ENGINE")
        assert column(table, "name") == ["comp.Started", "comp.Hot"]
        app.query_one("#severity-WARNING_HI", Checkbox).value = False
        await pilot.pause()
        assert column(table, "name") == ["comp.Started"]
        # New events obey the filters as they arrive
        model.data_callback(make_event(2, "Hot", "WARNING_HI", "engine hot"))
        model.data_callback(make_event(1, "Started", "ACTIVITY_HI", "engine started again"))
        await refresh(app, pilot)
        assert column(table, "message") == ["engine started", "engine started again"]
        assert "filtered" in str(app.query_one("#events").border_subtitle)
        app.query_one("#severity-WARNING_HI", Checkbox).value = True
        app.query_one("#events-filter", Input).value = ""
        await pilot.pause()
        assert table.row_count == 5

    run(scenario)


def test_events_capped():
    async def scenario(app, pilot, model, sender):
        table = app.query_one("#events-table", DataTable)
        for index in range(25):
            model.data_callback(make_event(1, "EV", "COMMAND", f"message {index}"))
            if index % 4 == 0:
                await refresh(app, pilot)
        await refresh(app, pilot)
        assert column(table, "message") == [f"message {index}" for index in range(15, 25)]

    run(scenario, max_events=10)


def test_event_flood_rebuilds():
    async def scenario(app, pilot, model, sender):
        for index in range(1200):
            model.data_callback(make_event(1, "EV", "COMMAND", f"message {index}"))
        await refresh(app, pilot)
        table = app.query_one("#events-table", DataTable)
        assert table.row_count == 1000
        assert column(table, "message")[-1] == "message 1199"
        assert table.cursor_row == 999

    run(scenario, max_events=1000)


def test_events_follow_tail_unless_scrolled_back():
    async def scenario(app, pilot, model, sender):
        table = app.query_one("#events-table", DataTable)
        for index in range(100):
            model.data_callback(make_event(1, "EV", "COMMAND", f"message {index}"))
        await refresh(app, pilot)
        assert table.cursor_row == 99
        table.move_cursor(row=10)
        model.data_callback(make_event(1, "EV", "COMMAND", "late"))
        await refresh(app, pilot)
        assert table.cursor_row == 10

    run(scenario)


def test_clear_events():
    async def scenario(app, pilot, model, sender):
        model.data_callback(make_event(1, "EV", "COMMAND", "x"))
        await refresh(app, pilot)
        await pilot.press("ctrl+l")
        assert app.query_one("#events-table", DataTable).row_count == 0
        assert model.events() == []

    run(scenario)


def test_markup_and_escapes_in_downlinked_text_are_inert():
    async def scenario(app, pilot, model, sender):
        hostile = "[bold red]x[/] [@click=app.quit]y[/] \x1b[2J \x1b]0;t\x07"
        model.data_callback(make_event(1, "EV", "WARNING_LO", hostile))
        await refresh(app, pilot)
        message = column(app.query_one("#events-table", DataTable), "message")[0]
        assert "[bold red]x[/] [@click=app.quit]y[/]" in message
        assert "\x1b" not in message and "\x07" not in message

    run(scenario)


# ---- Commanding ----


def test_send_from_command_string():
    async def scenario(app, pilot, model, sender):
        assert app.focused.id == "command-text"
        await type_text(pilot, 'comp.NO_OP_STRING, "hello, world"')
        # The form follows the command string
        assert app.query_one("#command-select", Select).value == "comp.NO_OP_STRING"
        assert app.query_one("#argument-0", Input).value == "hello, world"
        await pilot.press("enter")
        await settle(app, pilot)
        assert sender.sent == [("comp.NO_OP_STRING", ["hello, world"])]
        assert sender.thread_names[0] != threading.current_thread().name
        history = app.query_one("#history", OptionList)
        assert history.option_count == 1
        assert 'sent    comp.NO_OP_STRING, "hello, world"' in str(history.get_option_at_index(0).prompt)
        assert "sent: 1" in text_of(app, "#status")

    run(scenario)


def test_pasted_command_string_fills_form():
    async def scenario(app, pilot, model, sender):
        from textual import events

        app.query_one("#command-text", Input).post_message(events.Paste("other.MIXED, 7, 1.5, yes, SECOND"))
        await pilot.pause()
        await pilot.pause()
        assert app.query_one("#command-select", Select).value == "other.MIXED"
        assert app.query_one("#argument-0", Input).value == "7"
        assert app.query_one("#argument-1", Input).value == "1.5"
        assert app.query_one("#argument-2", Select).value == "True"
        assert app.query_one("#argument-3", Select).value == "SECOND"
        await pilot.press("enter")
        await settle(app, pilot)
        assert sender.sent == [("other.MIXED", ["7", "1.5", "yes", "SECOND"])]

    run(scenario)


def test_send_from_form():
    async def scenario(app, pilot, model, sender):
        select = app.query_one("#command-select", Select)
        select.focus()
        select.value = "other.MIXED"
        await pilot.pause()
        await pilot.pause()
        assert app.query_one("#command-text", Input).value == "other.MIXED, , , , "
        # Tab moves through the argument fields in order
        await pilot.press("tab")
        assert app.focused.id == "argument-0"
        await type_text(pilot, "12")
        await pilot.press("tab")
        assert app.focused.id == "argument-1"
        await type_text(pilot, "0.5")
        await pilot.press("tab")
        assert app.focused.id == "argument-2"
        app.focused.value = "False"
        await pilot.press("tab")
        assert app.focused.id == "argument-3"
        app.focused.value = "FIRST"
        await pilot.pause()
        assert app.query_one("#command-text", Input).value == "other.MIXED, 12, 0.5, False, FIRST"
        await pilot.click("#send")
        await settle(app, pilot)
        assert sender.sent == [("other.MIXED", ["12", "0.5", "False", "FIRST"])]

    run(scenario)


def test_enter_in_argument_field_sends():
    async def scenario(app, pilot, model, sender):
        select = app.query_one("#command-select", Select)
        select.focus()
        select.value = "comp.NO_OP_STRING"
        await pilot.pause()
        await pilot.pause()
        await pilot.press("tab")
        await type_text(pilot, "a, b")
        assert app.query_one("#command-text", Input).value == 'comp.NO_OP_STRING, "a, b"'
        await pilot.press("enter")
        await settle(app, pilot)
        assert sender.sent == [("comp.NO_OP_STRING", ["a, b"])]

    run(scenario)


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("", "empty command"),
        ("comp.MISSING", "unknown command"),
        ("NO_OP_STRING, x", "did you mean comp.NO_OP_STRING"),
        ("comp.NO_OP, 1", "takes 0 argument(s)"),
        ("other.MIXED, 1, 2", "takes 4 argument(s) (count, ratio, flag, choice), 2 given"),
        ("other.MIXED, x, 1.0, true, FIRST", "count[U32Type]"),
        ("other.MIXED, 1, 1.0, maybe, FIRST", "flag[BoolType]"),
        ("other.MIXED, 1, 1.0, true, THIRD", "choice["),
        ("other.MIXED, 99999999999, 1.0, true, FIRST", "count[U32Type]"),
        ('comp.NO_OP_STRING, "open', "unterminated quote"),
        ("comp.NO_OP_STRING, " + "x" * 41, "text[String_40]"),
    ],
)
def test_invalid_commands_are_not_sent(text, fragment):
    async def scenario(app, pilot, model, sender):
        app.query_one("#command-text", Input).value = text
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert sender.sent == []
        error = text_of(app, "#command-error")
        assert error.startswith("Not sent:") and fragment in error
        assert app.query_one("#history", OptionList).option_count == 0

    run(scenario)


def test_transport_failure_is_reported_not_raised():
    async def scenario(app, pilot, model, sender):
        sender.error = ConnectionError("link \x1b[31mdown")
        app.query_one("#command-text", Input).value = "comp.NO_OP"
        await pilot.press("enter")
        await settle(app, pilot)
        error = text_of(app, "#command-error")
        assert "Send failed: ConnectionError: link" in error and "\x1b" not in error
        history = app.query_one("#history", OptionList)
        assert "FAILED  comp.NO_OP" in str(history.get_option_at_index(0).prompt)
        assert "sent: 0" in text_of(app, "#status")

    run(scenario)


def test_history_reloads_command():
    async def scenario(app, pilot, model, sender):
        command_text = app.query_one("#command-text", Input)
        for text in ("comp.NO_OP", "other.MIXED, 1, 2.0, true, SECOND"):
            command_text.value = text
            await pilot.pause()
            await pilot.press("enter")
            await settle(app, pilot)
        command_text.value = ""
        await pilot.pause()
        assert app.query_one("#command-select", Select).is_blank()
        history = app.query_one("#history", OptionList)
        history.focus()
        history.highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        assert command_text.value == "other.MIXED, 1, 2.0, true, SECOND"
        assert app.focused.id == "command-text"
        assert app.query_one("#argument-3", Select).value == "SECOND"
        history.focus()
        history.highlighted = 1
        await pilot.press("enter")
        await pilot.pause()
        assert command_text.value == "comp.NO_OP"
        assert app.query("#arguments Input, #arguments Select").results() is not None
        assert len(app.argument_widgets) == 0

    run(scenario)


# ---- Keys and status ----


def test_panel_keys():
    async def scenario(app, pilot, model, sender):
        assert app.current_panel() == "commands"
        await pilot.press("f3")
        assert app.focused.id == "telemetry-table"
        await pilot.press("f4")
        assert app.focused.id == "events-table"
        await pilot.press("f2")
        assert app.focused.id == "command-text"
        # Ctrl+Tab cycles Commands -> Telemetry -> Events -> Commands
        visited = []
        for _ in range(3):
            await pilot.press("ctrl+tab")
            visited.append(app.current_panel())
        assert visited == ["telemetry", "events", "commands"]
        await pilot.press("ctrl+shift+tab")
        assert app.current_panel() == "events"
        # Function keys work from inside a text field; Esc leaves the field
        await pilot.press("slash")
        assert app.focused.id == "events-filter"
        await pilot.press("escape")
        assert app.focused.id == "events-table"
        await pilot.press("slash", "f3")
        assert app.focused.id == "telemetry-table"

    run(scenario)


def test_slash_types_in_text_fields():
    async def scenario(app, pilot, model, sender):
        await pilot.press("f3", "slash", "a", "slash", "b")
        assert app.query_one("#telemetry-filter", Input).value == "a/b"

    run(scenario)


def test_tab_moves_between_fields():
    async def scenario(app, pilot, model, sender):
        seen = []
        for _ in range(40):
            await pilot.press("tab")
            seen.append(app.focused.id)
            if seen.count(seen[0]) == 2:
                break
        for expected in ("telemetry-filter", "telemetry-table", "events-filter", "events-table",
                         "command-select", "command-text", "send", "severity-FATAL"):
            assert expected in seen

    run(scenario)


def test_help_screen():
    async def scenario(app, pilot, model, sender):
        await pilot.press("f1")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpScreen)

    run(scenario)


def test_status_line():
    async def scenario(app, pilot, model, sender):
        status = text_of(app, "#status")
        assert "transport: yamcs" in status and "no data yet" in status and "Dictionary.json" in status
        model.data_callback(make_channel(1, "A", 1))
        await refresh(app, pilot)
        assert "receiving" in text_of(app, "#status")
        app.last_data_time -= 60
        app.update_status()
        assert "NO DATA for 60s" in text_of(app, "#status")

    run(scenario)


@pytest.mark.parametrize("size", [(80, 24), (60, 20), (220, 60)])
def test_usable_at_terminal_sizes(size):
    async def scenario(app, pilot, model, sender):
        model.data_callback(make_channel(1, "A", 1))
        model.data_callback(make_event(1, "EV", "FATAL", "x" * 500))
        await refresh(app, pilot)
        for selector in ("#telemetry-table", "#events-table", "#command-text", "#status"):
            region = app.query_one(selector).region
            assert region.width > 0 and region.height > 0, selector
        await type_text(pilot, "comp.NO_OP")
        await pilot.press("enter")
        await settle(app, pilot)
        assert sender.sent == [("comp.NO_OP", [])]

    run(scenario, size=size)
