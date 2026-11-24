"""
Builds showcase/index.html: one page presenting both prototypes, filled with REAL results.

- Prototype 1 screenshots come from docs/screenshots/.
- Prototype 2 data comes from matcher/results.csv (the real AI run) and matcher/jobs.json.
- Talent pool matches are computed here with the same free embedding model as the matcher.

Usage:
    python showcase/build_showcase.py            # writes showcase/index.html
    python showcase/build_showcase.py --fragment out.html   # page body only (for hosting that adds <head>)
"""

import argparse
import base64
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "matcher"))
from smart_job_matcher import APPLIED_FOR, EMBED_MODEL, POOL_MIN_SIMILARITY, embed, job_text, load_data  # noqa: E402

TEMPLATE = ROOT / "showcase" / "template.html"
OUT = ROOT / "showcase" / "index.html"
SHOTS = [
    ("Workflow", "01_workflow.png", "The n8n workflow after a successful run: all 5 nodes green.",
     "n8n workflow with Gmail Trigger, Extract from File, Gemini, Parse AI JSON and Google Sheets nodes"),
    ("Google Sheet", "02_google_sheet.png", "The sheet the workflow filled: 95 Shortlist, 42 Reject, 5 Reject, each with a summary and skills.",
     "Google Sheet with three screened candidates"),
    ("Parsed output", "03_parsed_output.png", "What the Code node outputs for one candidate: clean fields ready for the sheet.",
     "Parse AI JSON node output for Aarav Mehta"),
]


def image_uri(name: str) -> str:
    data = (ROOT / "docs" / "screenshots" / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def build_data():
    jobs, resumes = load_data()
    rows = list(csv.DictReader((ROOT / "matcher" / "results.csv").open(encoding="utf-8")))

    candidates, order = {}, []
    for r in rows:
        name = r["candidate"]
        if name not in candidates:
            candidates[name] = {"name": name, "top": []}
            order.append(name)
        candidates[name]["top"].append({
            "job_code": r["job_code"],
            "job_title": r["job_title"],
            "similarity": float(r["similarity"]),
            "ai_score": int(r["ai_score"]) if r["ai_score"] else None,
            "reason": r["reason"],
        })

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBED_MODEL, device="cpu")
    job_vecs = embed(model, [job_text(j) for j in jobs])
    res_vecs = embed(model, [r["text"] for r in resumes])
    sim = job_vecs @ res_vecs.T  # rows = jobs, columns = resumes
    pool = {}
    for j_idx, job in enumerate(jobs):
        ranked = sim[j_idx].argsort()[::-1][:3]
        pool[job["job_code"]] = [{"name": resumes[i]["name"], "similarity": round(float(sim[j_idx][i]), 3)} for i in ranked]

    return {
        "applied_for": APPLIED_FOR,
        "n_jobs": len(jobs),
        "jobs": {j["job_code"]: {"job_code": j["job_code"], "title": j["title"]} for j in jobs},
        "candidates": [candidates[n] for n in order],
        "pool": pool,
        "pool_min": POOL_MIN_SIMILARITY,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fragment", help="also write the page body only to this path")
    args = parser.parse_args()

    data = build_data()
    shots = [{"label": l, "src": image_uri(f), "caption": c, "alt": a} for l, f, c, a in SHOTS]
    body = (TEMPLATE.read_text(encoding="utf-8")
            .replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
            .replace("/*SHOTS*/null", json.dumps(shots)))

    full = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            "</head>\n<body>\n" + body + "\n</body>\n</html>\n")
    OUT.write_text(full, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    if args.fragment:
        Path(args.fragment).write_text(body, encoding="utf-8")
        print(f"Wrote {args.fragment}")


if __name__ == "__main__":
    main()
