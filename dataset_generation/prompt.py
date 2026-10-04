"""
Builds the prompt for one CV from its spec.

Pure string assembly, deliberately separate from the API call, so the prompt
can be asserted in a test without spending a Claude call - which is how you
catch an instruction that silently contradicts itself or does nothing.
"""

MODEL_INSTRUCTIONS = """
IMPORTANT:
- Output ONLY the CV text, nothing else
- No markdown, no asterisks, no bold markers, no symbols
- Plain text only
- Fictional company websites must end in .io, .co, or .net
- Real companies must have their real website"""

# Asked for when the summary should read as a person wrote it. Omitted when
# `ai_text` is planted, since that asks for the opposite.
HUMAN_SUMMARY = (
    "Write the professional summary in a natural human voice "
    "with specific personal details. Avoid all corporate buzzwords."
)


def build_cv_prompt(spec: dict) -> str:
    """
    The full prompt for one spec.

    Takes the whole spec rather than loose arguments so the inconsistency KEYS
    are available, not just their prompt text. That matters: the `ai_text`
    check has to compare keys. An earlier version searched for the string
    "ai_text" inside the inconsistency prose, where it never appears, so the
    model was told both to write buzzword-heavy AI prose and to write in a
    natural human voice - two contradictory instructions in one prompt.
    """
    location = spec["location"]
    inconsistency_keys = spec.get("inconsistency_types", [])
    inconsistency_prompts = spec.get("inconsistencies", [])

    inconsistencies_section = ""
    if inconsistency_prompts:
        numbered = "".join(
            f"{number}. {text}\n"
            for number, text in enumerate(inconsistency_prompts, 1)
        )
        inconsistencies_section = (
            "\n\nINCONSISTENCIES TO INCLUDE (follow exactly):\n" + numbered
        )

    summary_instruction = "" if "ai_text" in inconsistency_keys else HUMAN_SUMMARY
    github_line = (
        "GitHub URL with 3-4 relevant public repositories" if spec["github"]
        else "No GitHub URL"
    )

    return f"""Generate a realistic IT technical CV in plain text for:
- Role: {spec["role"]}
- Seniority: {spec["seniority"]}
- Years of experience: {spec["years"]}
- City: {location["city"]}, {location["country"]}

Requirements:
- Fictional but realistic full name
- Fictional email (firstname.lastname@gmail.com)
- Fictional phone number starting with {location["phone"]}
- LinkedIn URL
- {github_line}
- Exactly 3 jobs in work experience
- Each job must include: job title, company name, company website if available,
  location, dates in format Month Year - Month Year, exactly 4 bullet points
- Education from a real university in {location["country"]}
- Skills section with relevant technical skills
- Professional summary of 3-4 lines
{inconsistencies_section}
{summary_instruction}
{MODEL_INSTRUCTIONS}"""
