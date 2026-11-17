"""Tests of command string parsing and formatting"""
import pytest

from fprime_gds.tui.command_text import (
    CommandTextError,
    format_argument,
    format_command_text,
    parse_command_text,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("a.B", ("a.B", [])),
        ("  a.B  ", ("a.B", [])),
        ("a.B,", ("a.B", [])),
        ("a.b.C, 1, 2.5, -3", ("a.b.C", ["1", "2.5", "-3"])),
        ('a.B, "x, y"', ("a.B", ["x, y"])),
        ('a.B, "say \\"hi\\" \\\\"', ("a.B", ['say "hi" \\'])),
        ('a.B, ""', ("a.B", [""])),
        ("a.B, ,2", ("a.B", ["", "2"])),
        ("a.B, hello world", ("a.B", ["hello world"])),
        ('a.B, [1, "a,b"], {"k": [1, 2]}', ("a.B", ['[1, "a,b"]', '{"k": [1, 2]}'])),
        ("a.B, 0x10, ENUM_A", ("a.B", ["0x10", "ENUM_A"])),
    ],
)
def test_parse(text, expected):
    assert parse_command_text(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "   ", ", 1", '"a.B", 1', "a b, 1", 'a.B, "x', 'a.B, "x" y', "a.B, [1", "a.B, 1]", 'a.B, {"k": 1'],
)
def test_parse_errors(text):
    with pytest.raises(CommandTextError):
        parse_command_text(text)


@pytest.mark.parametrize(
    "value, is_string, expected",
    [
        ("hello", True, "hello"),
        ("hello world", True, "hello world"),
        ("a, b", True, '"a, b"'),
        ("", True, '""'),
        (" pad ", True, '" pad "'),
        ('q"q', True, '"q\\"q"'),
        ("[1]", True, '"[1]"'),
        ("[1, 2]", False, "[1, 2]"),
        ("12", False, "12"),
    ],
)
def test_format_argument(value, is_string, expected):
    assert format_argument(value, is_string) == expected


@pytest.mark.parametrize(
    "values",
    [
        [],
        ["1", "2"],
        ["a, b", 'q"q', "back\\slash", "", " pad ", "[x]", "{y}"],
        ["tab\there", "ünïcödé"],
    ],
)
def test_round_trip_strings(values):
    """Any string argument survives format -> parse"""
    text = format_command_text("comp.CMD", values, [True] * len(values))
    assert parse_command_text(text) == ("comp.CMD", values)


def test_trailing_empty_string_round_trip():
    """A final empty string argument is quoted, so it is not taken for a trailing comma"""
    text = format_command_text("comp.CMD", ["1", ""], [False, True])
    assert text == 'comp.CMD, 1, ""'
    assert parse_command_text(text) == ("comp.CMD", ["1", ""])
