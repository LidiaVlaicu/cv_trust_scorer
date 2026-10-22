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

import argparse
from pathlib import Path

from dataset_generation.claude_api import generate_cv_text
from dataset_generation.ground_truth import append_entry, recorded_ids
from dataset_generation.prompt import build_cv_prompt
from dataset_generation.specs import cv_filename, generate_specs
from dataset_generation.text_to_pdf import text_to_pdf

OUTPUT_ROOT = Path("data")
GROUND_TRUTH = OUTPUT_ROOT / "ground_truth.csv"
TOTAL_CVS = 300

# One Claude call per CV, at Haiku rates. Only used to state the bill before
# asking; the real cost is whatever the API charges.
COST_PER_CV = 0.0057


def pending(specs: list[dict], already_made: set[str]) -> list[dict]:
    """
    The CVs still to generate.

    A spec is pending when the ground truth file has no record of it and no
    file is sitting where it would go. Asking the record rather than only the
    filename is what stops a spec change - which renames every later CV - from
    making hundreds of already-generated CVs look missing.
    """
    return [
        spec
        for spec in specs
        if spec["id"] not in already_made
        and not (OUTPUT_ROOT / spec["folder"] / cv_filename(spec)).exists()
    ]


def confirm(count: int, ask=None) -> bool:
    """
    States what the run would cost and waits for a yes.

    `ask` is resolved here rather than defaulting to `input` in the signature,
    which would bind the builtin once and ignore anything that replaces it.
    """
    ask = ask or input
    print(f"\n{count} CVs to generate.")
    print(f"That is {count} Claude calls, roughly ${count * COST_PER_CV:.2f}.\n")
    return ask("Generate them? [y/N]: ").strip().lower() == "y"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic CV dataset.")
    parser.add_argument(
        "--limit", type=int, help="generate at most this many CVs this run"
    )
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation (for scripts)"
    )
    args = parser.parse_args(argv)

    for folder in ("inconsistent", "legitimate"):
        (OUTPUT_ROOT / folder).mkdir(parents=True, exist_ok=True)

    specs = generate_specs(TOTAL_CVS)
    print(f"Total:        {len(specs)} CVs")
    print(f"Inconsistent: {sum(1 for s in specs if s['folder'] == 'inconsistent')}")
    print(f"Legitimate:   {sum(1 for s in specs if s['folder'] == 'legitimate')}\n")

    already_made = recorded_ids(GROUND_TRUTH)
    todo = pending(specs, already_made)
    skipped = len(specs) - len(todo)

    if not todo:
        print("Every CV already exists. Nothing to generate.")
        return

    if args.limit is not None:
        todo = todo[: args.limit]
        print(f"Limit applied: {len(todo)} of the missing CVs will be generated.")

    if not args.yes and not confirm(len(todo)):
        print("Nothing generated.")
        return

    generated = failed = 0
    for spec in todo:
        output_path = OUTPUT_ROOT / spec["folder"] / cv_filename(spec)
        inconsistencies = ", ".join(spec["inconsistency_types"]) or "none"
        print(
            f"[{spec['id']}] {spec['seniority']} {spec['role']} "
            f"({spec['folder']}) | {inconsistencies}"
        )
        try:
            text_to_pdf(generate_cv_text(build_cv_prompt(spec)), str(output_path))
            append_entry(GROUND_TRUTH, spec=spec, filename=output_path.name)
            print(f"       Saved: {output_path}")
            generated += 1
        except Exception as error:
            print(f"[{spec['id']}] Failed: {type(error).__name__}: {error}")
            failed += 1

    print(f"\nDone. Generated: {generated} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    main()
