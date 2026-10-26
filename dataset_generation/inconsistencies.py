"""
The inconsistencies planted in the synthetic CVs, one instruction each.

This file defines what "inconsistent" means for the whole dataset, kept apart
from the generation machinery so that editing one does not mean scrolling past
PDF styling code.

Each value is prose handed to the model. Nothing here is verified afterwards:
the model is asked to plant the inconsistency and may not comply. So a CV in
data/inconsistent/ was *asked* to contain these, which is not the same as
containing them.

The release years quoted in `tech_anachronism` are first-release dates. A
candidate with one or two years of experience has no role old enough to carry
this one.
"""

INCONSISTENCY_TYPES: dict[str, str] = {
    "fictional_company": "Include exactly one completely fictional company that does not exist in any public "
    "business registry. Use a convincing but fake name like 'NovaTech Solutions Ltd', "
    "'DataStream Analytics Inc', 'CloudPeak Technologies Ltd', 'Nexus Digital Co', "
    "'Synapse Data Ltd', or similar. The other companies must be real.",
    "fictional_company_2": "Include exactly TWO completely fictional companies that do not exist in any public "
    "business registry. Use convincing but fake names. The third company must be real.",
    "date_overlap": "Create an impossible date overlap between two full-time jobs. The overlap must be "
    "at least 3 months. Make it subtle: for example job 1 ends March 2021 and job 2 "
    "starts January 2021, creating a 2-month overlap. Both jobs should appear full-time.",
    "ai_text": "Write the professional summary using clearly AI-generated language. Overuse corporate "
    "buzzwords: results-driven, highly motivated, cutting-edge, actionable insights, "
    "cross-functional collaboration, mission-critical, leverage, spearhead, champion, "
    "synergistically, proven track record, dynamic, innovative, passionate about delivering "
    "value, data-driven decision making, organisational objectives. Make it generic and "
    "impersonal with no specific personal details.",
    "career_incoherent": "Make the career progression completely incoherent and impossible. Examples: "
    "jumped from Junior Engineer to Staff Engineer in only 18 months, "
    "claims to have managed a team of 20+ engineers as a Junior, "
    "went from Graduate to Principal Engineer in 2 years, "
    "or a Mid-level analyst claims to have directed a department of 50 people. "
    "The progression must be clearly impossible for the declared seniority level.",
    "company_substitution": "Simulate a company substitution between CV versions: include one fictional company "
    "(that does not exist in public registries) for an early role, and make it clear "
    "the candidate recently updated their CV. Add a note like 'Previously known as "
    "[fake name]' next to a real company, suggesting the candidate changed a fictional "
    "company to a real one.",
    "geo_mismatch": "The candidate declares they are based in a UK city but their phone number suggests "
    "another country. Use a non-UK phone number format: Romanian (+40), Spanish (+34), "
    "or Indian (+91) while the address says London or Manchester.",
    "skills_mismatch": "The candidate lists advanced technical skills in the skills section that do not "
    "appear anywhere in their work experience bullet points. For example: claims expert "
    "knowledge of Kubernetes, Terraform and ArgoCD in the skills section but none of "
    "these technologies are mentioned in any job description. The gap must be obvious.",
    "tech_anachronism": "One job must claim a technology that did not exist while that job ran. "
    "Keep the job dates consistent with the stated years of experience, and end the job at "
    "least two years before the technology was first released, so the gap is unambiguous. "
    "Choose a pair that fits the candidate's career from: dbt (first released 2016), "
    "HuggingFace Transformers (2018), GitHub Actions (November 2019), "
    "LangChain (October 2022), the GPT-4 API (March 2023), uv (February 2024). "
    "For example a role from 2013 to 2016 claiming GitHub Actions, or a role from "
    "2019 to 2021 claiming the GPT-4 API. "
    "Make the anachronism clear by using specific years in the job dates.",
}
