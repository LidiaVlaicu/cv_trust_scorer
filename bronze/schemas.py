"""
Pydantic schemas for CV extraction.

These models validate the JSON response from Claude when extracting structured
information from CV text. They define a contract: if validation passes, the
data has exactly this shape and downstream code can trust it.

Used by:
    - dagster/assets/extraction.py (validates Claude responses)
    - tests/test_schemas.py (verifies schema behavior)
"""
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional


class WorkExperienceItem(BaseModel):
    """
    A single work experience entry from a CV.

    Dates are kept as strings here (not date objects) because CVs use varied
    formats ("January 2020", "Jan 2020", "01/2020", "Present"). Parsing into
    structured dates happens in the silver layer transformations, where we
    can apply consistent normalization rules.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    job_title: str = Field(..., min_length=1, max_length=200)
    company_name: str = Field(..., min_length=1, max_length=200)
    company_website: str = Field(default="", max_length=500)
    location: str = Field(default="", max_length=200)
    start_date: str = Field(default="", max_length=50)
    end_date: str = Field(default="Present", max_length=50)
    is_current: bool = False
    description: str = Field(default="", max_length=10000)

    @field_validator("job_title", "company_name")
    @classmethod
    def must_not_be_placeholder(cls, value: str) -> str:
        """Reject obvious LLM hallucinations or placeholder values."""
        placeholders = {"n/a", "none", "unknown", "tbd", "xxx", "placeholder"}
        if value.lower().strip() in placeholders:
            raise ValueError(f"Field appears to be a placeholder: '{value}'")
        return value


class ExtractedCV(BaseModel):
    """
    Complete structured CV data extracted by Claude.

    This is the contract between the LLM extraction step and everything
    downstream. If a CV's Claude response validates against this schema, all
    bronze and silver tables can trust the structure.

    Empty strings are allowed for optional contact fields because CVs don't
    always include LinkedIn, GitHub, or phone numbers. Required fields
    (candidate_name, work_experience) cause validation to fail if missing.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    candidate_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=50)
    linkedin: str = Field(default="", max_length=500)
    github: str = Field(default="", max_length=500)
    work_experience: list[WorkExperienceItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("candidate_name")
    @classmethod
    def must_not_be_placeholder(cls, value: str) -> str:
        placeholders = {"n/a", "none", "unknown", "candidate", "name"}
        if value.lower().strip() in placeholders:
            raise ValueError(f"candidate_name appears to be a placeholder: '{value}'")
        return value

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, skills: list[str]) -> list[str]:
        """Remove empty strings and deduplicate skills (case-insensitive)."""
        seen = set()
        cleaned = []
        for skill in skills:
            skill_stripped = skill.strip()
            if not skill_stripped:
                continue
            if skill_stripped.lower() in seen:
                continue
            seen.add(skill_stripped.lower())
            cleaned.append(skill_stripped)
        return cleaned
