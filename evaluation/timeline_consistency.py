"""
Evaluates signal_timeline_consistency against the folder ground-truth label.

The synthetic CVs are generated into `inconsistent` and `legitimate` folders,
recorded on bronze.raw_cv_texts. That label is the only ground truth available,
so it is how each rule earns or loses its place in the signal.

Run with:  python -m evaluation.timeline_consistency
"""

import os
from collections import Counter, defaultdict

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()


def main() -> None:
    client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
    project = client.project
    bronze = os.getenv("BQ_DATASET_BRONZE")
    gold = os.getenv("BQ_DATASET_GOLD")

    rows = [
        dict(r)
        for r in client.query(f"""
            SELECT s.submission_id, s.confidence, s.findings,
                   t.folder
            FROM `{project}.{gold}.signal_timeline_consistency` s
            LEFT JOIN `{bronze}.raw_cv_texts` t USING (submission_id)
        """).result()
    ]
    labelled = [r for r in rows if r["folder"]]
    print(f"candidates: {len(rows)} ({len(labelled)} with a folder label)")
    print("label split:", dict(Counter(r["folder"] for r in labelled)))

    positives = sum(1 for r in labelled if r["folder"] == "inconsistent")
    negatives = len(labelled) - positives

    def report(name: str, fired) -> None:
        tp = sum(1 for r in labelled if fired(r) and r["folder"] == "inconsistent")
        fp = sum(1 for r in labelled if fired(r) and r["folder"] == "legitimate")
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / positives if positives else 0.0
        print(
            f"  {name:<34} fires {tp + fp:>3}  "
            f"TP={tp:>3} FP={fp:>3}  "
            f"precision={precision:>5.0%}  recall={recall:>5.0%}"
        )

    def finding_codes(row):
        return {f["name"] for f in row["findings"]}

    def evidence_strengths(row):
        return {f["evidence"] for f in row["findings"]}

    print(f"\n=== EACH FINDING CODE AS A DETECTOR (of {positives} inconsistent CVs) ===")
    for code in sorted({c for r in labelled for c in finding_codes(r)}):
        report(code, lambda r, c=code: c in finding_codes(r))

    print("\n=== GROUPED ===")
    report("any overlap finding", lambda r: any("overlap" in c for c in finding_codes(r)))
    report("any gap finding", lambda r: any("gap" in c and "unevaluable" not in c
                                            for c in finding_codes(r)))
    report("any seniority finding", lambda r: any("seniority" in c for c in finding_codes(r)))
    report("any proven finding", lambda r: "proven" in evidence_strengths(r))
    report("any finding at all", lambda r: bool(r["findings"]))

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
    per_code = defaultdict(Counter)
    for r in labelled:
        for f in r["findings"]:
            per_code[(f["name"], f["evidence"])][r["folder"]] += 1
    for (name, strength), counts in sorted(per_code.items()):
        total = counts["inconsistent"] + counts["legitimate"]
        precision = counts["inconsistent"] / total if total else 0
        print(f"  {name:<28} {strength:<13} "
              f"inconsistent={counts['inconsistent']:>3} legitimate={counts['legitimate']:>3} "
              f"precision={precision:>5.0%}")

    print("\n=== CANDIDATES WITH THE MOST FINDINGS ===")
    for r in sorted(labelled, key=lambda r: -len(r["findings"]))[:10]:
        detail = ", ".join(f"{f['name']}({f['months']})" for f in r["findings"])
        print(f"  {len(r['findings'])}  {r['confidence']:<14} {r['folder']:<13} "
              f"{r['submission_id']:<38} {detail}")


if __name__ == "__main__":
    main()
