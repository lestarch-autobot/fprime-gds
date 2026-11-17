"""
fprime_gds.tui.app:

Textual application of the F Prime terminal UI: latest telemetry on the left, colourized events as the primary area,
and commanding (command drop-down with argument form, paste-able command string, and history) across the bottom.
"""
import difflib
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from fprime_gds.common.data_types.cmd_data import CmdData, CommandArgumentsException
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.tui.command_text import CommandTextError, format_command_text, parse_command_text
from fprime_gds.tui.filtering import matches, parse_filter
from fprime_gds.tui.model import SEVERITY_ORDER, ChannelRow, EventRow, TuiModel, sanitize

# Event colours follow the severity classes of the GDS web interface (fp-color-*)
SEVERITY_STYLES = {
    "FATAL": "bold white on red",
    "WARNING_HI": "bold red",
    "WARNING_LO": "yellow",
    "ACTIVITY_HI": "bright_blue",
    "ACTIVITY_LO": "green",
    "COMMAND": "cyan",
    "DIAGNOSTIC": "dim",
}
SEVERITY_LABELS = {
    "FATAL": "FATAL",
    "WARNING_HI": "WARN_HI",
    "WARNING_LO": "WARN_LO",
    "ACTIVITY_HI": "ACT_HI",
    "ACTIVITY_LO": "ACT_LO",
    "COMMAND": "CMD",
    "DIAGNOSTIC": "DIAG",
}
LIMIT_STYLES = {"red": "bold white on red", "orange": "black on dark_orange", "yellow": "black on yellow"}
REFRESH_SECONDS = 0.2
# Above this many new events in one refresh the event table is rebuilt instead of appended to
EVENT_REBUILD_THRESHOLD = 500
MAX_HISTORY = 100
# Seconds without data after which the link indicator turns stale
STALE_SECONDS = 10.0
FILTER_HELP = "filter: words AND, -or- for OR"

HELP_TEXT = """\
F Prime terminal UI

Panels
  F2 / F3 / F4      focus Commands / Telemetry / Events
  Ctrl+Tab          next panel (when the terminal passes it through)
  Tab / Shift+Tab   next / previous field
  /                 focus the filter of the current panel
  Esc               leave a field (focus the panel's table)
  Ctrl+L            clear the event list
  Ctrl+Q            quit

Filters (same as the GDS tables)
  Case-insensitive substrings of the row as displayed.
  Space separated words must all match; "-or-" between two words matches either.
    cmdDisp warning            rows with both words
    FATAL -or- WARNING_HI      rows with either word

Commanding
  Pick a command in the drop-down and fill in the argument fields, or type/paste
  a command string:   component.MNEMONIC, arg1, "string, with comma", [1, 2]
  The form and the command string stay in step. Enter or Send sends.
  Select a history entry to load it again.
"""


def short_time(readable: str) -> str:
    """Time of day (millisecond precision) of an ISO timestamp; other time formats are returned whole"""
    if "T" in readable:
        return readable.split("T", 1)[1][:12]
    return readable


def plain(value: str, style: str = "") -> Text:
    """Text cell that is never interpreted as console markup"""
    return Text(value, style=style, no_wrap=True)


class HelpScreen(ModalScreen):
    """Key and filter help"""

    BINDINGS = [Binding("escape,f1,q,enter", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(HELP_TEXT, markup=False)

    def on_click(self) -> None:
        self.dismiss()


class FprimeTui(App):
    """Terminal UI for F Prime telemetry, events, and commanding"""

    TITLE = "F Prime"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #top { height: 1fr; }
    #telemetry { width: 3fr; min-width: 30; }
    #events { width: 5fr; }
    #commands { height: 13; }
    .panel { border: round $primary-darken-1; border-title-color: $text; padding: 0 1; }
    .panel:focus-within { border: round $accent; }
    .bar { height: 1; }
    Input { height: 1; border: none; padding: 0 1; background: $surface-lighten-1; }
    Input:focus { background: $surface-lighten-2; }
    Input.-invalid { color: $error; }
    #severity-bar { height: 1; }
    #severity-bar Checkbox { margin-right: 1; }
    DataTable { height: 1fr; }
    #command-select { width: 48; }
    #send { min-width: 10; height: 1; border: none; margin-left: 1; }
    #command-row { height: 3; }
    #arguments { height: 4; }
    .argument { width: auto; min-width: 20; max-width: 44; height: 4; margin-right: 1; }
    .argument Label { height: 1; color: $text-muted; }
    .argument Input { width: 26; }
    .argument Select { width: 30; }
    #no-arguments { color: $text-muted; }
    #command-text-row { height: 1; }
    #command-text-label { width: 9; }
    #command-text { width: 1fr; }
    #command-error { height: 1; color: $error; }
    #history { height: 1fr; min-height: 1; border: none; background: $surface; }
    #status { height: 1; background: $panel; color: $text; padding: 0 1; }
    HelpScreen { align: center middle; }
    #help-box { width: 84; max-width: 100%; height: auto; max-height: 100%; border: round $accent;
                background: $surface; padding: 1 2; }
    """
    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("f2", "focus_panel('commands')", "Commands", priority=True),
        Binding("f3", "focus_panel('telemetry')", "Telemetry", priority=True),
        Binding("f4", "focus_panel('events')", "Events", priority=True),
        Binding("ctrl+tab", "next_panel", "Next panel", show=False, priority=True),
        Binding("ctrl+shift+tab", "previous_panel", "Previous panel", show=False, priority=True),
        Binding("slash", "focus_filter", "Filter"),
        Binding("escape", "leave_field", "Leave field", show=False),
        Binding("ctrl+l", "clear_events", "Clear events"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]
    PANELS = ("commands", "telemetry", "events")
    PANEL_FOCUS = {"commands": "#command-text", "telemetry": "#telemetry-table", "events": "#events-table"}
    PANEL_FILTER = {"telemetry": "#telemetry-filter", "events": "#events-filter"}

    def __init__(
        self,
        model: TuiModel,
        command_templates: Dict[str, object],
        send_command: Callable[[str, Sequence[str]], None],
        transport_name: str = "",
        dictionary_name: str = "",
        max_events: int = 5000,
    ):
        """Create the application

        Args:
            model: store fed by the GDS pipeline
            command_templates: command templates by full command name (the pipeline's command dictionary)
            send_command: function sending a command by name with string arguments; raises on failure
            transport_name: name of the data transport plugin in use, for the status line
            dictionary_name: name of the loaded dictionary, for the status line
            max_events: number of events displayed at most
        """
        super().__init__()
        self.model = model
        self.command_templates = command_templates
        self.send_command = send_command
        self.transport_name = sanitize(transport_name)
        self.dictionary_name = sanitize(dictionary_name)
        self.max_events = max_events
        self.channel_filter: List[List[str]] = []
        self.event_filter: List[List[str]] = []
        self.severities = set(SEVERITY_ORDER)
        self.shown_channels: Dict[int, ChannelRow] = {}
        self.shown_events: Deque[int] = deque()
        self.last_event_sequence = 0
        self.current_command: Optional[str] = None
        self.argument_widgets: List[object] = []
        self.history: Deque[Tuple[str, Text]] = deque(maxlen=MAX_HISTORY)  # Newest first
        self.last_data_time: Optional[float] = None
        self.sent_count = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            with Vertical(id="telemetry", classes="panel"):
                yield Input(placeholder=FILTER_HELP, id="telemetry-filter", select_on_focus=False)
                yield DataTable(id="telemetry-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="events", classes="panel"):
                yield Input(placeholder=FILTER_HELP, id="events-filter", select_on_focus=False)
                with Horizontal(id="severity-bar"):
                    for severity in SEVERITY_ORDER:
                        yield Checkbox(
                            SEVERITY_LABELS[severity], value=True, compact=True, id=f"severity-{severity}"
                        )
                yield DataTable(id="events-table", cursor_type="row")
        with Vertical(id="commands", classes="panel"):
            with Horizontal(id="command-row"):
                yield Select(
                    [(name, name) for name in sorted(self.command_templates)],
                    prompt="Select command",
                    id="command-select",
                    compact=True,
                )
                arguments = HorizontalScroll(id="arguments")
                arguments.can_focus = False  # Not a tab stop: the fields scroll into view when focused
                yield arguments
            with Horizontal(id="command-text-row"):
                yield Label("command>", id="command-text-label")
                yield Input(
                    placeholder='component.MNEMONIC, arg1, "arg 2"   (Enter sends)',
                    id="command-text",
                    suggester=SuggestFromList(sorted(self.command_templates), case_sensitive=False),
                    select_on_focus=False,
                )
                yield Button("Send", id="send", variant="primary", compact=True)
            yield Static("", id="command-error", markup=False)
            yield OptionList(id="history", markup=False, compact=True)
        yield Static("", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#telemetry").border_title = "Telemetry (F3)"
        self.query_one("#events").border_title = "Events (F4)"
        self.query_one("#commands").border_title = "Commanding (F2)"
        telemetry = self.query_one("#telemetry-table", DataTable)
        telemetry.add_column("Channel", key="name")
        telemetry.add_column("Value", key="value")
        telemetry.add_column("Time", key="time")
        events = self.query_one("#events-table", DataTable)
        events.add_column("Time", key="time")
        events.add_column("Severity", key="severity")
        events.add_column("Event", key="name")
        events.add_column("Message", key="message")
        self.query_one("#command-text", Input).focus()
        self.set_interval(REFRESH_SECONDS, self.refresh_data)
        self.update_status()

    # ---- Data refresh ----

    def refresh_data(self) -> None:
        """Move data received since the last refresh from the model into the tables"""
        channels, events = self.model.drain()
        if channels or events:
            self.last_data_time = time.monotonic()
        if channels:
            self.update_channels(channels)
        if len(events) > EVENT_REBUILD_THRESHOLD:
            self.rebuild_events()
        elif events:
            self.append_events(events)
        self.update_status()

    def channel_cells(self, row: ChannelRow):
        """Table cells of a channel row"""
        return (
            plain(row.name),
            plain(row.value, LIMIT_STYLES.get(row.limit, "")),
            plain(short_time(row.time)),
        )

    def update_channels(self, rows: List[ChannelRow]) -> None:
        """Update displayed channels in place; a channel seen for the first time re-sorts the table"""
        table = self.query_one("#telemetry-table", DataTable)
        matching = [row for row in rows if matches(self.channel_filter, row.text)]
        if any(row.channel_id not in self.shown_channels for row in matching):
            self.rebuild_channels()
            return
        for row in rows:
            if row.channel_id not in self.shown_channels:
                continue
            key = str(row.channel_id)
            if not matches(self.channel_filter, row.text):
                # The new reading no longer passes the filter (e.g. a filter on the value)
                table.remove_row(key)
                del self.shown_channels[row.channel_id]
                continue
            _, value_cell, time_cell = self.channel_cells(row)
            table.update_cell(key, "time", time_cell)
            table.update_cell(key, "value", value_cell, update_width=True)
            self.shown_channels[row.channel_id] = row

    def rebuild_channels(self) -> None:
        """Redraw the telemetry table from the model with the current filter, keeping the cursor on its channel"""
        table = self.query_one("#telemetry-table", DataTable)
        selected = None
        if table.row_count and table.is_valid_row_index(table.cursor_row):
            selected = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        table.clear()
        self.shown_channels = {}
        for row in self.model.channels():
            if matches(self.channel_filter, row.text):
                table.add_row(*self.channel_cells(row), key=str(row.channel_id))
                self.shown_channels[row.channel_id] = row
        if selected is not None and int(selected) in self.shown_channels:
            table.move_cursor(row=table.get_row_index(selected), animate=False)

    def event_visible(self, row: EventRow) -> bool:
        """Whether an event passes the severity toggles and the text filter"""
        return row.severity in self.severities and matches(self.event_filter, row.text)

    def add_event_row(self, table: DataTable, row: EventRow) -> None:
        """Append one event to the event table"""
        style = SEVERITY_STYLES.get(row.severity, "")
        table.add_row(
            plain(short_time(row.time), style),
            plain(row.severity, style),
            plain(row.name, style),
            plain(row.message, style),
            key=str(row.sequence),
        )
        self.shown_events.append(row.sequence)

    def following(self, table: DataTable) -> bool:
        """Whether the event table shows its newest rows, so new events should keep scrolling into view"""
        return table.row_count == 0 or table.cursor_row >= table.row_count - 1

    def append_events(self, rows: List[EventRow]) -> None:
        """Append new events, drop events beyond the retention limit, and follow the tail when already there"""
        table = self.query_one("#events-table", DataTable)
        follow = self.following(table)
        for row in rows:
            self.last_event_sequence = row.sequence
            if self.event_visible(row):
                self.add_event_row(table, row)
        oldest_retained = self.last_event_sequence - self.max_events
        while self.shown_events and (
            self.shown_events[0] <= oldest_retained or len(self.shown_events) > self.max_events
        ):
            table.remove_row(str(self.shown_events.popleft()))
        if follow and table.row_count:
            table.move_cursor(row=table.row_count - 1, animate=False)

    def rebuild_events(self) -> None:
        """Redraw the event table from the model with the current filters"""
        table = self.query_one("#events-table", DataTable)
        follow = self.following(table)
        selected = None
        if not follow and table.is_valid_row_index(table.cursor_row):
            selected = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        table.clear()
        self.shown_events.clear()
        for row in self.model.events()[-self.max_events :]:
            self.last_event_sequence = row.sequence
            if self.event_visible(row):
                self.add_event_row(table, row)
        if not table.row_count:
            return
        if selected is not None and int(selected) in self.shown_events:
            table.move_cursor(row=table.get_row_index(selected), animate=False)
        else:
            table.move_cursor(row=table.row_count - 1, animate=False)

    def update_status(self) -> None:
        """Refresh the status line and panel titles"""
        if self.last_data_time is None:
            link = "no data yet"
        else:
            age = time.monotonic() - self.last_data_time
            link = "receiving" if age < STALE_SECONDS else f"NO DATA for {int(age)}s"
        parts = [f"transport: {self.transport_name or '?'}", link]
        if self.dictionary_name:
            parts.append(f"dictionary: {self.dictionary_name}")
        parts.append(f"sent: {self.sent_count}")
        dropped = self.model.dropped
        if dropped:
            parts.append(f"undisplayable: {dropped}")
        self.query_one("#status", Static).update(" | ".join(parts))
        total_channels = len(self.model.channels()) if self.channel_filter else len(self.shown_channels)
        self.query_one("#telemetry").border_subtitle = (
            f"{len(self.shown_channels)}/{total_channels} channels"
            if self.channel_filter
            else f"{len(self.shown_channels)} channels"
        )
        filtered = bool(self.event_filter) or len(self.severities) != len(SEVERITY_ORDER)
        self.query_one("#events").border_subtitle = (
            f"{len(self.shown_events)} shown (filtered)" if filtered else f"{len(self.shown_events)} events"
        )

    # ---- Filters ----

    @on(Input.Changed, "#telemetry-filter")
    def telemetry_filter_changed(self, event: Input.Changed) -> None:
        self.channel_filter = parse_filter(event.value)
        self.rebuild_channels()
        self.update_status()

    @on(Input.Changed, "#events-filter")
    def events_filter_changed(self, event: Input.Changed) -> None:
        self.event_filter = parse_filter(event.value)
        self.rebuild_events()
        self.update_status()

    @on(Checkbox.Changed, "#severity-bar Checkbox")
    def severity_changed(self, event: Checkbox.Changed) -> None:
        severity = event.checkbox.id.split("-", 1)[1]
        if event.value:
            self.severities.add(severity)
        else:
            self.severities.discard(severity)
        self.rebuild_events()
        self.update_status()

    # ---- Commanding ----

    def argument_values(self) -> List[str]:
        """Current values of the argument form as strings"""
        values = []
        for widget in self.argument_widgets:
            if isinstance(widget, Select):
                values.append("" if widget.is_blank() else str(widget.value))
            else:
                values.append(widget.value)
        return values

    def string_flags(self, name: str) -> List[bool]:
        """Per-argument flags of a command: True for string-typed arguments"""
        return [issubclass(arg_type, StringType) for _, _, arg_type in self.command_templates[name].get_args()]

    async def show_command(self, name: Optional[str], values: Sequence[str] = ()) -> None:
        """Show the argument form of a command, optionally filled in

        Args:
            name: full command name, None to clear the form
            values: argument values as strings; missing arguments are left empty
        """
        container = self.query_one("#arguments", HorizontalScroll)
        if name != self.current_command:
            await container.remove_children()
            self.argument_widgets = []
            self.current_command = name
            if name is not None:
                arguments = self.command_templates[name].get_args()
                boxes = []
                for index, (arg_name, _, arg_type) in enumerate(arguments):
                    label = Label(sanitize(f"{arg_name}: {arg_type.__name__}"), markup=False)
                    if issubclass(arg_type, EnumType):
                        widget = Select(
                            [(sanitize(key), key) for key in arg_type.keys()],
                            prompt="Select",
                            id=f"argument-{index}",
                            compact=True,
                        )
                    elif issubclass(arg_type, BoolType):
                        widget = Select(
                            [("True", "True"), ("False", "False")], prompt="Select", id=f"argument-{index}", compact=True
                        )
                    else:
                        widget = Input(id=f"argument-{index}", select_on_focus=False)
                    self.argument_widgets.append(widget)
                    boxes.append(Vertical(label, widget, classes="argument"))
                if not boxes:
                    boxes.append(Static("(no arguments)", id="no-arguments"))
                await container.mount_all(boxes)
        for widget, value in zip(self.argument_widgets, list(values) + [""] * len(self.argument_widgets)):
            if isinstance(widget, Select):
                options = {str(option_value): option_value for _, option_value in widget._options if option_value is not Select.NULL}
                normalized = value.strip()
                if normalized.lower() in ("true", "yes", "false", "no") and "True" in options:
                    normalized = "True" if normalized.lower() in ("true", "yes") else "False"
                if normalized in options:
                    widget.value = options[normalized]
                else:
                    widget.clear()
            elif widget.value != value:
                widget.value = value
        select = self.query_one("#command-select", Select)
        if name is None:
            if not select.is_blank():
                select.clear()
        elif select.value != name:
            select.value = name

    def form_focused(self) -> bool:
        """Whether the focused widget belongs to the command form (drop-down or an argument)"""
        focused = self.focused
        if focused is None:
            return False
        return focused.id == "command-select" or any(
            ancestor.id in ("arguments", "command-select") for ancestor in focused.ancestors
        )

    def set_command_error(self, message: str) -> None:
        """Show (or with an empty message clear) the command error line"""
        self.query_one("#command-error", Static).update(sanitize(message))

    def form_to_text(self) -> None:
        """Write the command string for the current state of the form"""
        if self.current_command is None:
            return
        text = format_command_text(
            self.current_command, self.argument_values(), self.string_flags(self.current_command)
        )
        command_text = self.query_one("#command-text", Input)
        if command_text.value != text:
            command_text.value = text
            command_text.cursor_position = len(text)
        self.set_command_error("")

    @on(Select.Changed, "#command-select")
    async def command_selected(self, event: Select.Changed) -> None:
        if not self.form_focused():
            return  # Set from the command string or history, which already updated the form
        name = None if event.select.is_blank() else str(event.value)
        if name == self.current_command:
            return
        await self.show_command(name)
        if name is None:
            self.query_one("#command-text", Input).value = ""
        self.form_to_text()

    @on(Select.Changed, "#arguments Select")
    def argument_selected(self, event: Select.Changed) -> None:
        if self.form_focused():
            self.form_to_text()

    @on(Input.Changed, "#arguments Input")
    def argument_changed(self, event: Input.Changed) -> None:
        if self.form_focused():
            self.form_to_text()

    @on(Input.Changed, "#command-text")
    async def command_text_changed(self, event: Input.Changed) -> None:
        if self.form_focused():
            return  # Written by the form
        await self.text_to_form(event.value)

    async def text_to_form(self, text: str) -> None:
        """Bring the form in step with the command string, as far as the string is understood"""
        self.set_command_error("")
        if not text.strip():
            await self.show_command(None)
            return
        try:
            name, values = parse_command_text(text)
        except CommandTextError:
            return  # Incomplete while typing; reported on send
        if name in self.command_templates:
            await self.show_command(name, values)

    @on(Input.Submitted, "#command-text")
    @on(Input.Submitted, "#arguments Input")
    @on(Button.Pressed, "#send")
    def send_requested(self, event) -> None:
        event.stop()
        self.send_text(self.query_one("#command-text", Input).value)

    def send_text(self, text: str) -> None:
        """Validate the command string and send it"""
        try:
            name, values = parse_command_text(text)
        except CommandTextError as error:
            self.set_command_error(f"Not sent: {error}")
            return
        template = self.command_templates.get(name)
        if template is None:
            close = [known for known in sorted(self.command_templates) if name.lower() in known.lower()]
            close = close or difflib.get_close_matches(name, list(self.command_templates), n=3)
            hint = f" (did you mean {', '.join(close[:3])}?)" if close else ""
            self.set_command_error(f"Not sent: unknown command '{name}'{hint}")
            return
        arguments = template.get_args()
        if len(values) != len(arguments):
            expected = ", ".join(arg_name for arg_name, _, _ in arguments) or "none"
            self.set_command_error(
                f"Not sent: {name} takes {len(arguments)} argument(s) ({expected}), {len(values)} given"
            )
            return
        try:
            CmdData(tuple(values), template)
        except CommandArgumentsException as error:
            problems = "; ".join(message for message in error.errors if message)
            self.set_command_error(f"Not sent: {problems}")
            return
        self.set_command_error("")
        canonical = format_command_text(name, values, self.string_flags(name))
        self.dispatch_command(name, values, canonical)

    @work(thread=True, group="send")
    def dispatch_command(self, name: str, values: List[str], canonical: str) -> None:
        """Send on a worker thread: a transport may block on the network"""
        try:
            self.send_command(name, values)
        except Exception as error:  # Any transport failure is reported, never raised into the UI
            self.call_from_thread(self.command_finished, canonical, f"{type(error).__name__}: {error}")
        else:
            self.call_from_thread(self.command_finished, canonical, None)

    def command_finished(self, canonical: str, error: Optional[str]) -> None:
        """Record the outcome of a send in the history"""
        stamp = time.strftime("%H:%M:%S")
        history = self.query_one("#history", OptionList)
        if error is None:
            self.sent_count += 1
            prompt = Text(f"{stamp} sent    {canonical}", no_wrap=True)
        else:
            prompt = Text(f"{stamp} FAILED  {canonical}  ({sanitize(error)})", style="bold red", no_wrap=True)
            self.set_command_error(f"Send failed: {error}")
        self.history.appendleft((canonical, prompt))
        history.clear_options()
        history.add_options([Option(item) for _, item in self.history])
        self.update_status()

    @on(OptionList.OptionSelected, "#history")
    async def history_selected(self, event: OptionList.OptionSelected) -> None:
        text = self.history[event.option_index][0]
        command_text = self.query_one("#command-text", Input)
        command_text.focus()
        command_text.value = text
        command_text.cursor_position = len(text)
        await self.text_to_form(text)

    # ---- Keys ----

    def current_panel(self) -> str:
        """Name of the panel holding the focus (commands when nothing is focused)"""
        focused = self.focused
        if focused is not None:
            for node in (focused, *focused.ancestors):
                if node.id in self.PANELS:
                    return node.id
        return "commands"

    def action_focus_panel(self, panel: str) -> None:
        self.query_one(self.PANEL_FOCUS[panel]).focus()

    def action_next_panel(self) -> None:
        index = self.PANELS.index(self.current_panel())
        self.action_focus_panel(self.PANELS[(index + 1) % len(self.PANELS)])

    def action_previous_panel(self) -> None:
        index = self.PANELS.index(self.current_panel())
        self.action_focus_panel(self.PANELS[(index - 1) % len(self.PANELS)])

    def action_focus_filter(self) -> None:
        panel = self.current_panel()
        if panel in self.PANEL_FILTER:
            self.query_one(self.PANEL_FILTER[panel]).focus()

    def action_leave_field(self) -> None:
        self.action_focus_panel(self.current_panel())

    def action_clear_events(self) -> None:
        self.model.clear_events()
        self.rebuild_events()
        self.update_status()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
