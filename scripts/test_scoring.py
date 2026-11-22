"""
Local test for the screening prompt, without n8n.

Reads every PDF in sample_resumes/, sends the text + job description to an LLM
using the same system prompt as the n8n workflow, and prints a results table.

Two providers are supported:
  gemini  (default) Google Gemini free tier, model gemini-3.5-flash-lite
  claude            Anthropic Claude API (paid), model claude-haiku-5-5

Setup:
    pip install -r requirements.txt
    cp .env.example .env      # then paste GEMINI_API_KEY (and/or ANTHROPIC_API_KEY)

Usage:
    python scripts/test_scoring.py                    # Gemini
    python scripts/test_scoring.py --provider claude  # Claude
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
RESUME_DIR = ROOT / "sample_resumes"
PROMPT_FILE = ROOT / "prompts" / "screening_prompt.md"
JOB_FILE = ROOT / "job_description.md"

MODELS = {"gemini": "gemini-3.5-flash-lite", "claude": "claude-haiku-5-5"}
TIMEOUT_SECONDS = 60      # per request
SDK_RETRIES = 3           # the SDKs retry timeouts, 429 and 5xx with backoff
JSON_ATTEMPTS = 2         # ask again once if the reply is not valid JSON
PAUSE_SECONDS = {"gemini": 5, "claude": 0}   # stay under the free tier's requests-per-minute limit
VALID_RECOMMENDATIONS = {"Shortlist", "Maybe", "Reject"}


class ScoringError(Exception):
    """A problem scoring one resume. fatal=True stops the whole run (e.g. bad API key)."""

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def parse_llm_json(raw: str) -> dict:
    """Same idea as the n8n Code node: strip code fences, find the {...} block, parse it."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in reply")
    json_text = cleaned[start : end + 1]
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        # Second try: raw line breaks inside strings are invalid JSON, so turn them into spaces.
        data = json.loads(re.sub(r"[\r\n]+", " ", json_text))

    score = int(round(float(data.get("score", 0))))
    data["score"] = max(0, min(100, score))
    if data.get("recommendation") not in VALID_RECOMMENDATIONS:
        data["recommendation"] = "Shortlist" if score >= 70 else "Maybe" if score >= 45 else "Reject"
    return data


# ---------------------------------------------------------------- Gemini (free)

def make_gemini_caller(system_prompt: str):
    from google import genai
    from google.genai import errors, types

    if not os.getenv("GEMINI_API_KEY"):
        raise ScoringError("GEMINI_API_KEY is missing in .env", fatal=True)

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(
            timeout=TIMEOUT_SECONDS * 1000,  # milliseconds
            retry_options=types.HttpRetryOptions(attempts=SDK_RETRIES + 1),
        ),
    )
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",  # Gemini's JSON mode
        max_output_tokens=2000,
    )

    def call(user_message: str) -> str:
        try:
            response = client.models.generate_content(
                model=MODELS["gemini"], contents=user_message, config=config
            )
        except errors.ClientError as err:  # 4xx
            if err.code in (400, 401, 403):
                raise ScoringError(f"Gemini rejected the request ({err.code}): check GEMINI_API_KEY", fatal=True)
            if err.code == 429:
                raise ScoringError("rate limited (free tier quota reached, try again later)")
            raise ScoringError(f"Gemini API {err.code}")
        except errors.ServerError as err:  # 5xx after retries
            raise ScoringError(f"Gemini server error {err.code}")
        except Exception as err:
            if "Timeout" in type(err).__name__:
                raise ScoringError(f"timed out after {SDK_RETRIES} retries")
            raise
        if not response.text:
            raise ScoringError("empty reply (possibly blocked by safety filters)")
        return response.text

    return call


# ---------------------------------------------------------------- Claude (paid)

def make_claude_caller(system_prompt: str):
    import anthropic

    try:
        client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=SDK_RETRIES)
    except anthropic.AnthropicError as err:
        raise ScoringError(f"could not create client (is ANTHROPIC_API_KEY set in .env?): {err}", fatal=True)

    def call(user_message: str) -> str:
        try:
            response = client.messages.create(
                model=MODELS["claude"],
                max_tokens=4000,
                output_config={"effort": "low"},
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.AuthenticationError:
            raise ScoringError("authentication failed: check ANTHROPIC_API_KEY in .env", fatal=True)
        except anthropic.APITimeoutError:
            raise ScoringError(f"timed out after {SDK_RETRIES} retries")
        except anthropic.RateLimitError:
            raise ScoringError("rate limited")
        except anthropic.APIConnectionError:
            raise ScoringError("network problem")
        except anthropic.APIStatusError as err:
            raise ScoringError(f"Claude API {err.status_code}")
        if response.stop_reason == "refusal":
            raise ScoringError("Claude declined this request")
        return "".join(block.text for block in response.content if block.type == "text")

    return call


# ---------------------------------------------------------------- main

def score_resume(call, job: str, resume: str) -> dict:
    user_message = (
        f"<job_description>\n{job}\n</job_description>\n\n"
        f"<resume>\n{resume}\n</resume>"
    )
    last_error = ""
    for attempt in range(1, JSON_ATTEMPTS + 1):
        try:
            return parse_llm_json(call(user_message))
        except (ValueError, json.JSONDecodeError) as err:
            last_error = f"invalid JSON on attempt {attempt}: {err}"
    raise ScoringError(last_error)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the sample resumes with an LLM.")
    parser.add_argument("--provider", choices=MODELS, default="gemini")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    pdfs = sorted(RESUME_DIR.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found. Run: python scripts/generate_sample_resumes.py")
        return 1

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    job = JOB_FILE.read_text(encoding="utf-8")
    try:
        make_caller = make_gemini_caller if args.provider == "gemini" else make_claude_caller
        call = make_caller(system_prompt)
    except ScoringError as err:
        print(f"Error: {err}")
        return 1

    print(f"Provider: {args.provider} ({MODELS[args.provider]})\n")
    rows = []
    for i, pdf in enumerate(pdfs):
        if i and PAUSE_SECONDS[args.provider]:
            time.sleep(PAUSE_SECONDS[args.provider])
        print(f"Scoring {pdf.name} ...", flush=True)
        try:
            result = score_resume(call, job, extract_pdf_text(pdf))
            rows.append((result.get("name") or pdf.stem, str(result["score"]), result["recommendation"]))
        except ScoringError as err:
            if err.fatal:
                print(f"Error: {err}")
                return 1
            rows.append((pdf.stem, "-", f"ERROR: {err}"))

    name_w = max(len("Name"), *(len(r[0]) for r in rows))
    print()
    print(f"{'Name':<{name_w}}  {'Score':>5}  Recommendation")
    print(f"{'-' * name_w}  {'-' * 5}  {'-' * 14}")
    for name, score, rec in sorted(rows, key=lambda r: -int(r[1]) if r[1].isdigit() else 1):
        print(f"{name:<{name_w}}  {score:>5}  {rec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
