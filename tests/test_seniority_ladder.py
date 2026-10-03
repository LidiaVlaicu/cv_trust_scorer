"""
The published ladder is reference data, so these tests pin it to its source.

Source: Eden Capital Careers, "Engineering Titles Explained".
If a value here changes, the guide it came from must have changed too.
"""

from orchestration.assets import seniority_ladder as ladder


def test_the_minimums_are_the_published_lower_bounds():
    """The lower bound of each E-band, in months, exactly as the guide states."""
    assert ladder.MIN_EXPERIENCE_MONTHS == {
        "Intern": 0,        # E1, 0-1 yrs
        "Apprentice": 0,    # E1
        "Graduate": 0,      # E1
        "Junior": 12,       # E2, 1-2 yrs
        "Mid": 24,          # E3 Engineer III, 2-4 yrs
        "Senior": 48,       # E4, 4-7 yrs
        "Lead": 84,         # E5, 7-11 yrs
        "Staff": 84,        # E5
        "Principal": 132,   # E6, 11-15 yrs
        "Manager": 84,      # mapped to E5 by scope, not stated in the source
        "Director": 132,    # mapped to E6 by scope, not stated in the source
    }


def test_every_level_maps_to_an_e_band():
    assert ladder.ladder_level("Mid") == "E3"
    assert ladder.ladder_level("Senior") == "E4"
    assert ladder.ladder_level("Staff") == "E5"
    assert ladder.ladder_level("Principal") == "E6"
    assert ladder.ladder_level(None) is None
    assert ladder.ladder_level("Chief Wizard") is None


def test_minimums_rise_monotonically_with_the_e_band():
    """A higher band can never ask for less experience than a lower one."""
    by_band = {}
    for level, (band, years, _) in ladder.LADDER.items():
        by_band.setdefault(band, set()).add(years)
    # every level sharing a band agrees on its minimum
    for band, years in by_band.items():
        assert len(years) == 1, f"{band} has conflicting minimums: {years}"
    ordered = [next(iter(by_band[band])) for band in sorted(by_band)]
    assert ordered == sorted(ordered)


def test_junior_levels_are_exactly_the_e1_and_e2_bands():
    """
    The guide defines E1-E2 as not owning design decisions. That is what makes
    a large-team or budget claim at these levels a contradiction, so the set
    must follow the bands rather than be listed by hand.
    """
    assert ladder.JUNIOR_LEVELS == frozenset(
        {"Intern", "Apprentice", "Graduate", "Junior"}
    )
    assert ladder.is_junior_level("Junior") is True
    assert ladder.is_junior_level("Mid") is False      # E3 ships alone
    assert ladder.is_junior_level("Senior") is False
    assert ladder.is_junior_level(None) is False


def test_levels_not_on_the_ladder_have_no_minimum():
    assert ladder.minimum_months("Senior") == 48
    assert ladder.minimum_months(None) is None
    assert ladder.minimum_months("Ninja") is None


def test_the_inferred_mappings_are_marked_as_inferred():
    """
    Manager and Director are our scope-match, not the guide's words. The flag
    keeps that visible so the thesis can cite the ladder without overclaiming.
    """
    from_source = {
        level for level, (_, _, stated) in ladder.LADDER.items() if stated
    }
    inferred = {
        level for level, (_, _, stated) in ladder.LADDER.items() if not stated
    }
    assert inferred == {"Manager", "Director"}
    assert "Senior" in from_source and "Principal" in from_source
