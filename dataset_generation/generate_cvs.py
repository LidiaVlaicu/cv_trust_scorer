"""
Generates the synthetic CV dataset: plan it, ask Claude for each CV, save a PDF.

Orchestration only, every decision lives elsewhere:

    specs.py            what dataset to build
    inconsistencies.py  what "inconsistent" means
    prompt.py           how to ask for one CV
    claude_api.py       the API call
    text_to_pdf.py      how to render it

A CV whose PDF already exists is skipped, so a failed run can be repeated
without paying for the CVs that already succeeded.
"""

from pathlib import Path

from dataset_generation.claude_api import generate_cv_text
from dataset_generation.prompt import build_cv_prompt
from dataset_generation.specs import cv_filename, generate_specs
from dataset_generation.text_to_pdf import text_to_pdf

OUTPUT_ROOT = Path("data")
TOTAL_CVS = 300


def main() -> None:
    for folder in ("inconsistent", "legitimate"):
        (OUTPUT_ROOT / folder).mkdir(parents=True, exist_ok=True)

    specs = generate_specs(TOTAL_CVS)
    print(f"Total:        {len(specs)} CVs")
    print(f"Inconsistent: {sum(1 for s in specs if s['folder'] == 'inconsistent')}")
    print(f"Legitimate:   {sum(1 for s in specs if s['folder'] == 'legitimate')}\n")

    generated = skipped = failed = 0
    for spec in specs:
        output_path = OUTPUT_ROOT / spec["folder"] / cv_filename(spec)
        if output_path.exists():
            skipped += 1
            continue

        inconsistencies = ", ".join(spec["inconsistency_types"]) or "none"
        print(f"[{spec['id']}] {spec['seniority']} {spec['role']} "
              f"({spec['folder']}) | {inconsistencies}")
        try:
            text_to_pdf(generate_cv_text(build_cv_prompt(spec)), str(output_path))
            print(f"       Saved: {output_path}")
            generated += 1
        except Exception as error:
            print(f"[{spec['id']}] Failed: {type(error).__name__}: {error}")
            failed += 1

    print(f"\nDone. Generated: {generated} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    main()
