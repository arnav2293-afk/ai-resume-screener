"""
Builds showcase/index.html: one page presenting both prototypes, filled with real results.

- Screenshots are linked from docs/screenshots/. GitHub Pages serves the whole repository,
  so the same relative links work online and when the page is opened from a local clone.
- Prototype 2 data comes from matcher/results.csv (the real AI run) and matcher/jobs.json.
- Talent pool matches are computed here with the same free embedding model as the matcher.

Usage:
    python showcase/build_showcase.py
"""

import csv
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "matcher"))
from smart_job_matcher import (  # noqa: E402
    APPLIED_FOR,
    EMBED_MODEL,
    POOL_MIN_SIMILARITY,
    embed,
    job_text,
    load_data,
)

TEMPLATE = ROOT / "showcase" / "template.html"
OUT = ROOT / "showcase" / "index.html"
SCREENSHOTS = ROOT / "docs" / "screenshots"
SITE = "https://arnav2293-afk.github.io/ai-resume-screener/"

TITLE = "Arnav's Hiring Prototypes"
DESCRIPTION = (
    "Two working AI hiring prototypes: an n8n workflow that screens resumes from Gmail into Google Sheets, "
    "and a Smart Job Matcher that checks every resume against every open job at low cost."
)
ICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' rx='14' fill='%232f4fd6'/%3E"
    "%3Ctext x='32' y='42' font-size='26' font-family='Arial' font-weight='700' text-anchor='middle' "
    "fill='white'%3EAI%3C/text%3E%3C/svg%3E"
)

# Prototype 1 screenshots: (tab label, file in docs/screenshots, caption, alt text)
SHOTS = [
    ("Workflow", "01_workflow.png",
     "The n8n workflow after a successful run: all 5 nodes green.",
     "n8n workflow with Gmail Trigger, Extract from File, Gemini, Parse AI JSON and Google Sheets nodes"),
    ("Google Sheet", "02_google_sheet.png",
     "The sheet the workflow filled: 95 Shortlist, 42 Reject, 5 Reject, each with a summary and skills.",
     "Google Sheet with three screened candidates"),
    ("Parsed output", "03_parsed_output.png",
     "What the Code node outputs for one candidate: clean fields ready for the sheet.",
     "Parse AI JSON node output for Aarav Mehta"),
]


def build_data():
    jobs, resumes = load_data()
    with (ROOT / "matcher" / "results.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    candidates = {}
    for r in rows:
        candidates.setdefault(r["candidate"], {"name": r["candidate"], "top": []})["top"].append({
            "job_code": r["job_code"],
            "job_title": r["job_title"],
            "similarity": float(r["similarity"]),
            "ai_score": int(r["ai_score"]) if r["ai_score"] else None,
            "reason": r["reason"],
        })

    from sentence_transformers import SentenceTransformer  # slow to import, so only here

    model = SentenceTransformer(EMBED_MODEL, device="cpu")
    job_vecs = embed(model, [job_text(j) for j in jobs])
    res_vecs = embed(model, [r["text"] for r in resumes])
    sim = job_vecs @ res_vecs.T  # rows = jobs, columns = resumes
    pool = {}
    for j_idx, job in enumerate(jobs):
        ranked = sim[j_idx].argsort()[::-1][:3]
        pool[job["job_code"]] = [
            {"name": resumes[i]["name"], "similarity": round(float(sim[j_idx][i]), 3)} for i in ranked
        ]

    return {
        "applied_for": APPLIED_FOR,
        "n_jobs": len(jobs),
        "jobs": {j["job_code"]: {"job_code": j["job_code"], "title": j["title"]} for j in jobs},
        "candidates": list(candidates.values()),
        "pool": pool,
        "pool_min": POOL_MIN_SIMILARITY,
    }


def build_shots():
    shots = []
    for label, name, caption, alt in SHOTS:
        if not (SCREENSHOTS / name).exists():
            sys.exit(f"Missing screenshot: docs/screenshots/{name}")
        shots.append({"label": label, "src": f"../docs/screenshots/{name}", "caption": caption, "alt": alt})
    return shots


def head() -> str:
    title, desc = html.escape(TITLE), html.escape(DESCRIPTION)
    return (
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"<title>{title}</title>\n"
        f'<meta name="description" content="{desc}">\n'
        '<meta name="theme-color" content="#2f4fd6">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:title" content="{title}">\n'
        f'<meta property="og:description" content="{desc}">\n'
        f'<meta property="og:url" content="{SITE}showcase/">\n'
        f'<meta property="og:image" content="{SITE}docs/screenshots/02_google_sheet.png">\n'
        f'<link rel="icon" href="{ICON}">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    )


def main():
    template = TEMPLATE.read_text(encoding="utf-8")
    # The template starts with its font links and <style>; those belong in <head>.
    styles, sep, body = template.partition("</style>\n")
    if not sep:
        sys.exit("template.html must contain a <style> block followed by the page body")
    body = (body.replace("/*DATA*/null", json.dumps(build_data(), ensure_ascii=False))
                .replace("/*SHOTS*/null", json.dumps(build_shots(), ensure_ascii=False)))

    page = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n" + head() + styles + sep
        + "</head>\n<body>\n" + body.rstrip() + "\n</body>\n</html>\n"
    )
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
