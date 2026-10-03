"""
The engineering seniority ladder, taken from a published industry reference.

Source: Eden Capital Careers, "Engineering Titles Explained"
        https://edencapitalcareers.com/guides/engineering-titles-explained

The guide maps an individual-contributor ladder (E1-E7) to the years of
experience and scope typical of each level:

    E1  Engineer I / Intern-adjacent      0-1 yrs   work is checked before it ships
    E2  Engineer II / Junior              1-2 yrs   assigned tasks, with review
    E3  Engineer III / Mid                2-4 yrs   owns well-scoped features
    E4  Senior Engineer                   4-7 yrs   owns a component or subsystem
    E5  Staff / Lead Engineer             7-11 yrs  technical lead for a team
    E6  Principal Engineer               11-15 yrs  cross-org technical authority
    E7  Senior Principal / Fellow         15+ yrs   sets direction for a unit

Why this module exists at all: every threshold in a trust signal has to be
answerable to "where does that number come from?". Taking the ladder from a
published guide makes each minimum citable, instead of a value chosen because
it happened to score well on our own dataset.

Two deliberate reading decisions, both conservative:

1. We take the LOWER bound of each band - the fewest years at which the guide
   describes anyone holding the title. A claim is only ever measured against
   the most generous reading of the ladder.

2. Manager and Director are NOT on the guide's IC ladder. They are mapped by
   matching scope: a Manager is a technical lead for a team (E5) and a Director
   carries cross-org authority (E6). This is our inference, not the source's,
   and is marked as such below.

The years are experience accumulated BEFORE the role began. Note the structural
limitation this creates, which the consuming signals have to allow for: a CV
lists only its most recent roles, so prior experience read off a CV
systematically undercounts a real career, and undercounts it most for the most
senior titles. See MIN_EXPERIENCE_MONTHS users for how that bias is absorbed.
"""

# Level name as standardized in silver -> (ladder level, minimum years, from source)
LADDER: dict[str, tuple[str, int, bool]] = {
    "Intern":     ("E1", 0, True),
    "Apprentice": ("E1", 0, True),
    "Graduate":   ("E1", 0, True),
    "Junior":     ("E2", 1, True),
    "Mid":        ("E3", 2, True),
    "Senior":     ("E4", 4, True),
    "Lead":       ("E5", 7, True),
    "Staff":      ("E5", 7, True),
    "Principal":  ("E6", 11, True),
    # Not on the guide's IC ladder; mapped by equivalent scope (see docstring).
    "Manager":    ("E5", 7, False),
    "Director":   ("E6", 11, False),
}

# Minimum months of prior experience the ladder associates with each level.
MIN_EXPERIENCE_MONTHS: dict[str, int] = {
    level: years * 12 for level, (_, years, _) in LADDER.items()
}

# E1-E2: "work is checked before it ships", "no independent design ownership".
# These are the levels at which the guide says the holder does not yet own
# design decisions - so a claim of leading a large team or owning a budget
# contradicts the title itself.
JUNIOR_LEVELS: frozenset[str] = frozenset(
    level for level, (ladder_level, _, _) in LADDER.items()
    if ladder_level in {"E1", "E2"}
)


def minimum_months(level: str | None) -> int | None:
    """Months of prior experience the ladder expects before `level`; None if unknown."""
    if level is None:
        return None
    return MIN_EXPERIENCE_MONTHS.get(level)


def is_junior_level(level: str | None) -> bool:
    """True for E1-E2 levels, which the ladder defines as not owning design."""
    return level in JUNIOR_LEVELS


def ladder_level(level: str | None) -> str | None:
    """The E-number for a level name, e.g. "Senior" -> "E4"; None if unknown."""
    if level is None:
        return None
    entry = LADDER.get(level)
    return entry[0] if entry else None
