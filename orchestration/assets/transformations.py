"""
Pure standardization and validation logic for bronze -> silver transforms.

No I/O here — everything is a plain function over in-memory data, so it can
be unit tested without mocking BigQuery. Covers raw_candidates ->
silver_candidates, raw_skills -> silver_skills and raw_work_experience ->
silver_work_experience.

Anything that depends on a controlled vocabulary (skills, job-title seniority,
country aliases) is a lookup against a `dim_*` reference table loaded from a
reviewed CSV, never a vocabulary hardcoded here: callers fetch the rows, build
the lookup object, and inject it into the functions below. That keeps this
module I/O-free while letting the vocabularies evolve as reviewed data.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

import phonenumbers

_EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)

# Default region used to interpret numbers with no country code (e.g. "20
# 7183 8750"). Most CVs in this dataset are UK-based; a number that already
# carries its own country code ("+1 415...") is parsed using that instead.
_DEFAULT_REGION = "GB"


def standardize_name(name: str) -> str:
    """Uppercases and collapses whitespace. Empty/missing names become ''."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip()).upper()


def standardize_phone(phone: str) -> str | None:
    """
    Normalizes a phone number to E.164 format (e.g. `+34612458907`,
    `+14155552671`), for any country.

    Numbers that already carry a country code ("+1 415 555 2671", "0034 612
    458 907") are parsed using that code. Numbers with no country code
    ("020 7183 8750") are assumed to be in `_DEFAULT_REGION`. Returns None
    when the input can't be parsed into a valid, assignable number for its
    country (wrong length, bad prefix, etc).
    """
    if not phone:
        return None

    try:
        parsed = phonenumbers.parse(phone, _DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_valid_number(parsed):
        return None

    return phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.E164
    )


def is_valid_email(email: str) -> bool:
    """
    True when `email` contains "@", a domain, no spaces, and matches a
    standard email pattern.
    """
    if not email:
        return False
    if " " in email:
        return False
    if "@" not in email:
        return False

    local, _, domain = email.partition("@")
    if not domain or "." not in domain:
        return False

    return bool(_EMAIL_PATTERN.match(email))


def transform_candidate_row(row: dict) -> dict:
    """Applies standardization/validation to one raw_candidates row."""
    email = (row.get("email") or "").strip()
    phone = standardize_phone(row.get("phone") or "")

    return {
        "submission_id": row["submission_id"],
        "candidate_name": standardize_name(row.get("candidate_name") or ""),
        "email": email,
        "is_email_valid": is_valid_email(email),
        "phone": phone,
        "is_phone_valid": phone is not None,
        "linkedin": (row.get("linkedin") or "").strip(),
        "github": (row.get("github") or "").strip(),
    }


# ── Skills: clean -> standardize -> normalize -> validate ────────────────
def clean_skill(raw_skill: str) -> str:
    """
    CLEANING. Removes noise without changing meaning: normalizes Unicode
    (full-width and lookalike characters) to canonical form, strips
    leading/trailing whitespace, and collapses internal whitespace.

    "  Power   BI " -> "Power BI"
    """
    if not raw_skill:
        return ""
    normalized = unicodedata.normalize("NFKC", raw_skill)
    return re.sub(r"\s+", " ", normalized.strip())


def skill_lookup_key(raw_skill: str) -> str:
    """
    STANDARDIZATION. Puts a skill into the one consistent format used for
    taxonomy lookups: cleaned, then lowercased.

    "  Power   BI " and "POWERBI" -> "power bi" and "powerbi"

    This is the single definition of the lookup key. Both the taxonomy
    (alias side) and the bronze data (raw_skill side) are keyed through this
    function, so the two sides can never drift apart.
    """
    return clean_skill(raw_skill).lower()


@dataclass(frozen=True)
class SkillsTaxonomy:
    """
    Immutable in-memory lookup of skill alias -> canonical skill, built from
    the `dim_skills` reference table. Injected into the functions below so
    they stay pure and testable without BigQuery.
    """

    canonical_by_key: dict[str, str]

    def canonical_for(self, lookup_key: str) -> str | None:
        return self.canonical_by_key.get(lookup_key)

    @property
    def alias_count(self) -> int:
        return len(self.canonical_by_key)

    @property
    def canonical_skills(self) -> set[str]:
        return set(self.canonical_by_key.values())


def build_skills_taxonomy(dim_skills_rows: list[dict]) -> SkillsTaxonomy:
    """
    Builds the lookup from `dim_skills` rows (`{alias, canonical_skill}`).

    Raises ValueError if two aliases collapse to the same lookup key but
    disagree on the canonical skill — that is a broken taxonomy, and failing
    loudly here beats silently resolving a skill to whichever row happened to
    be read last.
    """
    canonical_by_key: dict[str, str] = {}

    for row in dim_skills_rows:
        key = skill_lookup_key(row["alias"])
        if not key:
            continue

        canonical = row["canonical_skill"]
        existing = canonical_by_key.get(key)
        if existing is not None and existing != canonical:
            raise ValueError(
                f"Conflicting taxonomy: lookup key '{key}' maps to both "
                f"'{existing}' and '{canonical}'"
            )
        canonical_by_key[key] = canonical

    return SkillsTaxonomy(canonical_by_key=canonical_by_key)


def normalize_skill(raw_skill: str, taxonomy: SkillsTaxonomy) -> str | None:
    """
    NORMALIZATION. Maps a skill to its canonical name, merging synonyms
    ("Google Data Studio" and "Looker Studio" both -> "Looker Studio").
    Returns None when the skill is not in the taxonomy.
    """
    return taxonomy.canonical_for(skill_lookup_key(raw_skill))


def transform_skill_row(row: dict, taxonomy: SkillsTaxonomy) -> dict:
    """
    Applies all four steps to one `raw_skills` row.

    Cleaning and standardization happen inside this function; only their end
    result is kept. `raw_skill` is preserved for traceability, and the
    intermediate values can always be re-derived from it with clean_skill()
    and skill_lookup_key().

    VALIDATION is expressed as `normalized_skill` being None: a skill that is
    not in the taxonomy is kept rather than dropped, so it can be reviewed and
    added, but it carries no canonical value.
    """
    raw_skill = row.get("skill_name") or ""

    return {
        "skill_id": row["skill_id"],
        "submission_id": row["submission_id"],
        "raw_skill": raw_skill,
        "normalized_skill": taxonomy.canonical_for(skill_lookup_key(raw_skill)),
    }


# ── Work experience: job title, dates, location ───────────────────────────
_NON_WORD_PATTERN = re.compile(r"[^\w\s]|_")

# CVs state a month and a year, never a day.
_MONTH_FORMATS = ("%B %Y", "%b %Y")  # "August 2017" / "Aug 2017"

# Values that mean "still working here" rather than a date. Only "Present"
# appears in the data today; the others are the obvious variants a future
# extraction could produce, and treating them as dates would be worse than
# recognising them.
_CURRENT_MARKERS = frozenset({"present", "current", "now", "ongoing", "to date"})

_REMOTE_PATTERN = re.compile(r"\bremote\b", re.IGNORECASE)
# "Remote / Edinburgh" and "Remote - Edinburgh": the marker plus its separator.
_REMOTE_PREFIX_PATTERN = re.compile(r"^\s*remote\s*[/\-–|]?\s*", re.IGNORECASE)
# "Stockholm Office" is the same city as "Stockholm".
_CITY_NOISE_PATTERN = re.compile(r"\s+(office|hq|headquarters)$", re.IGNORECASE)

EARLIEST_PLAUSIBLE_YEAR = 1950


def standardize_job_title(job_title: str) -> str:
    """
    STANDARDIZATION. Reduces a title to words and single spaces: every
    character that is not a letter, digit or space becomes a space.

    "Staff Engineer - Cloud Infrastructure" -> "Staff Engineer Cloud Infrastructure"
    "Software Engineer (Junior)"            -> "Software Engineer Junior"
    "Mid-Level Data Analyst"                -> "Mid Level Data Analyst"

    Written as "keep word characters" rather than as a list of punctuation to
    strip, so a separator that has not appeared yet is handled too.
    """
    if not job_title:
        return ""
    return re.sub(r"\s+", " ", _NON_WORD_PATTERN.sub(" ", job_title)).strip()


def parse_cv_month(value: str | None) -> tuple[date | None, bool]:
    """
    Parses a CV date into (first of that month, is_a_current_marker).

    "August 2017" -> (2017-08-01, False)
    "Jul 2021"    -> (2021-07-01, False)
    "Present"     -> (None, True)
    unparseable   -> (None, False)

    The day is always the 1st because a CV only states month precision —
    choosing any other day would invent information the source does not have.
    """
    text = (value or "").strip()
    if not text:
        return None, False

    if text.lower() in _CURRENT_MARKERS:
        return None, True

    for date_format in _MONTH_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format)
        except ValueError:
            continue
        return date(parsed.year, parsed.month, 1), False

    return None, False


@dataclass(frozen=True)
class WorkExperienceReference:
    """
    Immutable lookups built from the `dim_job_titles` and
    `dim_location_aliases` reference tables, injected into the functions below
    so they stay pure and testable without BigQuery.
    """

    seniority_by_title: dict[str, str]
    country_by_location_token: dict[str, str]

    def seniority_for(self, job_title: str) -> str | None:
        return self.seniority_by_title.get((job_title or "").strip().casefold())

    def country_for(self, location_token: str) -> str | None:
        return self.country_by_location_token.get((location_token or "").strip().casefold())


def build_work_experience_reference(
    job_title_rows: list[dict],
    location_alias_rows: list[dict],
) -> WorkExperienceReference:
    """
    Builds the lookups from `dim_job_titles` rows (`{job_title,
    seniority_level}`) and `dim_location_aliases` rows (`{location_token,
    country}`).

    Raises ValueError when two rows claim the same key with different values —
    a broken reference table should fail loudly rather than resolve to
    whichever row was read last.
    """
    seniority_by_title: dict[str, str] = {}
    for row in job_title_rows:
        key = (row["job_title"] or "").strip().casefold()
        if not key:
            continue
        level = row.get("seniority_level")
        if not level:
            continue  # the title states no level; absence is the answer
        existing = seniority_by_title.get(key)
        if existing is not None and existing != level:
            raise ValueError(
                f"Conflicting job title reference: {key!r} maps to both "
                f"{existing!r} and {level!r}"
            )
        seniority_by_title[key] = level

    country_by_token: dict[str, str] = {}
    for row in location_alias_rows:
        key = (row["location_token"] or "").strip().casefold()
        if not key:
            continue
        country = row["country"]
        existing = country_by_token.get(key)
        if existing is not None and existing != country:
            raise ValueError(
                f"Conflicting location reference: {key!r} maps to both "
                f"{existing!r} and {country!r}"
            )
        country_by_token[key] = country

    return WorkExperienceReference(
        seniority_by_title=seniority_by_title,
        country_by_location_token=country_by_token,
    )


def split_location(
    location: str,
    reference: WorkExperienceReference,
) -> tuple[str | None, str | None, bool]:
    """
    Splits a CV location into (city, country, is_remote).

    "Dublin, Ireland"                      -> ("Dublin", "Ireland", False)
    "Edinburgh, Scotland"                  -> ("Edinburgh", "United Kingdom", False)
    "Canary Wharf, London, United Kingdom" -> ("London", "United Kingdom", False)
    "Remote / Edinburgh, United Kingdom"   -> ("Edinburgh", "United Kingdom", True)
    "Stockholm Office, Sweden"             -> ("Stockholm", "Sweden", False)
    "Stockholm"                            -> ("Stockholm", "Sweden", False)
    ""                                     -> (None, None, False)

    With three or more parts the city is the second-to-last one, so a district
    ("Canary Wharf") gives way to the city it belongs to. The country always
    comes from the reference table; an unknown token yields None rather than a
    guess.
    """
    text = re.sub(r"\s+", " ", (location or "").strip())
    if not text:
        return None, None, False

    is_remote = bool(_REMOTE_PATTERN.search(text))
    text = _REMOTE_PREFIX_PATTERN.sub("", text).strip(" ,")
    if not text:
        return None, None, is_remote

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return None, None, is_remote

    country_token = parts[-1]
    country = reference.country_for(country_token)

    if len(parts) == 1:
        # Either a bare city ("Stockholm") or a bare country ("Sweden").
        city_token = "" if country and country_token.casefold() == country.casefold() else parts[0]
    else:
        city_token = parts[-2]

    city = _CITY_NOISE_PATTERN.sub("", city_token).strip() or None
    return city, country, is_remote


def transform_work_experience_row(
    row: dict,
    reference: WorkExperienceReference,
) -> dict:
    """
    Applies cleaning, standardization and normalization to one
    `raw_work_experience` row.

    `company_name`, `job_title`, `location` and `description` are preserved as
    written; the standardized and split values go alongside them. Unknown
    titles, countries and unparseable dates become None — the row is kept and
    the gap is visible, never dropped or guessed.
    """
    job_title = (row.get("job_title") or "").strip()
    location = (row.get("location") or "").strip()

    start_date, _ = parse_cv_month(row.get("start_date_raw"))
    end_date, end_is_current_marker = parse_cv_month(row.get("end_date_raw"))
    city, country, is_remote = split_location(location, reference)

    return {
        "experience_id": row["experience_id"],
        "submission_id": row["submission_id"],
        "company_name": re.sub(r"\s+", " ", (row.get("company_name") or "").strip()),
        "job_title": job_title,
        "job_title_standardized": standardize_job_title(job_title),
        "seniority_level": reference.seniority_for(job_title),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "is_current": bool(row.get("is_current")) or end_is_current_marker,
        "location": location,
        "location_city": city,
        "location_country": country,
        "is_remote": is_remote,
        "description": row.get("description"),
        "company_website": row.get("company_website"),
    }


def work_experience_date_problems(silver_row: dict) -> list[str]:
    """
    Date validity problems in a transformed row, as a list of short labels.

    Checks validity, not plausibility: that the dates parsed, that they run
    forwards, and that they fall in a sane range. Whether the described
    responsibilities fit the dates is a gold-layer question.
    """
    problems = []
    start, end = silver_row["start_date"], silver_row["end_date"]

    if start is None:
        problems.append("unparsed_start_date")
    if end is None and not silver_row["is_current"]:
        problems.append("unparsed_end_date")
    if start and end and start > end:
        problems.append("start_after_end")

    today = date.today().isoformat()
    for value in (start, end):
        if value and value > today:
            problems.append("date_in_future")
        if value and int(value[:4]) < EARLIEST_PLAUSIBLE_YEAR:
            problems.append("implausible_year")

    return problems
