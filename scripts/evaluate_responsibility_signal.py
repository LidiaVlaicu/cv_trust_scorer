"""
Evaluates signal_responsibility_mismatch against the folder ground-truth label.

The synthetic CVs are generated into `inconsistent` and `legitimate` folders,
recorded on bronze.raw_cv_texts. That label is the only ground truth available,
so it is how each rule earns or loses its place in the signal.

The per-level breakdown at the end is what justifies the central design claim:
that no legitimate CV has an E1/E2 role claiming authority over anybody, which
is why that check needs no size threshold.

Run with:  python -m scripts.evaluate_responsibility_signal
"""

import os
from collections import Counter, defaultdict

from dotenv import load_dotenv
from google.cloud import bigquery

from reference import seniority_ladder as ladder
from gold.rules.responsibility_mismatch import (
    budget_millions,
    people_managed,
)

load_dotenv()


def main() -> None:
    client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
    project = client.project
    bronze = os.getenv("BQ_DATASET_BRONZE")
    silver = os.getenv("BQ_DATASET_SILVER")
    gold = os.getenv("BQ_DATASET_GOLD")

    rows = [
        dict(r)
        for r in client.query(f"""
            SELECT s.submission_id, s.confidence, s.findings, t.folder
            FROM `{project}.{gold}.signal_responsibility_mismatch` s
            LEFT JOIN `{bronze}.raw_cv_texts` t USING (submission_id)
        """).result()
    ]
    labelled = [r for r in rows if r["folder"]]
    print(f"candidates: {len(rows)} ({len(labelled)} with a folder label)")
    print("label split:", dict(Counter(r["folder"] for r in labelled)))

    positives = sum(1 for r in labelled if r["folder"] == "inconsistent")

    def report(name: str, fired) -> None:
        tp = sum(1 for r in labelled if fired(r) and r["folder"] == "inconsistent")
        fp = sum(1 for r in labelled if fired(r) and r["folder"] == "legitimate")
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / positives if positives else 0.0
        print(
            f"  {name:<36} fires {tp + fp:>3}  TP={tp:>3} FP={fp:>3}  "
            f"precision={precision:>5.0%}  recall={recall:>5.0%}"
        )

    def finding_names(row):
        return {f["name"] for f in row["findings"]}

    print(f"\n=== EACH CHECK AS A DETECTOR (of {positives} inconsistent CVs) ===")
    for name in sorted({n for r in labelled for n in finding_names(r)}):
        report(name, lambda r, n=name: n in finding_names(r))

    print("\n=== GROUPED ===")
    report("any finding at all", lambda r: bool(r["findings"]))
    report(
        "any proven finding",
        lambda r: any(f["evidence"] == "proven" for f in r["findings"]),
    )

    print("\n=== CONFIDENCE vs LABEL ===")
    matrix = defaultdict(Counter)
    for r in labelled:
        matrix[r["confidence"]][r["folder"]] += 1
    print(f"  {'confidence':<16} {'inconsistent':>14} {'legitimate':>12}")
    for value in ["confirmed", "possible", "not_confirmed", "not_evaluated"]:
        if value in matrix:
            print(f"  {value:<16} {matrix[value]['inconsistent']:>14} "
                  f"{matrix[value]['legitimate']:>12}")

    print("\n=== EVIDENCE STRENGTH, AS MEASURED ===")
    print("  (this is the evidence behind the `evidence` field in the table)")
    per_name = defaultdict(Counter)
    for r in labelled:
        for f in r["findings"]:
            per_name[(f["name"], f["evidence"])][r["folder"]] += 1
    for (name, strength), counts in sorted(per_name.items()):
        total = counts["inconsistent"] + counts["legitimate"]
        precision = counts["inconsistent"] / total if total else 0
        print(f"  {name:<36} {strength:<11} "
              f"inconsistent={counts['inconsistent']:>3} "
              f"legitimate={counts['legitimate']:>3} precision={precision:>5.0%}")

    # ── the claim the design rests on, measured per role rather than per CV ──
    print("\n=== AUTHORITY CLAIMED PER ROLE, BY LADDER BAND ===")
    print("  The E1/E2 check has no size threshold because no legitimate CV")
    print("  has an E1/E2 role claiming authority over anybody.")
    roles = [
        dict(r)
        for r in client.query(f"""
            SELECT w.seniority_level, w.description, t.folder
            FROM `{project}.{silver}.silver_work_experience` w
            LEFT JOIN `{bronze}.raw_cv_texts` t USING (submission_id)
            WHERE w.description IS NOT NULL AND t.folder IS NOT NULL
        """).result()
    ]
    print(f"\n  {'band':<6} {'label':<14} {'roles':>6} {'claim people':>13} "
          f"{'largest':>8} {'claim budget':>13}")
    grouped = defaultdict(list)
    for role in roles:
        band = ladder.ladder_level(role["seniority_level"]) or "(none)"
        grouped[(band, role["folder"])].append(role)
    for (band, folder), group in sorted(grouped.items()):
        people = [people_managed(r["description"]) for r in group]
        budgets = [budget_millions(r["description"]) for r in group]
        print(f"  {band:<6} {folder:<14} {len(group):>6} "
              f"{sum(1 for p in people if p):>13} {max(people):>8} "
              f"{sum(1 for b in budgets if b):>13}")

    print("\n=== EVERY ROLE THE SIGNAL FIRES ON ===")
    for r in sorted(labelled, key=lambda r: (r["folder"], r["submission_id"])):
        for f in r["findings"]:
            print(f"  [{r['folder']:<13}] {f['level']:<9} "
                  f"claimed={f['claimed']:>6.1f}  {f['name']:<34} "
                  f"{f['experience_id']}")


if __name__ == "__main__":
    main()
