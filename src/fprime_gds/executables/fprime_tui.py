"""
fprime_gds.executables.fprime_tui:

Entry point of `fprime-tui`, the terminal UI for F Prime telemetry, events, and commanding. It connects through the
standard GDS pipeline and a data transport plugin (default: yamcs), exactly as `fprime-cli` and the integration test
API do. Requires the optional `tui` extra: `pip install "fprime-gds[tui]"`.
"""
import os
import sys
from typing import Any, Dict, Tuple

from fprime_gds.executables.cli import MiddleWareParser, ParserBase, StandardPipelineParser
from fprime_gds.tui.model import DEFAULT_MAX_EVENTS, TuiModel


class TuiMiddleWareParser(MiddleWareParser):
    """Data transport selection defaulting to the yamcs transport"""

    DEFAULT_TRANSPORT = "yamcs"


class TuiPipelineParser(StandardPipelineParser):
    """Standard pipeline parser with the terminal UI's default transport"""

    CONSTITUENTS = [
        TuiMiddleWareParser if constituent is MiddleWareParser else constituent
        for constituent in StandardPipelineParser.CONSTITUENTS
    ]


class TuiParser(ParserBase):
    """Arguments of the terminal UI itself"""

    DESCRIPTION = "Terminal UI options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments of the terminal UI"""
        return {
            ("--max-events",): {
                "dest": "max_events",
                "type": int,
                "default": DEFAULT_MAX_EVENTS,
                "help": "Number of most recent events kept for display [default: %(default)s]",
            }
        }

    def handle_arguments(self, args, **kwargs):
        """Check the terminal UI arguments"""
        if args.max_events < 1:
            raise ValueError("--max-events must be at least 1")
        return args


def main(arguments=None) -> int:
    """Run the terminal UI

    Args:
        arguments: command line arguments, None to use the process arguments
    Returns:
        process exit code
    """
    try:
        from fprime_gds.tui.app import FprimeTui
    except ImportError as error:
        print(
            f'[ERROR] fprime-tui needs the "tui" extra: pip install "fprime-gds[tui]" ({error})',
            file=sys.stderr,
        )
        return 1
    try:
        args, _ = ParserBase.parse_args(
            [TuiPipelineParser, TuiParser],
            description="Terminal UI for F Prime telemetry, events, and commanding",
            arguments=arguments,
            client=True,
        )
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    model = TuiModel(max_events=args.max_events)
    pipeline = None
    try:
        pipeline = TuiPipelineParser.pipeline_factory(args)
        pipeline.coders.register_channel_consumer(model)
        pipeline.coders.register_event_consumer(model)
    except Exception as error:
        print(
            f"[ERROR] Could not connect using the '{args.data_transport_selection}' data transport: {error}",
            file=sys.stderr,
        )
        if pipeline is not None:
            pipeline.disconnect()
        return 1
    try:
        app = FprimeTui(
            model=model,
            command_templates=pipeline.dictionaries.command_name,
            send_command=pipeline.send_command,
            transport_name=args.data_transport_selection,
            dictionary_name=os.path.basename(str(pipeline.dictionaries.dictionary_path or "")),
            max_events=args.max_events,
        )
        app.run()
    finally:
        pipeline.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
