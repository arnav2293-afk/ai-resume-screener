"""Tests for the n8n workflow files: structure, safety, and the JavaScript inside the Code nodes."""

import csv
import json
import re

import pytest
from conftest import ROOT, WORKFLOWS

SCREENERS = ["screener_gemini", "screener_claude"]
SHEET_TEMPLATES = {
    "screener_gemini": ROOT / "sheet_templates" / "resume_screener.csv",
    "screener_claude": ROOT / "sheet_templates" / "resume_screener.csv",
    "matcher": ROOT / "sheet_templates" / "job_matches.csv",
}
# The exact text n8n passes on when the API answers 503 (seen in a real run on the free tier).
N8N_503 = {"message": '503 - "{\\n  \\"error\\": {\\n    \\"code\\": 503,\\n    \\"message\\": '
                      '\\"The model is overloaded. Please try again later.\\",\\n    \\"status\\": '
                      '\\"UNAVAILABLE\\"\\n  }\\n}\\n"'}


def nodes(workflow):
    return {n["name"]: n for n in workflow["nodes"]}


def sheets_node(workflow):
    return next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.googleSheets")


# ---------------------------------------------------------------- structure and safety


@pytest.mark.parametrize("key", WORKFLOWS)
def test_nodes_form_one_chain_from_gmail_to_sheets(workflows, key):
    workflow = workflows[key]
    by_name = nodes(workflow)
    assert len(by_name) == len(workflow["nodes"]), "node names must be unique"
    order, current = [], workflow["nodes"][0]["name"]
    while current:
        order.append(current)
        outputs = workflow["connections"].get(current, {}).get("main", [[]])
        targets = [link["node"] for branch in outputs for link in branch]
        assert len(targets) <= 1, f"{current} should connect to one node"
        assert all(t in by_name for t in targets)
        current = targets[0] if targets else None
    assert order == [n["name"] for n in workflow["nodes"]]
    assert by_name[order[0]]["type"] == "n8n-nodes-base.gmailTrigger"
    assert by_name[order[-1]]["type"] == "n8n-nodes-base.googleSheets"


@pytest.mark.parametrize("key", WORKFLOWS)
def test_workflow_is_safe_to_share(workflows, key):
    workflow = workflows[key]
    assert workflow["active"] is False
    for node in workflow["nodes"]:
        for credential in node.get("credentials", {}).values():
            assert credential["id"] == "", "credential IDs belong to one n8n instance"
    text = WORKFLOWS[key].read_text(encoding="utf-8")
    assert not re.search(r"AIza[0-9A-Za-z_-]{30,}|sk-ant-[0-9A-Za-z_-]{20,}", text), "API key in workflow"


@pytest.mark.parametrize("key", WORKFLOWS)
def test_api_calls_retry_and_never_stop_the_workflow(workflows, key):
    http_nodes = [n for n in workflows[key]["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    assert http_nodes
    for node in http_nodes:
        assert node["parameters"]["authentication"] == "genericCredentialType"
        assert node["retryOnFail"] is True and node["maxTries"] == 3
        assert node["onError"] == "continueRegularOutput"


@pytest.mark.parametrize("key", WORKFLOWS)
def test_sheet_settings_and_template_match(workflows, key):
    params = sheets_node(workflows[key])["parameters"]
    assert params["operation"] == "appendOrUpdate"
    assert params["columns"]["matchingColumns"] == ["Email"]
    assert params["options"]["cellFormat"] == "RAW"
    assert params["documentId"]["value"] == "PASTE_YOUR_GOOGLE_SHEET_ID_HERE"
    columns = [c["id"] for c in params["columns"]["schema"]]
    with SHEET_TEMPLATES[key].open(encoding="utf-8") as f:
        assert next(csv.reader(f)) == columns


def test_gmail_filters_do_not_overlap(workflows):
    for key in SCREENERS:
        query = nodes(workflows[key])["Gmail Trigger"]["parameters"]["filters"]["q"]
        assert '-subject:"job match"' in query
    assert 'subject:"job match"' in nodes(workflows["matcher"])["Gmail Trigger"]["parameters"]["filters"]["q"]


def test_matcher_jobs_match_jobs_file(workflows, run_code_node):
    jobs = json.loads((ROOT / "matcher" / "jobs.json").read_text(encoding="utf-8"))
    out = run_code_node(workflows["matcher"], "Prepare Texts", [{"text": "Test Person"}],
                        {"Gmail Trigger": [{"subject": "Job Match"}]})
    assert out[0]["jobs"] == [{k: j[k] for k in ("job_code", "title", "description")} for j in jobs]


# ---------------------------------------------------------------- screener Code node

GMAIL = {"date": "2026-11-23T10:00:00Z", "subject": "Application",
         "from": {"value": [{"address": "Sender@Gmail.com", "name": "Sender"}]}}
GOOD = {"name": "Aarav Mehta", "email": "AARAV@example.com ", "phone": "+91 90000 11101", "score": 88.4,
        "summary": "Line 1\nLine 2\nLine 3", "top_skills": ["n8n", "Python"], "missing_skills": [],
        "recommendation": "Shortlist"}


def gemini_reply(text, finish="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": finish}]}


def screen(workflows, run_code_node, key, reply):
    return run_code_node(workflows[key], "Parse AI JSON", [reply], {"Gmail Trigger": [GMAIL]})[0]


@pytest.mark.parametrize("key", SCREENERS)
def test_screener_builds_clean_row(workflows, run_code_node, key):
    row = screen(workflows, run_code_node, key, gemini_reply(json.dumps(GOOD)))
    columns = [c["id"] for c in sheets_node(workflows[key])["parameters"]["columns"]["schema"]]
    assert list(row) == columns
    assert row["Score"] == 88
    assert row["Email"] == "aarav@example.com"
    assert row["Top Skills"] == "n8n, Python"
    assert row["Recommendation"] == "Shortlist"


@pytest.mark.parametrize("key", SCREENERS)
def test_screener_reads_claude_replies(workflows, run_code_node, key):
    reply = {"content": [{"type": "thinking", "thinking": ""},
                         {"type": "text", "text": "```json\n" + json.dumps(GOOD) + "\n```"}],
             "stop_reason": "end_turn"}
    assert screen(workflows, run_code_node, key, reply)["Score"] == 88


@pytest.mark.parametrize("key", SCREENERS)
def test_screener_fixes_raw_line_breaks_and_bad_recommendation(workflows, run_code_node, key):
    text = '{"name": "A", "email": "", "score": 50, "summary": "one\ntwo", "recommendation": "Yes!"}'
    row = screen(workflows, run_code_node, key, gemini_reply(text))
    assert row["Summary"] == "one two"
    assert row["Recommendation"] == "Maybe"
    assert row["Email"] == "sender@gmail.com"  # falls back to the sender, so the duplicate check still works


@pytest.mark.parametrize("key", SCREENERS)
@pytest.mark.parametrize(("reply", "reason"), [
    ({"error": N8N_503}, "AI API error: 503 The model is overloaded. Please try again later."),
    (gemini_reply('{"name": "Aa', finish="MAX_TOKENS"), "Gemini stopped early: MAX_TOKENS"),
    ({"promptFeedback": {"blockReason": "SAFETY"}}, "Gemini blocked the request: SAFETY"),
    (gemini_reply("Score: 80"), "Invalid JSON from AI"),
    ({"content": [], "stop_reason": "refusal"}, "Claude stopped early: refusal"),
])
def test_screener_failures_become_manual_review_rows(workflows, run_code_node, key, reply, reason):
    row = screen(workflows, run_code_node, key, reply)
    assert row["Summary"].startswith("NEEDS MANUAL REVIEW\n" + reason)
    assert row["Email"] == "sender@gmail.com"
    assert row["Recommendation"] == "Maybe"


# ---------------------------------------------------------------- matcher Code nodes

RESUME = "Priya Sharma\npriya.sharma@example.com | +91 90000 11108\nB.Com graduate, Tally ERP, GST filing"


def prepare(workflows, run_code_node, subject, text=RESUME):
    gmail = {**GMAIL, "subject": subject}
    return run_code_node(workflows["matcher"], "Prepare Texts", [{"text": text}], {"Gmail Trigger": [gmail]})[0]


@pytest.mark.parametrize(("subject", "applied"), [
    ("Job Match JOB-04", "JOB-04"), ("job match job-06 application", "JOB-06"),
    ("Job Match", "JOB-01"), ("Job Match JOB-99", "JOB-01"),
])
def test_prepare_texts_reads_job_code_from_subject(workflows, run_code_node, subject, applied):
    assert prepare(workflows, run_code_node, subject)["candidate"]["appliedFor"] == applied


def test_prepare_texts_builds_one_embeddings_request(workflows, run_code_node):
    out = prepare(workflows, run_code_node, "Job Match JOB-01")
    assert out["candidate"]["name"] == "Priya Sharma"
    assert out["candidate"]["email"] == "priya.sharma@example.com"  # from the resume, not the sender
    requests = out["embedBody"]["requests"]
    assert len(requests) == 1 + len(out["jobs"]) == 16
    assert requests[0]["content"]["parts"][0]["text"] == RESUME
    assert {r["model"] for r in requests} == {"models/gemini-embedding-001"}


def fake_embeddings(prepared, close_jobs):
    """Resume vector [1, 0]; jobs in close_jobs get vectors near it, in that order; the rest point away."""
    vectors = [[1.0, 0.0]]
    for job in prepared["jobs"]:
        rank = close_jobs.index(job["job_code"]) if job["job_code"] in close_jobs else None
        vectors.append([1.0, 0.1 * rank] if rank is not None else [0.0, 1.0])
    return {"embeddings": [{"values": v} for v in vectors]}


def shortlist(workflows, run_code_node, prepared, embed_reply):
    return run_code_node(workflows["matcher"], "Free Shortlist (top 3)", [embed_reply], {"Prepare Texts": [prepared]})


def test_free_shortlist_keeps_the_three_closest_jobs(workflows, run_code_node):
    prepared = prepare(workflows, run_code_node, "Job Match JOB-01")
    out = shortlist(workflows, run_code_node, prepared, fake_embeddings(prepared, ["JOB-06", "JOB-11", "JOB-13"]))
    assert [item["job"]["job_code"] for item in out] == ["JOB-06", "JOB-11", "JOB-13"]
    assert [item["rank"] for item in out] == [1, 2, 3]
    assert out[0]["similarity"] == 1.0
    body = out[0]["aiBody"]
    assert "<job>\nAccounts and Taxation Executive (JOB-06)" in body["contents"][0]["parts"][0]["text"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_free_shortlist_failure_scores_only_the_applied_job(workflows, run_code_node):
    prepared = prepare(workflows, run_code_node, "Job Match JOB-04")
    out = shortlist(workflows, run_code_node, prepared, {"error": N8N_503})
    assert len(out) == 1
    assert out[0]["job"]["job_code"] == "JOB-04"
    assert out[0]["shortlistNote"]


def combine(workflows, run_code_node, prepared, short, replies):
    refs = {"Free Shortlist (top 3)": short, "Prepare Texts": [prepared]}
    return run_code_node(workflows["matcher"], "Combine Into One Row", replies, refs)


def scored(score, reason="ok"):
    reply = gemini_reply(json.dumps({"score": score, "reason": reason, "recommendation": "x"}))
    reply["usageMetadata"] = {"promptTokenCount": 500, "candidatesTokenCount": 50}
    return reply


def matcher_case(workflows, run_code_node, subject, close_jobs, replies):
    prepared = prepare(workflows, run_code_node, subject)
    short = shortlist(workflows, run_code_node, prepared, fake_embeddings(prepared, close_jobs))
    return combine(workflows, run_code_node, prepared, short, replies)


def test_combine_finds_a_better_opening(workflows, run_code_node):
    rows = matcher_case(workflows, run_code_node, "Job Match JOB-01", ["JOB-06", "JOB-11", "JOB-13"],
                        [scored(90), scored(40), scored(15)])
    assert len(rows) == 1
    row = rows[0]
    columns = [c["id"] for c in sheets_node(workflows["matcher"])["parameters"]["columns"]["schema"]]
    assert list(row) == columns
    assert row["Applied Job Score"] == "not in top 3"
    assert row["Best Match"] == "JOB-06 Accounts and Taxation Executive"
    assert (row["Best Score"], row["Recommendation"]) == (90, "Shortlist")
    assert row["Result"] == "Better opening found: Accounts and Taxation Executive"
    assert row["AI Calls"] == 3
    assert row["Tokens (in/out)"] == "1500 / 150"


def test_combine_flags_failed_calls_with_a_readable_reason(workflows, run_code_node):
    row = matcher_case(workflows, run_code_node, "Job Match JOB-01", ["JOB-06", "JOB-11", "JOB-13"],
                       [scored(95), scored(40), {"error": N8N_503}])[0]
    assert row["Best Score"] == 95
    assert row["Result"] == "NEEDS MANUAL REVIEW (some AI calls failed)"
    assert "REVIEW (AI API error: 503 The model is overloaded. Please try again later.)" in row["Top 3 Scores"]
    assert '\\"' not in row["Top 3 Scores"]


@pytest.mark.parametrize(("subject", "replies", "result", "recommendation"), [
    ("Job Match JOB-06", [scored(92), scored(60), scored(30)], "Applied job is the best fit", "Shortlist"),
    ("Job Match JOB-01", [scored(70), scored(60), scored(30)], "No strong match (best below 75)", "Maybe"),
    ("Job Match JOB-01", [{"error": N8N_503}, gemini_reply("not json"), gemini_reply("{", finish="MAX_TOKENS")],
     "NEEDS MANUAL REVIEW", "REVIEW"),
])
def test_combine_results(workflows, run_code_node, subject, replies, result, recommendation):
    row = matcher_case(workflows, run_code_node, subject, ["JOB-06", "JOB-11", "JOB-13"], replies)[0]
    assert (row["Result"], row["Recommendation"]) == (result, recommendation)


def test_combine_when_the_free_shortlist_failed(workflows, run_code_node):
    prepared = prepare(workflows, run_code_node, "Job Match JOB-04")
    short = shortlist(workflows, run_code_node, prepared, {"error": N8N_503})
    row = combine(workflows, run_code_node, prepared, short, [scored(81)])[0]
    assert row["Result"] == "Only the applied job was checked (free shortlist failed)"
    assert (row["Applied Job Score"], row["AI Calls"]) == ("81 Shortlist", 1)


def test_combine_makes_one_row_per_candidate(workflows, run_code_node):
    first = prepare(workflows, run_code_node, "Job Match JOB-01")
    second = prepare(workflows, run_code_node, "Job Match JOB-01", "Rohan Desai\nrohan.desai@example.com\nReact")
    embeds = [fake_embeddings(first, ["JOB-06", "JOB-11", "JOB-13"]),
              fake_embeddings(second, ["JOB-04", "JOB-15", "JOB-01"])]
    short = run_code_node(workflows["matcher"], "Free Shortlist (top 3)", embeds, {"Prepare Texts": [first, second]})
    assert len(short) == 6
    # Prepare Texts items line up with the shortlist items, as n8n's item pairing does.
    refs = {"Free Shortlist (top 3)": short, "Prepare Texts": [first] * 3 + [second] * 3}
    rows = run_code_node(workflows["matcher"], "Combine Into One Row", [scored(s) for s in (90, 40, 15, 95, 65, 62)],
                         refs)
    assert [(r["Name"], r["Best Score"]) for r in rows] == [("Priya Sharma", 90), ("Rohan Desai", 95)]
