"""
Structured CV extraction via Claude.

This is I/O - a network call to an LLM - so it is deliberately outside
bronze/rules/. The response is validated against the ExtractedCV pydantic
model before anything downstream sees it, so a malformed or hallucinated
shape fails here rather than reaching the warehouse.
"""

import os
import re

import anthropic

from bronze.schemas import ExtractedCV

# ── Claude extraction ───────────────────────────────────────────────
def extract_cv_data_with_claude(raw_text):
    """
    LLM Extraction 2: CV Extractor.
    Sends the CV text to Claude Haiku.
    Claude extracts all structured data and returns clean JSON.
    Much more accurate than regex or SpaCy for CV parsing.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""Extract structured data from this CV text.
Return ONLY valid JSON, no explanation, no markdown, no code blocks.

{{
  "candidate_name": "full name from CV",
  "email": "email address or empty string",
  "phone": "phone number or empty string",
  "linkedin": "linkedin url or empty string",
  "github": "github url or empty string",
  "work_experience": [
    {{
      "job_title": "exact job title as written in CV",
      "company_name": "exact company name as written in CV",
      "company_website": "company website url or empty string",
      "location": "city and country or empty string",
      "start_date": "Month Year format or empty string",
      "end_date": "Month Year format or Present",
      "is_current": true or false,
      "description": "all bullet points joined with | separator"
    }}
  ],
  "skills": ["skill1", "skill2", "skill3"]
}}

Rules:
- work_experience must contain ONLY actual jobs
- A job entry must have a clear job title AND company name
- Do not include companies mentioned inside bullet points
- skills must be technical skills only
- Return exactly the number of jobs present in the CV
- Do not invent data, only extract what is written

CV TEXT:
{raw_text}"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()

    # remove markdown code blocks if Claude added them
    if response_text.startswith("```"):
        response_text = re.sub(r"```json\n?|```\n?", "", response_text).strip()

    cv_data = ExtractedCV.model_validate_json(response_text)
    return cv_data

