"""Tests for the Python side: JSON cleaning, cut-offs and the project's data files."""

import json

import pytest
import smart_job_matcher as matcher
from test_scoring import JOB_FILE, PROMPT_FILE, RESUME_DIR, extract_pdf_text, parse_llm_json


def test_parses_plain_json():
    data = parse_llm_json('{"name": "Aarav", "score": 88, "recommendation": "Shortlist"}')
    assert data["score"] == 88
    assert data["recommendation"] == "Shortlist"


def test_strips_code_fences_and_extra_words():
    reply = 'Here is the result:\n```json\n{"score": 42, "recommendation": "Reject"}\n```\nHope this helps.'
    assert parse_llm_json(reply)["score"] == 42


def test_handles_raw_line_breaks_inside_strings():
    reply = '{"score": 80, "summary": "line one\nline two", "recommendation": "Shortlist"}'
    assert parse_llm_json(reply)["summary"] == "line one line two"


@pytest.mark.parametrize(("raw_score", "expected"), [(150, 100), (-5, 0), ("88.6", 89), (70.2, 70)])
def test_score_is_rounded_and_clamped(raw_score, expected):
    reply = json.dumps({"score": raw_score, "recommendation": "Maybe"})
    assert parse_llm_json(reply)["score"] == expected


@pytest.mark.parametrize(("score", "expected"), [(70, "Shortlist"), (69, "Maybe"), (45, "Maybe"), (44, "Reject")])
def test_invalid_recommendation_is_recalculated(score, expected):
    reply = json.dumps({"score": score, "recommendation": "Strong yes"})
    assert parse_llm_json(reply)["recommendation"] == expected


def test_reply_without_json_raises():
    with pytest.raises(ValueError):
        parse_llm_json("Score: 80 out of 100")


@pytest.mark.parametrize(("score", "expected"), [(100, "Shortlist"), (75, "Shortlist"), (74, "Maybe"),
                                                 (50, "Maybe"), (49, "Reject"), (0, "Reject")])
def test_matcher_cut_offs(score, expected):
    assert matcher.recommendation_for(score) == expected


def test_prompt_and_data_files_exist():
    for path in (PROMPT_FILE, JOB_FILE, matcher.PROMPT_FILE, matcher.JOBS_FILE, matcher.RESULTS_FILE):
        assert path.is_file(), path


def test_sample_resumes_are_readable():
    pdfs = sorted(RESUME_DIR.glob("*.pdf"))
    assert len(pdfs) == 10
    text = extract_pdf_text(pdfs[0])
    assert text.startswith("Aarav Mehta")
    assert "@example.com" in text  # made-up contact details only


def test_jobs_file_is_well_formed():
    jobs = json.loads(matcher.JOBS_FILE.read_text(encoding="utf-8"))
    codes = [job["job_code"] for job in jobs]
    assert codes == [f"JOB-{n:02d}" for n in range(1, 16)]
    assert all(job["title"] and job["description"] for job in jobs)
    assert matcher.APPLIED_FOR in codes
