"""Tests of the telemetry/event filter grammar (the grammar of the GDS web tables)"""
import pytest

from fprime_gds.tui.filtering import matches, parse_filter


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", []),
        ("   ", []),
        ("abc", [["abc"]]),
        ("ABC Def", [["abc"], ["def"]]),
        ("a -or- b", [["a", "b"]]),
        ("a -OR- b c", [["a", "b"], ["c"]]),
        ("a -or- b -or- c", [["a", "b", "c"]]),
        ("a -or-", [["a"]]),
        ("-or- a", [["a"]]),
        ("a -or- -or- b", [["a", "b"]]),
    ],
)
def test_parse_filter(text, expected):
    assert parse_filter(text) == expected


@pytest.mark.parametrize(
    "filter_text, item, expected",
    [
        ("", "anything", True),
        ("cmd", "CdhCore.cmdDisp.OpCodeCompleted", True),
        ("CMDDISP", "CdhCore.cmdDisp.OpCodeCompleted", True),
        ("cmdDisp completed", "CdhCore.cmdDisp.OpCodeCompleted", True),
        ("cmdDisp dispatched", "CdhCore.cmdDisp.OpCodeCompleted", False),
        ("fatal -or- warning_hi", "x WARNING_HI y", True),
        ("fatal -or- warning_hi", "x WARNING_LO y", False),
        ("fatal -or- warning cmdDisp", "WARNING_LO CdhCore.cmdDisp.X", True),
        ("fatal -or- warning cmdDisp", "WARNING_LO Ref.health.X", False),
        ("[bold]", "plain", False),
    ],
)
def test_matches(filter_text, item, expected):
    assert matches(parse_filter(filter_text), item) is expected
