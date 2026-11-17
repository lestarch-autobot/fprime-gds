"""Tests of command string parsing and formatting"""
import pytest

from fprime_gds.tui.command_text import (
    relax_json,
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


@pytest.mark.parametrize("value", ["1,2", "1, 2", "[1, 2", "1]", '5"', " 5", "a}b", '"', "\\"])
def test_values_that_would_not_parse_back_as_one_argument_are_quoted(value):
    for is_string in (True, False):
        text = format_command_text("comp.CMD", [value, "7"], [is_string, False])
        assert parse_command_text(text) == ("comp.CMD", [value, "7"])


@pytest.mark.parametrize("value", ["5", "-1.5e3", "[1, 2, 3]", '{"a": [1, "x,y"]}', "ENUM_VALUE", ""])
def test_plain_values_are_not_quoted(value):
    assert format_command_text("comp.CMD", [value], [False]) == f"comp.CMD, {value}"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("[ONE, TWO]", '["ONE", "TWO"]'),
        ("{firstChoice: ONE, secondChoice: TWO}", '{"firstChoice": "ONE", "secondChoice": "TWO"}'),
        ('{a: "x, y: z", b: [true, null, 1.5e3, Ref.Choice.ONE]}', '{"a": "x, y: z", "b": [true, null, 1.5e3, "Ref.Choice.ONE"]}'),
        ('["ONE", "TWO"]', '["ONE", "TWO"]'),
        ("[1, 2, 3]", "[1, 2, 3]"),
        ("ONE", "ONE"),
        ("5", "5"),
        ("[ONE, TWO", "[ONE, TWO"),
        ("{a b}", "{a b}"),
    ],
)
def test_relax_json_quotes_bare_words_as_the_gds_writes_them(value, expected):
    assert relax_json(value) == expected
