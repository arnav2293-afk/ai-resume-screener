"""
Smart Job Matcher: live demo app (Prototype 2).

Pick a sample resume (or upload a made-up one), click Run, and watch the 4 steps:
  1. Read the PDF
  2. FREE shortlist: compare with every open job using embeddings on this computer
  3. AI scores only the top 3 jobs (Gemini free tier)
  4. Code applies the 75 cut-off and the recruiter decides

Run:
    .venv/bin/streamlit run matcher/app.py
"""

import csv
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "matcher"))
sys.path.insert(0, str(ROOT / "scripts"))
import smart_job_matcher as sjm  # noqa: E402

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="Smart Job Matcher", layout="wide")

BADGE = {"Shortlist": ":green-background[Shortlist]", "Maybe": ":orange-background[Maybe]",
         "Reject": ":red-background[Reject]", "REVIEW": ":gray-background[Needs review]"}


# ---------------------------------------------------------------- cached setup (loads once)

@st.cache_resource(show_spinner="Loading the free embedding model...")
def get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(sjm.EMBED_MODEL, device="cpu")


@st.cache_resource(show_spinner="Reading jobs and sample resumes...")
def get_data():
    jobs, resumes = sjm.load_data()
    model = get_model()
    job_vecs = sjm.embed(model, [sjm.job_text(j) for j in jobs])
    resume_vecs = sjm.embed(model, [r["text"] for r in resumes])
    return jobs, resumes, job_vecs, resume_vecs


@st.cache_resource
def get_scorer():
    if not os.getenv("GEMINI_API_KEY"):
        return None
    return sjm.make_ai_scorer(sjm.PROMPT_FILE.read_text(encoding="utf-8"))


@st.cache_data
def saved_results():
    """Scores from the full test run, used only as a labelled backup if the AI is busy."""
    out = {}
    with sjm.RESULTS_FILE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["ai_score"]:
                out[(r["candidate"], r["job_code"])] = (int(r["ai_score"]), r["reason"])
    return out


def read_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def haiku_cost_inr(tokens_in: int, tokens_out: int) -> float:
    usd = tokens_in / 1e6 * sjm.HAIKU_USD_PER_M_INPUT + tokens_out / 1e6 * sjm.HAIKU_USD_PER_M_OUTPUT
    return usd * sjm.USD_TO_INR


# ---------------------------------------------------------------- the pipeline

def run_pipeline(name: str, text: str, applied: str, use_ai: bool, top_k: int):
    jobs, _, job_vecs, _ = get_data()
    model = get_model()
    result = {"name": name, "text": text, "applied": applied, "steps": {}}

    t = time.perf_counter()
    vec = sjm.embed(model, [text])[0]
    sims = job_vecs @ vec
    order = sims.argsort()[::-1]
    result["steps"]["shortlist_ms"] = (time.perf_counter() - t) * 1000
    result["all_jobs"] = [{"job": jobs[i], "similarity": float(sims[i]), "rank": rank + 1}
                          for rank, i in enumerate(order)]
    top = [jobs[i] | {"similarity": float(sims[i])} for i in order[:top_k]]

    scorer = get_scorer() if use_ai else None
    saved = saved_results()
    scored, tokens_in, tokens_out, calls = [], 0, 0, 0
    t = time.perf_counter()
    progress = st.progress(0.0, text="AI is scoring the shortlisted jobs...") if scorer else None
    for n, job in enumerate(top, start=1):
        entry = {"job": job, "score": None, "reason": "", "source": "not scored"}
        if scorer:
            out = scorer(job, text)
            calls += 1
            tokens_in += out["tokens_in"]
            tokens_out += out["tokens_out"]
            if out["score"] is not None:
                entry.update(score=out["score"], reason=out["reason"], source="live AI")
            elif (name, job["job_code"]) in saved:
                s, reason = saved[(name, job["job_code"])]
                entry.update(score=s, reason=reason, source="AI busy: saved score from test run")
            else:
                entry.update(reason=out["reason"], source="needs manual review")
            progress.progress(n / len(top), text=f"AI scored {n} of {len(top)} jobs")
        scored.append(entry)
    if progress:
        progress.empty()
    result["steps"]["ai_s"] = time.perf_counter() - t
    result.update(scored=scored, calls=calls, tokens_in=tokens_in, tokens_out=tokens_out, n_jobs=len(jobs))
    return result


# ---------------------------------------------------------------- page

st.title("Smart Job Matcher")
st.caption("Prototype 2 · One resume, checked against every open job · All resumes and jobs are made up")

with st.sidebar:
    st.subheader("How it works")
    st.markdown(
        "1. **Read** the resume PDF\n"
        "2. **Free shortlist:** compare it with every open job by meaning (embeddings, on this computer)\n"
        "3. **AI scores only the top 3** with a rubric and a reason\n"
        "4. **Code applies the cut-off** (75+ Shortlist, 50 to 74 Maybe, below 50 Reject). The recruiter decides."
    )
    st.divider()
    top_k = st.slider("Jobs the AI scores", 1, 5, sjm.TOP_K, key="top_k")
    use_ai = st.toggle("Use AI scoring (Gemini free tier)", value=True, key="use_ai")
    if use_ai and not os.getenv("GEMINI_API_KEY"):
        st.warning("No GEMINI_API_KEY in .env, so only the free shortlist will run.")
    st.divider()
    st.caption(f"Cost shown at Claude Haiku 5.5 list prices (${sjm.HAIKU_USD_PER_M_INPUT} in, "
               f"${sjm.HAIKU_USD_PER_M_OUTPUT} out per million tokens), at an assumed Rs {sjm.USD_TO_INR:.0f} per USD.")

jobs, resumes, job_vecs, resume_vecs = get_data()
job_by_code = {j["job_code"]: j for j in jobs}
job_codes = [j["job_code"] for j in jobs]
label = lambda code: f"{code} · {job_by_code[code]['title']}"

tab_match, tab_pool, tab_jobs = st.tabs(["Match a resume", "Talent pool", f"Open jobs ({len(jobs)})"])

# ---------- Tab 1: match one resume
with tab_match:
    left, right = st.columns(2)
    with left:
        source = st.radio("Resume", ["Sample resume", "Upload a PDF"], horizontal=True, key="source")
        names = [r["name"] for r in resumes]
        if source == "Sample resume":
            pick = st.selectbox("Choose a candidate", names, index=names.index("Ananya Iyer"), key="pick")
            resume_name, resume_text = pick, next(r["text"] for r in resumes if r["name"] == pick)
        else:
            up = st.file_uploader("Upload a resume PDF", type="pdf", key="upload")
            st.caption("Use made-up resumes only. The free AI tier may use what you send to improve its products.")
            resume_name, resume_text = (None, None)
            if up:
                resume_text = read_pdf(up.getvalue())
                resume_name = resume_text.splitlines()[0].strip() if resume_text else up.name
    with right:
        applied = st.selectbox("Applied for", job_codes, index=job_codes.index(sjm.APPLIED_FOR),
                               format_func=label, key="applied")
        st.write("")
        run = st.button("Run matcher", type="primary", disabled=not resume_text, key="run")

    if run and resume_text:
        with st.spinner("Running..."):
            st.session_state["result"] = run_pipeline(resume_name, resume_text, applied, use_ai, top_k)

    res = st.session_state.get("result")
    if res:
        st.divider()
        st.subheader(res["name"])

        # Step 1
        with st.container(border=True):
            st.markdown(f"**Step 1 · Read the resume** · {len(res['text'].split())} words extracted from the PDF")
            with st.expander("Show the extracted text"):
                st.text(res["text"][:3000])

        # Step 2
        with st.container(border=True):
            st.markdown(f"**Step 2 · Free shortlist** · compared with all {res['n_jobs']} open jobs in "
                        f"{res['steps']['shortlist_ms']:.0f} ms · cost Rs 0 · no data left this computer")
            table = pd.DataFrame([{
                "Rank": row["rank"],
                "Job": label(row["job"]["job_code"]),
                "Similarity": row["similarity"],
                "Sent to AI": "Yes" if row["rank"] <= len(res["scored"]) else "",
                "Applied for": "Applied" if row["job"]["job_code"] == res["applied"] else "",
            } for row in res["all_jobs"]])
            st.dataframe(table, hide_index=True, width="stretch", height=300, column_config={
                "Similarity": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f"),
            })

        # Step 3
        scored = res["scored"]
        with st.container(border=True):
            if res["calls"]:
                st.markdown(f"**Step 3 · AI scored only the top {len(scored)}** · {res['calls']} AI calls instead of "
                            f"{res['n_jobs']} · {res['steps']['ai_s']:.1f} s")
            else:
                st.markdown("**Step 3 · AI scoring is off** · turn it on in the sidebar to score the shortlist")
            cols = st.columns(len(scored))
            for col, e in zip(cols, scored):
                with col.container(border=True):
                    st.markdown(f"**{e['job']['title']}**  \n`{e['job']['job_code']}` · similarity {e['job']['similarity']:.2f}")
                    if e["score"] is not None:
                        st.metric("AI score", e["score"])
                        st.markdown(BADGE[sjm.recommendation_for(e["score"])])
                    else:
                        st.metric("AI score", "-")
                        if res["calls"]:
                            st.markdown(BADGE["REVIEW"])
                    if e["reason"]:
                        st.caption(e["reason"])
                    if e["source"] != "live AI" and res["calls"]:
                        st.caption(f"Source: {e['source']}")

        # Step 4
        with st.container(border=True):
            st.markdown("**Step 4 · Recruiter decides**")
            done = [e for e in scored if e["score"] is not None]
            applied_title = job_by_code[res["applied"]]["title"]
            applied_entry = next((e for e in scored if e["job"]["job_code"] == res["applied"]), None)
            applied_txt = (f"{applied_title} scored {applied_entry['score']} "
                           f"({sjm.recommendation_for(applied_entry['score'])})" if applied_entry and applied_entry["score"] is not None
                           else f"{applied_title} was not in the top {len(scored)}, so no AI money was spent on it")
            if done:
                best = max(done, key=lambda e: e["score"])
                if best["job"]["job_code"] != res["applied"] and best["score"] >= 75:
                    st.success(f"Better opening found: **{best['job']['title']}** scored **{best['score']}**. "
                               f"Applied for: {applied_txt}. Checked against one job only, this match would be missed.")
                elif best["job"]["job_code"] == res["applied"]:
                    st.info(f"The job they applied for is their best fit: {applied_txt}.")
                else:
                    st.warning(f"No opening reached the 75 cut-off. Best: {best['job']['title']} ({best['score']}). "
                               f"A recruiter decides whether to keep them in the talent pool.")
            else:
                st.info("Shortlist ready. Turn on AI scoring to get scores and reasons.")

            if res["calls"]:
                c1, c2, c3 = st.columns(3)
                c1.metric("AI calls", f"{res['calls']} of {res['n_jobs']}",
                          f"{100 * (1 - res['calls'] / res['n_jobs']):.0f}% fewer", delta_color="off")
                c2.metric("Tokens", f"{res['tokens_in']:,} in", f"{res['tokens_out']:,} out", delta_color="off")
                c3.metric("Cost for this resume", f"Rs {haiku_cost_inr(res['tokens_in'], res['tokens_out']):.3f}",
                          "on Claude Haiku 5.5", delta_color="off")

# ---------- Tab 2: talent pool
with tab_pool:
    st.markdown("A new job opens. Before sourcing anyone new, search the candidates you already have. "
                "**Free: no AI call.**")
    code = st.selectbox("New opening", job_codes, index=job_codes.index("JOB-09"), format_func=label, key="pool_job")
    j_idx = job_codes.index(code)
    sims = resume_vecs @ job_vecs[j_idx]
    order = sims.argsort()[::-1][:5]
    strong = [resumes[i]["name"] for i in order if sims[i] >= sjm.POOL_MIN_SIMILARITY]
    if strong:
        st.success(f"{len(strong)} strong match{'es' if len(strong) > 1 else ''} already in the pool: "
                   f"**{', '.join(strong)}**. Next: a recruiter checks they are available and interested.")
    else:
        st.warning(f"No strong match in the pool (best similarity {sims[order[0]]:.2f}, needs "
                   f"{sjm.POOL_MIN_SIMILARITY}). Start fresh sourcing for this role.")
    st.dataframe(pd.DataFrame([{
        "Candidate": resumes[i]["name"],
        "Similarity": float(sims[i]),
        "Suggest?": "Yes" if sims[i] >= sjm.POOL_MIN_SIMILARITY else "No, below 0.45",
    } for i in order]), hide_index=True, width="stretch", column_config={
        "Similarity": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f"),
    })

# ---------- Tab 3: jobs
with tab_jobs:
    st.caption("The made-up openings the matcher checks every resume against.")
    st.dataframe(pd.DataFrame([{"Code": j["job_code"], "Title": j["title"], "Client": j["client"],
                                "Description": j["description"]} for j in jobs]),
                 hide_index=True, width="stretch", height=560)
