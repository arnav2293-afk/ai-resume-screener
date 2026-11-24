"""
Smart Job Matcher: one resume, checked against every open job.

Idea 1 (default mode):
  1. FREE step: turn every resume and every job into embeddings (numbers that capture meaning)
     with a small model that runs on this computer, and keep the TOP 3 closest jobs per resume.
  2. PAID step: the AI scores the resume against only those 3 jobs, with a rubric and a reason.
  3. Code (not the AI) applies the cut-off: 75+ Shortlist, 50-74 Maybe, below 50 Reject.
  4. A recruiter makes the final decision.

Idea 2 (--pool JOB-10): Talent Pool Rediscovery, the same engine in reverse.
  For a new job, rank the candidates already in the pool. Free: no AI call at all.

All jobs and resumes are made up.

Usage:
    python matcher/smart_job_matcher.py               # Idea 1, with AI scoring (Gemini free tier)
    python matcher/smart_job_matcher.py --no-ai       # Idea 1, free shortlist only
    python matcher/smart_job_matcher.py --pool JOB-02 # Idea 2
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from test_scoring import extract_pdf_text, parse_llm_json  # reuse the same PDF reader and JSON cleaner

JOBS_FILE = ROOT / "matcher" / "jobs.json"
RESUME_DIR = ROOT / "sample_resumes"
PROMPT_FILE = ROOT / "prompts" / "matching_prompt.md"
RESULTS_FILE = ROOT / "matcher" / "results.csv"

EMBED_MODEL = "all-MiniLM-L6-v2"   # free, small (about 90 MB), runs on CPU
AI_MODEL = "gemini-3.5-flash-lite" # free tier for testing with made-up data
TOP_K = 3                          # how many jobs the AI scores per resume
APPLIED_FOR = "JOB-01"             # all sample resumes were written for the AI Intern role
PAUSE_SECONDS = 5                  # stay under the free tier's per-minute limit
POOL_MIN_SIMILARITY = 0.45         # Idea 2: below this, don't suggest anyone (picked from this test data)

# Cost estimate if the same token counts ran on Claude Haiku 5.5 (list price, prompts up to 100K tokens)
HAIKU_USD_PER_M_INPUT = 0.10
HAIKU_USD_PER_M_OUTPUT = 0.50
USD_TO_INR = 88.0                  # ASSUMED exchange rate, check today's rate before quoting


def recommendation_for(score: int) -> str:
    """The cut-off is applied by code, so it is always consistent."""
    return "Shortlist" if score >= 75 else "Maybe" if score >= 50 else "Reject"


def load_data():
    jobs = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    resumes = []
    for pdf in sorted(RESUME_DIR.glob("*.pdf")):
        text = extract_pdf_text(pdf)
        name = text.splitlines()[0].strip() if text else pdf.stem
        resumes.append({"file": pdf.name, "name": name, "text": text})
    return jobs, resumes


def embed(model, texts):
    # normalize_embeddings=True means the dot product equals cosine similarity (1 = same meaning)
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def job_text(job):
    return f"{job['title']}. {job['description']}"


def make_ai_scorer(system_prompt: str):
    from google import genai
    from google.genai import errors, types

    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is missing in .env (or run with --no-ai)")
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=60_000, retry_options=types.HttpRetryOptions(attempts=4)),
    )
    config = types.GenerateContentConfig(
        system_instruction=system_prompt, response_mime_type="application/json", max_output_tokens=1000
    )

    def score(job, resume_text):
        message = (
            f"<job>\n{job['title']} ({job['job_code']})\n{job['description']}\n</job>\n\n"
            f"<resume>\n{resume_text}\n</resume>"
        )
        for attempt in range(3):  # extra retries for "server busy" errors, waiting 10 s then 20 s
            try:
                response = client.models.generate_content(model=AI_MODEL, contents=message, config=config)
                data = parse_llm_json(response.text or "")
                break
            except errors.ServerError:
                if attempt < 2:
                    time.sleep(10 * (attempt + 1))
                    continue
                return {"score": None, "reason": "needs manual review: AI server busy", "tokens_in": 0, "tokens_out": 0}
            except Exception as err:  # bad request, timeout or invalid JSON: never lose the candidate
                return {"score": None, "reason": f"needs manual review: {type(err).__name__}", "tokens_in": 0, "tokens_out": 0}
        usage = response.usage_metadata
        tokens_out = (usage.candidates_token_count or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
        return {
            "score": data["score"],
            "reason": str(data.get("reason", "")).strip(),
            "tokens_in": usage.prompt_token_count or 0,
            "tokens_out": tokens_out,
        }

    return score


def run_matcher(model, jobs, resumes, use_ai: bool):
    job_vecs = embed(model, [job_text(j) for j in jobs])
    resume_vecs = embed(model, [r["text"] for r in resumes])
    similarity = resume_vecs @ job_vecs.T  # rows = resumes, columns = jobs

    scorer = make_ai_scorer(PROMPT_FILE.read_text(encoding="utf-8")) if use_ai else None
    rows, total_in, total_out, ai_calls = [], 0, 0, 0

    for r_idx, resume in enumerate(resumes):
        top = similarity[r_idx].argsort()[::-1][:TOP_K]
        print(f"\n{resume['name']}  (applied for {APPLIED_FOR})")
        best, failed_jobs = None, set()
        for j_idx in top:
            job, sim = jobs[j_idx], float(similarity[r_idx][j_idx])
            row = {"candidate": resume["name"], "job_code": job["job_code"], "job_title": job["title"],
                   "similarity": round(sim, 3), "ai_score": "", "recommendation": "", "reason": ""}
            if scorer:
                if ai_calls:
                    time.sleep(PAUSE_SECONDS)
                result = scorer(job, resume["text"])
                ai_calls += 1
                total_in += result["tokens_in"]
                total_out += result["tokens_out"]
                if result["score"] is not None:
                    row["ai_score"] = result["score"]
                    row["recommendation"] = recommendation_for(result["score"])
                    if best is None or result["score"] > best[1]:
                        best = (job["job_code"], result["score"], job["title"])
                else:
                    row["recommendation"] = "REVIEW"
                    failed_jobs.add(job["job_code"])
                row["reason"] = result["reason"]
            rows.append(row)
            score_txt = f"AI {str(row['ai_score']):>3}  {row['recommendation']:<9}" if scorer else ""
            print(f"  {job['job_code']}  {job['title'][:38]:<38}  similarity {sim:.2f}  {score_txt}")
        # Only claim a better fit if every shortlisted job was actually scored
        if best and best[0] != APPLIED_FOR and not failed_jobs and best[1] >= 75:
            print(f"  -> Best fit is a DIFFERENT opening: {best[2]} ({best[1]})")

    if scorer:
        cost_usd = total_in / 1e6 * HAIKU_USD_PER_M_INPUT + total_out / 1e6 * HAIKU_USD_PER_M_OUTPUT
        per_resume_inr = cost_usd * USD_TO_INR / len(resumes)
        all_calls = len(resumes) * len(jobs)
        print("\n--- Cost ---")
        print(f"AI calls made: {ai_calls} (scoring every job would need {all_calls}: "
              f"{100 * (1 - ai_calls / all_calls):.0f}% fewer)")
        print(f"Tokens measured: {total_in:,} in, {total_out:,} out")
        print(f"Estimated cost on Claude Haiku 5.5: ${cost_usd:.4f} total, "
              f"about Rs {per_resume_inr:.3f} per resume (at Rs {USD_TO_INR:.0f} per USD, assumed)")
        print("Shortlist step: free (runs on this computer)")

    with RESULTS_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} rows to {RESULTS_FILE.relative_to(ROOT)}")


def run_pool(model, jobs, resumes, job_code: str, top_n: int = 3):
    job = next((j for j in jobs if j["job_code"] == job_code), None)
    if not job:
        sys.exit(f"Unknown job code {job_code}. Choose from: {', '.join(j['job_code'] for j in jobs)}")
    job_vec = embed(model, [job_text(job)])[0]
    resume_vecs = embed(model, [r["text"] for r in resumes])
    ranked = sorted(zip(resumes, resume_vecs @ job_vec), key=lambda x: -x[1])
    strong = [(r, s) for r, s in ranked[:top_n] if s >= POOL_MIN_SIMILARITY]
    print(f"New opening: {job['title']} ({job_code})")
    if not strong:
        print(f"No strong match in the pool (best similarity {ranked[0][1]:.2f}, "
              f"needs {POOL_MIN_SIMILARITY}). Start fresh sourcing for this role.")
        return
    print("Strong matches already in the pool (free, no AI call):")
    for resume, sim in strong:
        print(f"  {resume['name']:<15} similarity {sim:.2f}")
    print("Next: AI scores these few (optional), then a recruiter checks they are available and interested.")


def main():
    parser = argparse.ArgumentParser(description="Smart Job Matcher demo (made-up data)")
    parser.add_argument("--no-ai", action="store_true", help="free shortlist only, no AI calls")
    parser.add_argument("--pool", metavar="JOB_CODE", help="Talent Pool Rediscovery for one job")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    from sentence_transformers import SentenceTransformer  # imported here: slow to load
    model = SentenceTransformer(EMBED_MODEL, device="cpu")
    jobs, resumes = load_data()
    print(f"{len(resumes)} resumes, {len(jobs)} open jobs")

    if args.pool:
        run_pool(model, jobs, resumes, args.pool)
    else:
        run_matcher(model, jobs, resumes, use_ai=not args.no_ai)


if __name__ == "__main__":
    main()
