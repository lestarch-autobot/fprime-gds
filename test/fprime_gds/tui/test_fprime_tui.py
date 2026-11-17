"""Tests of the fprime-tui entry point's arguments and failure handling"""
import pytest

from fprime_gds.executables import fprime_tui
from fprime_gds.executables.cli import MiddleWareParser, StandardPipelineParser


def test_default_transport_is_yamcs_for_the_tui_only():
    assert fprime_tui.TuiMiddleWareParser.DEFAULT_TRANSPORT == "yamcs"
    assert MiddleWareParser.DEFAULT_TRANSPORT != "yamcs"
    assert fprime_tui.TuiMiddleWareParser in fprime_tui.TuiPipelineParser.CONSTITUENTS
    assert MiddleWareParser not in fprime_tui.TuiPipelineParser.CONSTITUENTS
    assert len(fprime_tui.TuiPipelineParser.CONSTITUENTS) == len(StandardPipelineParser.CONSTITUENTS)
    assert MiddleWareParser in StandardPipelineParser.CONSTITUENTS


def test_selection_help_names_the_tui_default():
    arguments = fprime_tui.TuiMiddleWareParser().get_arguments()
    assert "default: yamcs" in arguments[("--data-transport-selection",)]["help"]


def run_main(arguments):
    """Exit code of main, whether returned or raised by the argument parser"""
    try:
        return fprime_tui.main(arguments)
    except SystemExit as exit_request:
        return exit_request.code


@pytest.mark.parametrize("value", ["0", "-5", "many"])
def test_max_events_must_be_positive(value, capsys, tmp_path):
    assert run_main(["--max-events", value, "--dictionary", str(tmp_path / "missing.json")]) not in (0, None)
    assert "Traceback" not in capsys.readouterr().err


def test_bad_dictionary_is_reported_without_traceback(capsys, tmp_path):
    assert run_main(["--dictionary", str(tmp_path / "missing.json")]) not in (0, None)
    error = capsys.readouterr().err
    assert "[ERROR]" in error and "does not exist" in error and "Traceback" not in error
