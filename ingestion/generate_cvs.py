import anthropic
import os
import random
import csv
from pathlib import Path
from dotenv import load_dotenv
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

Path("data/inconsistent").mkdir(parents=True, exist_ok=True)
Path("data/legitimate").mkdir(parents=True, exist_ok=True)

# ── Technology timeline ───────────────────────────────────────────────────
TECH_TIMELINE = {
    "dbt": 2019, "Apache Spark": 2014, "Spark": 2014, "Kafka": 2012,
    "Airflow": 2016, "Dagster": 2020, "Snowflake": 2015, "BigQuery": 2011,
    "Delta Lake": 2019, "Databricks": 2016, "Fivetran": 2016,
    "PyTorch": 2017, "TensorFlow": 2015, "scikit-learn": 2010,
    "HuggingFace": 2019, "LangChain": 2023, "ChatGPT API": 2023,
    "OpenAI API": 2020, "BERT": 2018, "MLflow": 2018, "Kubeflow": 2018,
    "Kubernetes": 2017, "Docker": 2015, "Terraform": 2015,
    "GitHub Actions": 2019, "ArgoCD": 2020, "Helm": 2016,
    "Prometheus": 2015, "Grafana": 2014,
    "React": 2015, "Next.js": 2018, "TypeScript": 2017,
    "Tailwind": 2020, "Vue.js": 2016, "GraphQL": 2016,
}

def check_tech_anachronism(technology, job_start_year):
    available_year = TECH_TIMELINE.get(technology)
    if available_year is None:
        return "not_in_dictionary"
    return "anachronism" if int(job_start_year) < available_year else "coherent"

# ── Configuration ─────────────────────────────────────────────────────────
ROLES = [
    "Data Engineer", "Data Scientist", "Machine Learning Engineer",
    "DevOps Engineer", "Software Engineer", "Backend Engineer",
    "Frontend Engineer", "Full Stack Engineer", "Data Analyst",
    "BI Analyst", "Staff Engineer", "Principal Engineer", "Research Engineer",
]

SENIOR_ONLY_ROLES = ["Staff Engineer", "Principal Engineer"]

SENIORITY_CONFIG = {
    "Junior": {"years": ["1", "2"],         "github_prob": 0.7},
    "Mid":    {"years": ["3", "4", "5"],    "github_prob": 0.5},
    "Senior": {"years": ["6", "7", "8"],    "github_prob": 0.3},
    "Staff":  {"years": ["10", "12", "14"], "github_prob": 0.1},
}

LOCATIONS = [
    # UK
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
    # Europe
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

INCONSISTENCY_TYPES = {
    "fictional_company":
        "Include exactly one completely fictional company that does not exist in any public "
        "business registry. Use a convincing but fake name like 'NovaTech Solutions Ltd', "
        "'DataStream Analytics Inc', 'CloudPeak Technologies Ltd', 'Nexus Digital Co', "
        "'Synapse Data Ltd', or similar. The other companies must be real.",

    "fictional_company_2":
        "Include exactly TWO completely fictional companies that do not exist in any public "
        "business registry. Use convincing but fake names. The third company must be real.",

    "date_overlap":
        "Create an impossible date overlap between two full-time jobs. The overlap must be "
        "at least 3 months. Make it subtle: for example job 1 ends March 2021 and job 2 "
        "starts January 2021, creating a 2-month overlap. Both jobs should appear full-time.",

    "ai_text":
        "Write the professional summary using clearly AI-generated language. Overuse corporate "
        "buzzwords: results-driven, highly motivated, cutting-edge, actionable insights, "
        "cross-functional collaboration, mission-critical, leverage, spearhead, champion, "
        "synergistically, proven track record, dynamic, innovative, passionate about delivering "
        "value, data-driven decision making, organisational objectives. Make it generic and "
        "impersonal with no specific personal details.",

    "career_incoherent":
        "Make the career progression completely incoherent and impossible. Examples: "
        "jumped from Junior Engineer to Staff Engineer in only 18 months, "
        "claims to have managed a team of 20+ engineers as a Junior, "
        "went from Graduate to Principal Engineer in 2 years, "
        "or a Mid-level analyst claims to have directed a department of 50 people. "
        "The progression must be clearly impossible for the declared seniority level.",

    "company_substitution":
        "Simulate a company substitution between CV versions: include one fictional company "
        "(that does not exist in public registries) for an early role, and make it clear "
        "the candidate recently updated their CV. Add a note like 'Previously known as "
        "[fake name]' next to a real company, suggesting the candidate changed a fictional "
        "company to a real one.",

    "geo_mismatch":
        "The candidate declares they are based in a UK city but their phone number suggests "
        "another country. Use a non-UK phone number format: Romanian (+40), Spanish (+34), "
        "or Indian (+91) while the address says London or Manchester.",

    "skills_mismatch":
        "The candidate lists advanced technical skills in the skills section that do not "
        "appear anywhere in their work experience bullet points. For example: claims expert "
        "knowledge of Kubernetes, Terraform and ArgoCD in the skills section but none of "
        "these technologies are mentioned in any job description. The gap must be obvious.",

    "tech_anachronism":
        "The candidate claims to have used modern technologies during a job that ended "
        "before those technologies were widely available. Examples: "
        "used dbt in a role from 2014-2016 (dbt not widely available until 2019), "
        "used LangChain in a role from 2019-2021 (LangChain released in 2023), "
        "used GitHub Actions in a role from 2015-2018 (released in 2019), "
        "or used HuggingFace Transformers in a role from 2015-2017 (released in 2018). "
        "Make the anachronism clear by using specific years in the job dates.",
}

# ── PDF generator ─────────────────────────────────────────────────────────
def text_to_pdf(text, output_path):
    doc = SimpleDocTemplate(output_path, pagesize=A4,
        rightMargin=1.8*cm, leftMargin=1.8*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm)
    name_style = ParagraphStyle('Name', fontSize=16, fontName='Helvetica-Bold',
                                spaceAfter=4, textColor=colors.HexColor('#1a1a1a'))
    body_style = ParagraphStyle('Body', fontSize=9.5, fontName='Helvetica',
                                spaceAfter=4, leading=14, textColor=colors.HexColor('#333333'))
    section_style = ParagraphStyle('Section', fontSize=10, fontName='Helvetica-Bold',
                                   spaceBefore=6, spaceAfter=2, textColor=colors.HexColor('#1a1a1a'))
    story = []
    for i, line in enumerate(text.strip().split('\n')):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
        elif i == 0:
            story.append(Paragraph(line, name_style))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor('#cccccc')))
        elif line.isupper() and len(line) < 40:
            story.append(Spacer(1, 4))
            story.append(Paragraph(line, section_style))
            story.append(HRFlowable(width="100%", thickness=0.3,
                                    color=colors.HexColor('#dddddd')))
        else:
            story.append(Paragraph(line, body_style))
    doc.build(story)

# ── Claude API call ───────────────────────────────────────────────────────
def generate_cv_text(role, seniority, years, location, github, inconsistencies):
    city = location["city"]
    country = location["country"]
    phone_prefix = location["phone"]
    inconsistencies_text = ""
    if inconsistencies:
        inconsistencies_text = "\n\nINCONSISTENCIES TO INCLUDE (follow exactly):\n"
        for i, inc in enumerate(inconsistencies, 1):
            inconsistencies_text += f"{i}. {inc}\n"
        summary_instruction = (
            "Write the professional summary in a natural human voice."
            if "ai_text" not in " ".join(inconsistencies) else ""
        )
    else:
        summary_instruction = (
            "Write the professional summary in a natural human voice "
            "with specific personal details. Avoid all corporate buzzwords."
        )

    prompt = f"""Generate a realistic IT technical CV in plain text for:
- Role: {role}
- Seniority: {seniority}
- Years of experience: {years}
- City: {location['city']}, {location['country']}

Requirements:
- Fictional but realistic full name
- Fictional email (firstname.lastname@gmail.com)
- Fictional phone number starting with {location['phone']}
- LinkedIn URL
- {'GitHub URL with 3-4 relevant public repositories' if github else 'No GitHub URL'}
- Exactly 3 jobs in work experience
- Each job must include: job title, company name, company website if available,
  location, dates in format Month Year - Month Year, exactly 4 bullet points
- Education from a real university in {location['country']}
- Skills section with relevant technical skills
- Professional summary of 3-4 lines
{inconsistencies_text}
{summary_instruction}

IMPORTANT:
- Output ONLY the CV text, nothing else
- No markdown, no asterisks, no bold markers, no symbols
- Plain text only
- Fictional company websites must end in .io, .co, or .net
- Real companies must have their real website"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

# ── Spec generator ────────────────────────────────────────────────────────
def generate_specs(total=300):
    random.seed(42)
    specs = []
    half = total // 2
    inconsistency_keys = list(INCONSISTENCY_TYPES.keys())

    for i in range(1, half + 1):
        role = random.choice(ROLES)
        if role in SENIOR_ONLY_ROLES:
            seniority = random.choice(["Senior", "Staff"])
        else:
            seniority = random.choice(list(SENIORITY_CONFIG.keys()))
        config = SENIORITY_CONFIG[seniority]
        years = random.choice(config["years"])
        location = random.choice(LOCATIONS)
        github = random.random() < config["github_prob"]
        num_inc = random.randint(1, 3)
        chosen_keys = random.sample(inconsistency_keys, min(num_inc, len(inconsistency_keys)))
        inconsistencies = [INCONSISTENCY_TYPES[k] for k in chosen_keys]
        specs.append({
            "id": str(i).zfill(3),
            "folder": "inconsistent",
            "role": role,
            "seniority": seniority,
            "years": years,
            "location": location,
            "github": github,
            "inconsistencies": inconsistencies,
            "inconsistency_types": chosen_keys,
        })

    for i in range(half + 1, total + 1):
        role = random.choice(ROLES)
        if role in SENIOR_ONLY_ROLES:
            seniority = random.choice(["Senior", "Staff"])
        else:
            seniority = random.choice(list(SENIORITY_CONFIG.keys()))
        config = SENIORITY_CONFIG[seniority]
        years = random.choice(config["years"])
        location = random.choice(LOCATIONS)
        github = random.random() < config["github_prob"]
        specs.append({
            "id": str(i).zfill(3),
            "folder": "legitimate",
            "role": role,
            "seniority": seniority,
            "years": years,
            "location": location,
            "github": github,
            "inconsistencies": [],
            "inconsistency_types": [],
        })

    return specs

# ── Ground truth CSV ──────────────────────────────────────────────────────
def save_ground_truth(specs):
    with open("data/ground_truth.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "folder", "role", "seniority", "years",
            "location", "github", "inconsistency_types", "filename"
        ])
        writer.writeheader()
        for spec in specs:
            role_slug = spec["role"].lower().replace(" ", "_")
            seniority_slug = spec["seniority"].lower()
            filename = f"cv_{spec['id']}_{role_slug}_{seniority_slug}.pdf"
            writer.writerow({
                "id": spec["id"],
                "folder": spec["folder"],
                "role": spec["role"],
                "seniority": spec["seniority"],
                "years": spec["years"],
                "location": f"{spec['location']['city']}, {spec['location']['country']}",
                "github": spec["github"],
                "inconsistency_types": "|".join(spec["inconsistency_types"]),
                "filename": filename,
            })
    print("Ground truth saved: data/ground_truth.csv\n")

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    specs = generate_specs(300)
    print(f"Total:        {len(specs)} CVs")
    print(f"Inconsistent: {sum(1 for s in specs if s['folder'] == 'inconsistent')}")
    print(f"Legitimate:   {sum(1 for s in specs if s['folder'] == 'legitimate')}\n")
    save_ground_truth(specs)

    generated = 0
    failed = 0
    skipped = 0

    for spec in specs:
        role_slug = spec["role"].lower().replace(" ", "_")
        seniority_slug = spec["seniority"].lower()
        filename = f"cv_{spec['id']}_{role_slug}_{seniority_slug}.pdf"
        output_path = f"data/{spec['folder']}/{filename}"

        if Path(output_path).exists():
            skipped += 1
            continue

        try:
            inc_summary = ", ".join(spec["inconsistency_types"]) or "none"
            print(f"[{spec['id']}] {spec['seniority']} {spec['role']} ({spec['folder']}) | {inc_summary}")
            cv_text = generate_cv_text(
                role=spec["role"],
                seniority=spec["seniority"],
                years=spec["years"],
                location=spec["location"],
                github=spec["github"],
                inconsistencies=spec["inconsistencies"],
            )
            text_to_pdf(cv_text, output_path)
            print(f"       Saved: {output_path}")
            generated += 1
        except Exception as e:
            print(f"[{spec['id']}] Failed: {e}")
            failed += 1

    print(f"\nDone.")
    print(f"Generated: {generated} | Skipped: {skipped} | Failed: {failed}")

if __name__ == "__main__":
    main()