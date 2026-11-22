"""
Local test for the screening prompt, without n8n.

Reads every PDF in sample_resumes/, sends the text + job description to Claude
using the same system prompt as the n8n workflow, and prints a results table.

Setup:
    pip install -r requirements.txt
    cp .env.example .env      # then paste your ANTHROPIC_API_KEY

Usage:
    python scripts/test_scoring.py
"""

import json
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
RESUME_DIR = ROOT / "sample_resumes"
PROMPT_FILE = ROOT / "prompts" / "screening_prompt.md"
JOB_FILE = ROOT / "job_description.md"

MODEL = "claude-haiku-5-5"
TIMEOUT_SECONDS = 60      # per request
SDK_RETRIES = 3           # SDK retries timeouts, 429 and 5xx with backoff
JSON_ATTEMPTS = 2         # ask again once if the reply is not valid JSON
VALID_RECOMMENDATIONS = {"Shortlist", "Maybe", "Reject"}


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def parse_claude_json(raw: str) -> dict:
    """Same idea as the n8n Code node: strip code fences, find the {...} block, parse it."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in reply")
    data = json.loads(cleaned[start : end + 1])

    score = int(round(float(data.get("score", 0))))
    data["score"] = max(0, min(100, score))
    if data.get("recommendation") not in VALID_RECOMMENDATIONS:
        data["recommendation"] = "Shortlist" if score >= 70 else "Maybe" if score >= 45 else "Reject"
    return data


def score_resume(client: anthropic.Anthropic, system_prompt: str, job: str, resume: str) -> dict:
    user_message = (
        f"<job_description>\n{job}\n</job_description>\n\n"
        f"<resume>\n{resume}\n</resume>"
    )
    last_error = ""
    for attempt in range(1, JSON_ATTEMPTS + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            output_config={"effort": "low"},
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request")
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            return parse_claude_json(text)
        except (ValueError, json.JSONDecodeError) as err:
            last_error = f"invalid JSON on attempt {attempt}: {err}"
    raise ValueError(last_error)


def main() -> int:
    load_dotenv(ROOT / ".env")
    pdfs = sorted(RESUME_DIR.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found. Run: python scripts/generate_sample_resumes.py")
        return 1

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    job = JOB_FILE.read_text(encoding="utf-8")
    try:
        client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=SDK_RETRIES)
    except anthropic.AnthropicError as err:
        print(f"Could not create client (is ANTHROPIC_API_KEY set in .env?): {err}")
        return 1

    rows = []
    for pdf in pdfs:
        print(f"Scoring {pdf.name} ...", flush=True)
        try:
            result = score_resume(client, system_prompt, job, extract_pdf_text(pdf))
            rows.append((result.get("name") or pdf.stem, str(result["score"]), result["recommendation"]))
        except anthropic.AuthenticationError:
            print("Authentication failed: check ANTHROPIC_API_KEY in .env")
            return 1
        except anthropic.APITimeoutError:
            rows.append((pdf.stem, "-", f"ERROR: timed out after {SDK_RETRIES} retries"))
        except anthropic.RateLimitError:
            rows.append((pdf.stem, "-", "ERROR: rate limited"))
        except anthropic.APIConnectionError:
            rows.append((pdf.stem, "-", "ERROR: network problem"))
        except anthropic.APIStatusError as err:
            rows.append((pdf.stem, "-", f"ERROR: API {err.status_code}"))
        except (ValueError, RuntimeError) as err:
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
