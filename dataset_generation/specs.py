"""
The plan for the dataset: what CV to generate, before any of them exist.

Pure - no API, no files, no randomness beyond a fixed seed - so the shape of
the dataset can be asserted in a test without generating anything. A spec is a
plain dict describing one CV to produce.
"""

import random

from dataset_generation.inconsistencies import INCONSISTENCY_TYPES

ROLES = [
    "Data Engineer", "Data Scientist", "Machine Learning Engineer",
    "DevOps Engineer", "Software Engineer", "Backend Engineer",
    "Frontend Engineer", "Full Stack Engineer", "Data Analyst",
    "BI Analyst", "Staff Engineer", "Principal Engineer", "Research Engineer",
    "Forward Deployed Engineer",
]

# Titles nobody holds early in a career, so these never get a Junior or Mid.
SENIOR_ONLY_ROLES = ["Staff Engineer", "Principal Engineer"]

# Years of experience and how likely a GitHub link is, per level. More junior
# candidates publish more: a portfolio matters most when there is little
# employment history to show.
SENIORITY_CONFIG = {
    "Junior": {"years": ["1", "2"],         "github_prob": 0.7},
    "Mid":    {"years": ["3", "4", "5"],    "github_prob": 0.5},
    "Senior": {"years": ["6", "7", "8"],    "github_prob": 0.3},
    "Staff":  {"years": ["10", "12", "14"], "github_prob": 0.1},
}

# Half UK, half elsewhere in Europe. The phone prefix belongs to the city, so
# a mismatch between them is something an inconsistency must introduce.
LOCATIONS = [
    {"city": "London",      "country": "United Kingdom", "phone": "+44"},
    {"city": "Manchester",  "country": "United Kingdom", "phone": "+44"},
    {"city": "Edinburgh",   "country": "United Kingdom", "phone": "+44"},
    {"city": "Bristol",     "country": "United Kingdom", "phone": "+44"},
    {"city": "Birmingham",  "country": "United Kingdom", "phone": "+44"},
    {"city": "Leeds",       "country": "United Kingdom", "phone": "+44"},
    {"city": "Glasgow",     "country": "United Kingdom", "phone": "+44"},
    {"city": "Cambridge",   "country": "United Kingdom", "phone": "+44"},
    {"city": "Oxford",      "country": "United Kingdom", "phone": "+44"},
    {"city": "Liverpool",   "country": "United Kingdom", "phone": "+44"},
    {"city": "Berlin",      "country": "Germany",        "phone": "+49"},
    {"city": "Amsterdam",   "country": "Netherlands",    "phone": "+31"},
    {"city": "Paris",       "country": "France",         "phone": "+33"},
    {"city": "Barcelona",   "country": "Spain",          "phone": "+34"},
    {"city": "Madrid",      "country": "Spain",          "phone": "+34"},
    {"city": "Lisbon",      "country": "Portugal",       "phone": "+351"},
    {"city": "Dublin",      "country": "Ireland",        "phone": "+353"},
    {"city": "Stockholm",   "country": "Sweden",         "phone": "+46"},
    {"city": "Copenhagen",  "country": "Denmark",        "phone": "+45"},
    {"city": "Zurich",      "country": "Switzerland",    "phone": "+41"},
]

# Fixed so the dataset is reproducible: the same seed yields the same plan, and
# a rerun skips CVs whose file already exists rather than making new ones.
RANDOM_SEED = 42

MIN_INCONSISTENCIES_PER_CV = 1
MAX_INCONSISTENCIES_PER_CV = 3


def cv_filename(spec: dict) -> str:
    """
    The PDF name for a spec, e.g. "cv_001_data_engineer_senior.pdf".

    The role and seniority are part of the name, so adding an entry to ROLES
    changes the name every later CV gets from the same seed - which is how 14
    unplanned CVs once got generated over an existing set.
    """
    role_slug = spec["role"].lower().replace(" ", "_")
    return f"cv_{spec['id']}_{role_slug}_{spec['seniority'].lower()}.pdf"


def _draw_candidate(rng: random.Random) -> dict:
    """The attributes every CV has, whether or not it carries inconsistencies."""
    role = rng.choice(ROLES)
    seniority = (
        rng.choice(["Senior", "Staff"]) if role in SENIOR_ONLY_ROLES
        else rng.choice(list(SENIORITY_CONFIG))
    )
    config = SENIORITY_CONFIG[seniority]
    return {
        "role": role,
        "seniority": seniority,
        "years": rng.choice(config["years"]),
        "location": rng.choice(LOCATIONS),
        "github": rng.random() < config["github_prob"],
    }


def generate_specs(total: int = 300) -> list[dict]:
    """
    One spec per CV: half inconsistent, half legitimate, in that order.

    Each inconsistent CV gets 1-3 inconsistencies drawn at random, so one CV
    can carry several and no type gets a guaranteed share. `inconsistency_types`
    holds the keys, `inconsistencies` the prompt text for them.
    """
    rng = random.Random(RANDOM_SEED)
    inconsistency_keys = list(INCONSISTENCY_TYPES)
    half = total // 2
    specs = []

    for number in range(1, total + 1):
        is_inconsistent = number <= half
        # Draw order is load-bearing: candidate first, then how many
        # inconsistencies, then which ones. It fixes the sequence the seed
        # produces, so reordering silently plans a different dataset.
        candidate = _draw_candidate(rng)
        if is_inconsistent:
            count = rng.randint(MIN_INCONSISTENCIES_PER_CV, MAX_INCONSISTENCIES_PER_CV)
            chosen = rng.sample(inconsistency_keys, min(count, len(inconsistency_keys)))
        else:
            chosen = []
        specs.append({
            "id": str(number).zfill(3),
            "folder": "inconsistent" if is_inconsistent else "legitimate",
            **candidate,
            "inconsistency_types": chosen,
            "inconsistencies": [INCONSISTENCY_TYPES[key] for key in chosen],
        })
    return specs
