"""Builders of GDS templates and data objects for the terminal UI tests"""
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.models.serialize.numerical_types import F32Type, U32Type
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.templates.event_template import EventTemplate
from fprime_gds.common.utils.event_severity import EventSeverity

CHOICE = EnumType.construct_type("Choice", {"FIRST": 0, "SECOND": 1})
STRING = StringType.construct_type("String_40", 40)
TRIPLE = ArrayType.construct_type("Triple", F32Type, 3, "{}")
EVENT_STRING = StringType.construct_type("String_2048", 2048)


def make_time(seconds=1000, useconds=0):
    """A workstation time"""
    return TimeType(2, 0, seconds, useconds)


def make_channel(channel_id, name, value, component="comp", seconds=1000, type_class=U32Type, **limits):
    """A channel reading"""
    template = ChTemplate(channel_id, name, component, type_class, **limits)
    return ChData(type_class(value), make_time(seconds), template)


def make_event(event_id, name, severity, message, component="comp", seconds=1000):
    """An event whose message is the given text"""
    template = EventTemplate(
        event_id, name, component, [("text", None, EVENT_STRING)], EventSeverity[severity], "{}"
    )
    return EventData((EVENT_STRING(message),), make_time(seconds), template)


def make_commands():
    """A small command dictionary by full name"""
    templates = [
        CmdTemplate(1, "NO_OP", "comp", []),
        CmdTemplate(2, "NO_OP_STRING", "comp", [("text", None, STRING)]),
        CmdTemplate(
            3,
            "MIXED",
            "other",
            [("count", None, U32Type), ("ratio", None, F32Type), ("flag", None, BoolType), ("choice", None, CHOICE)],
        ),
        CmdTemplate(4, "ARRAY", "other", [("values", None, TRIPLE), ("label", None, STRING)]),
    ]
    return {template.get_full_name(): template for template in templates}
