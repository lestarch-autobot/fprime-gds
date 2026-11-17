"""
fprime_gds.tui.filtering:

Text filter used by the telemetry and event panels. Implements the filter grammar of the GDS web tables
(`flask/static/js/vue-support/utils.js`): whitespace separated tokens must all match (AND), a token preceded by `-or-`
is an alternative of the token before it (OR), and matching is a case-insensitive substring search.
"""
from typing import List

OR_TOKEN = "-or-"


def parse_filter(text: str) -> List[List[str]]:
    """Parse filter text into an ANDed list of ORed token sets

    Args:
        text: filter text as typed by the user
    Returns:
        list of token groups; an item matches when every group has at least one token contained in the item
    """
    groups: List[List[str]] = []
    oring = False
    for token in text.lower().split():
        if token == OR_TOKEN:
            oring = True
        elif oring and groups:
            groups[-1].append(token)
            oring = False
        else:
            groups.append([token])
            oring = False
    return groups


def matches(groups: List[List[str]], item_text: str) -> bool:
    """Check an item's displayed text against a parsed filter

    Args:
        groups: output of `parse_filter`; an empty list matches everything
        item_text: text of the item as displayed
    Returns:
        True when the item passes the filter
    """
    lowered = item_text.lower()
    return all(any(token in lowered for token in group) for group in groups)
