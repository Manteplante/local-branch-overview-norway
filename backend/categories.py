"""Group free-text activity names into a fixed set of categories for filtering.

Branches name the same activity in many ways ("BARK (Barnas Røde Kors)", "Barnas Røde Kors
Arna og Åsane", "Besøksvenn med hund: – Spre glede…"). Rules are checked in order and the
first match wins, so put the more specific ones first.
"""

from __future__ import annotations

import re

OTHER = "Annet"

RULES: list[tuple[str, str]] = [
    ("RØFF", r"\brøff\b|friluftsliv og førstehjelp"),
    ("Barnas Røde Kors", r"\bbark\b|barnas røde kors"),
    ("Leksehjelp", r"leksehjelp"),
    ("Norsktrening", r"norsk|språkkaf|språkkafe"),
    (
        "Flyktning og migrasjon",
        r"flyktning|flerkultur|migrasjon|internasjonal|kvinnegruppe",
    ),
    ("Våketjeneste", r"våketjeneste"),
    ("Vitnestøtte", r"vitnestøtte"),
    ("Sykehusvert/-guide", r"sykehus"),
    (
        "Besøkstjeneste",
        r"besøk|visitor|kulturvenn|tirsdagstreff|eldretreff|seniorgutta",
    ),
    ("Ferie for alle", r"ferie|julegave"),
    (
        "Beredskap og hjelpekorps",
        r"hjelpekorps|beredskap|sanitet|redning|førstehjelp|psykososial",
    ),
    ("Møteplasser og ungdom", r"treffpunkt|møteplass|ungdom|fellesverket|gatemegling"),
]

_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in RULES]

CATEGORIES = [name for name, _ in RULES] + [OTHER]


def categorize(activity: str) -> str:
    """The category for one activity name; "Annet" when no rule matches, "" for no name."""
    if not activity:
        return ""
    for name, pattern in _COMPILED:
        if pattern.search(activity):
            return name
    return OTHER
