"""
fprime_gds.tui.command_text:

Parsing and formatting of the GDS command string: `component.MNEMONIC, arg1, "string, with comma", [1, 2]`. This is
the same form as the command string box of the GDS web interface, so strings may be pasted between the two.
"""
import json
import re
from typing import List, Sequence, Tuple

OPENERS = {"[": "]", "{": "}"}
# Characters that require a string argument to be quoted to survive a round trip through `parse_command_text`
NEEDS_QUOTING = set(',"[]{}\\')


class CommandTextError(ValueError):
    """The command string is malformed"""


def split_fields(text: str) -> List[Tuple[str, bool]]:
    """Split a command string into comma separated fields

    Commas inside double quotes, brackets, and braces do not split. A field that is exactly one double-quoted string is
    unquoted (with `\\"` and `\\\\` unescaped); every other field is returned stripped and otherwise verbatim so that
    JSON array/serializable arguments pass through unchanged.

    Args:
        text: command string
    Returns:
        list of (field, quoted) pairs; quoted is True when the field was written as a double-quoted string
    Raises:
        CommandTextError: unterminated quote, unbalanced bracket/brace, or text after a closing quote
    """
    fields: List[Tuple[str, bool]] = []
    raw: List[str] = []  # Characters of the current field verbatim
    unquoted: List[str] = []  # Characters of the current field with the outer quotes removed
    closers: List[str] = []
    in_quote = False
    was_quoted = False  # Current field started with a quote at depth zero
    quote_closed = False  # The field's leading quoted string has ended

    def finish():
        text_raw = "".join(raw).strip()
        if was_quoted:
            fields.append(("".join(unquoted), True))
        else:
            fields.append((text_raw, False))

    index = 0
    while index < len(text):
        char = text[index]
        if in_quote:
            if char == "\\" and index + 1 < len(text):
                raw.append(text[index : index + 2])
                if not closers:
                    unquoted.append(text[index + 1] if text[index + 1] in '"\\' else text[index : index + 2])
                index += 2
                continue
            raw.append(char)
            if char == '"':
                in_quote = False
                quote_closed = was_quoted and not closers
            elif not closers:
                unquoted.append(char)
        elif char == '"':
            if quote_closed:
                raise CommandTextError("unexpected text after closing quote")
            if not closers and not "".join(raw).strip():
                was_quoted = True
            raw.append(char)
            in_quote = True
        elif char in OPENERS:
            if quote_closed:
                raise CommandTextError("unexpected text after closing quote")
            closers.append(OPENERS[char])
            raw.append(char)
        elif closers and char == closers[-1]:
            closers.pop()
            raw.append(char)
        elif char in OPENERS.values():
            raise CommandTextError(f"unbalanced '{char}'")
        elif char == "," and not closers:
            finish()
            raw, unquoted, was_quoted, quote_closed = [], [], False, False
        else:
            if quote_closed and not char.isspace():
                raise CommandTextError("unexpected text after closing quote")
            raw.append(char)
        index += 1
    if in_quote:
        raise CommandTextError("unterminated quote")
    if closers:
        raise CommandTextError(f"missing '{closers[-1]}'")
    finish()
    return fields


def parse_command_text(text: str) -> Tuple[str, List[str]]:
    """Parse a command string into the command name and its argument strings

    Args:
        text: command string of the form `component.MNEMONIC, arg, ...`
    Returns:
        tuple of command name and list of argument strings
    Raises:
        CommandTextError: the string is empty or malformed
    """
    if not text.strip():
        raise CommandTextError("empty command")
    fields = split_fields(text)
    name, name_quoted = fields[0]
    if not name or name_quoted or any(char.isspace() for char in name):
        raise CommandTextError("expected: component.MNEMONIC, argument, ...")
    arguments = fields[1:]
    # A trailing comma (`CMD,`) is an empty tail, not an empty argument
    if arguments and arguments[-1] == ("", False):
        arguments = arguments[:-1]
    return name, [field for field, _ in arguments]


def format_argument(value: str, is_string: bool) -> str:
    """Format one argument for the command string

    Args:
        value: argument as text
        is_string: True for string-typed arguments, which are quoted when needed to survive parsing
    Returns:
        argument text for the command string
    """
    needs_quotes = is_string and (value == "" or any(char in NEEDS_QUOTING for char in value))
    if not needs_quotes and value != "":
        # Anything that would not come back from the parser as this one value is quoted, so that a comma typed into
        # a numeric field stays in that argument (and is then rejected) instead of shifting the arguments after it
        try:
            needs_quotes = split_fields(value) != [(value, False)]
        except CommandTextError:
            needs_quotes = True
    if needs_quotes:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def format_command_text(name: str, arguments: Sequence[str], string_flags: Sequence[bool]) -> str:
    """Format a command and its arguments as a command string

    Args:
        name: full command name
        arguments: argument values as text
        string_flags: per-argument flag, True for string-typed arguments
    Returns:
        command string accepted by `parse_command_text`
    """
    rendered = [format_argument(value, is_string) for value, is_string in zip(arguments, string_flags)]
    if rendered and rendered[-1] == "":
        rendered[-1] = '""'  # An empty tail would read as no argument at all
    return ", ".join([name] + rendered)


JSON_STRING = re.compile(r'("(?:\\.|[^"\\])*")')
BARE_WORD = re.compile(r"(?<![A-Za-z0-9_.])[A-Za-z_][A-Za-z0-9_.]*")  # Not the exponent of a number
JSON_WORDS = ("true", "false", "null")


def relax_json(value: str) -> str:
    """Make an array or serializable argument written the GDS way into JSON

    The GDS writes `[ONE, TWO]` and `{first: ONE}`; the argument types want `["ONE", "TWO"]` and `{"first": "ONE"}`.
    Bare words outside of strings are quoted. A value that already is JSON, or is not an array/serializable, is
    returned unchanged.

    Args:
        value: argument text
    Returns:
        argument text, as JSON when it could be made so
    """
    if not value.startswith(("[", "{")):
        return value
    try:
        json.loads(value)
        return value
    except ValueError:
        pass
    pieces = JSON_STRING.split(value)  # Odd indices are the string literals
    for index in range(0, len(pieces), 2):
        pieces[index] = BARE_WORD.sub(
            lambda match: match.group(0) if match.group(0) in JSON_WORDS else f'"{match.group(0)}"', pieces[index]
        )
    relaxed = "".join(pieces)
    try:
        json.loads(relaxed)
    except ValueError:
        return value
    return relaxed
