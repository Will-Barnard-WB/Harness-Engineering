"""
Student Review Generator — Streamlit UI
========================================

Visual interface for the Teaching harness. Wraps the same agent backend as
harness.py but replaces terminal human gates with a browser UI.

State machine (stored in st.session_state["state"]):

  upload
    → pass1_running   (agent Pass 1 runs in background, main thread free)
    → grade_gate      (teacher reviews / overrides grade)
    → ratings_gate    (teacher enters effort / engagement / quality)
    → pass2_running   (agent Pass 2 runs in background, main thread free)
    → approve         (teacher approves or rejects)
    → (next student → pass1_running, or complete)

Long-running agent calls are submitted to a ThreadPoolExecutor so
Streamlit's main thread is never blocked. The `pass1_running` /
`pass2_running` states poll future.done() on each rerun (0.4 s sleep),
giving responsive spinners without WebSocket timeouts.

SETUP:
  pip install streamlit pandas
  cd Teaching && /opt/homebrew/bin/python3.11 -m streamlit run app.py
"""

import asyncio
import concurrent.futures
import csv
import io
import sys
import time
from pathlib import Path

import streamlit as st

# ── Import shared logic from harness.py ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from harness import (
    CLASS_REVIEWS,
    CSV_PATH,
    GRADES,
    HARNESS_DIR,
    LOGGING_DIR,
    RATING_LABELS,
    REVIEWS_DIR,
    append_to_class_reviews,
    extract_grade_from_review,
    run_agent,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Student Review Generator",
    page_icon="📋",
    layout="wide",
)

# ── Session state initialisation ─────────────────────────────────────────────
_DEFAULTS: dict = {
    "state": "upload",
    "students": [],
    "student_index": 0,
    "session_id": None,           # single Claude session threaded across all students
    "session_totals": [0.0, 0, 0, 0, 0],  # cost, in, out, cache_written, cache_read
    "accepted_grade": None,
    "ratings": {},
    "agent_log": [],              # text blocks from most recent agent call
    "agent_future": None,         # concurrent.futures.Future | None
    "next_state": None,           # state to advance to once future completes
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# One background worker — agent calls are sequential per student
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def current_student() -> dict | None:
    idx = st.session_state["student_index"]
    students = st.session_state["students"]
    return students[idx] if idx < len(students) else None


def student_slug(row: dict) -> str:
    return f"{row['student_id'].lower()}-{row['last_name'].lower()}"


# ── Background agent task ─────────────────────────────────────────────────────

def _agent_task(
    prompt: str, session_id: str | None, slug: str, pass_label: str
) -> tuple:
    """
    Runs inside a ThreadPoolExecutor worker. Creates its own asyncio event loop.
    Returns (cost, tin, tout, tcw, tcr, new_sid, log_lines).
    Must NOT touch st.session_state — caller reads results after future.done().
    """
    log: list[str] = []
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            run_agent(
                prompt,
                session_id=session_id,
                slug=slug,
                pass_label=pass_label,
                text_callback=log.append,
            )
        )
    finally:
        loop.close()
    cost, tin, tout, tcw, tcr, new_sid = result
    return cost, tin, tout, tcw, tcr, new_sid, log


def _submit_agent(
    prompt: str, slug: str, pass_label: str, next_state: str
) -> None:
    """Submit agent task to the executor; set state to the running sentinel."""
    future = _EXECUTOR.submit(
        _agent_task,
        prompt,
        st.session_state["session_id"],
        slug,
        pass_label,
    )
    st.session_state["agent_future"] = future
    st.session_state["next_state"] = next_state
    # State name encodes which pass is running so the spinner can label itself
    st.session_state["state"] = pass_label.lower().replace(" ", "") + "_running"


def _poll_future() -> None:
    """
    Called when state is *_running.  Non-blocking poll of the background future.
    • If done → unpack results into session_state, advance to next_state, rerun.
    • If running → show spinner, sleep briefly, rerun (keeps UI alive).
    Never returns normally; always exits via st.rerun().
    """
    future: concurrent.futures.Future = st.session_state["agent_future"]

    if future.done():
        exc = future.exception()
        if exc:
            st.error(f"Agent error: {exc}")
            st.session_state["agent_future"] = None
            st.session_state["state"] = "upload"
            st.rerun()

        cost, tin, tout, tcw, tcr, new_sid, log = future.result()
        totals = st.session_state["session_totals"]
        totals[0] += cost
        totals[1] += tin
        totals[2] += tout
        totals[3] += tcw
        totals[4] += tcr
        st.session_state["session_id"] = new_sid
        st.session_state["agent_log"] = log
        st.session_state["agent_future"] = None
        st.session_state["state"] = st.session_state["next_state"]
        st.rerun()

    # Still running — render spinner, sleep 0.4 s, rerun to poll again
    row = current_student()
    name = f"{row['first_name']} {row['last_name']}" if row else "student"
    running_state: str = st.session_state["state"]
    pass_label = "Pass 1" if "pass1" in running_state else "Pass 2"
    with st.spinner(f"Agent running {pass_label} for {name}…"):
        time.sleep(0.4)
    st.rerun()


def _start_pass1(row: dict) -> None:
    sid, first, last = row["student_id"], row["first_name"], row["last_name"]
    slug = student_slug(row)
    prompt = (
        f"Project root: {HARNESS_DIR}. "
        f"Pass 1. "
        f"Student: {first} {last}, student_id: {sid}, slug: {slug}. "
        f"Read the CSV row for this student from data/students.csv, calculate "
        f"their weighted average and predicted grade using python3 via bash, "
        f"and write their pending review file and log. "
        f"Follow CLAUDE.md."
    )
    _submit_agent(prompt, slug, "Pass 1", next_state="grade_gate")


def _start_pass2(row: dict, accepted_grade: str, ratings: dict) -> None:
    sid, first, last = row["student_id"], row["first_name"], row["last_name"]
    slug = student_slug(row)
    prompt = (
        f"Project root: {HARNESS_DIR}. "
        f"Pass 2. "
        f"Student: {first} {last}, student_id: {sid}, slug: {slug}. "
        f"Accepted predicted grade: {accepted_grade}. "
        f"Teacher ratings: "
        f"Effort {ratings['Effort']}/5, "
        f"Class Engagement {ratings['Class Engagement']}/5, "
        f"Quality of Work {ratings['Quality of Work']}/5. "
        f"Write the 4–5 sentence progress summary paragraph and update "
        f"the pending review file and log. "
        f"Follow CLAUDE.md."
    )
    _submit_agent(prompt, slug, "Pass 2", next_state="approve")


def _advance_to_next_student() -> None:
    """Move to next student (or complete), kick off Pass 1 in background."""
    next_idx = st.session_state["student_index"] + 1
    students = st.session_state["students"]
    st.session_state["agent_log"] = []
    if next_idx >= len(students):
        st.session_state["state"] = "complete"
        st.rerun()
    else:
        st.session_state["student_index"] = next_idx
        _start_pass1(students[next_idx])
        st.rerun()


def load_csv_from_path(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_csv_from_bytes(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode())))


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar() -> None:
    with st.sidebar:
        st.title("📋 Review Generator")
        st.caption("A-Level Business Studies · 2025–2026")
        st.divider()

        students = st.session_state["students"]
        idx = st.session_state["student_index"]
        total = len(students)
        if total:
            done = (idx + 1) if st.session_state["state"] == "complete" else idx
            st.markdown(f"**Progress** — {done}/{total} students")
            st.progress(int(done / total * 100))

        t = st.session_state["session_totals"]
        st.markdown(f"**Session cost** — :green[${t[0]:.4f}]")
        if t[1] + t[4] > 0:
            cached_pct = int(100 * t[4] / (t[1] + t[4]))
            cache_tokens = f"{t[4]:,}"
            st.caption(f"Cache hit: {cached_pct}% · {cache_tokens} tokens read")

        st.divider()
        sid = st.session_state.get("session_id")
        if sid:
            st.caption(f"Session: `{sid[:16]}…`")

        st.divider()
        if CLASS_REVIEWS.exists():
            with st.expander("📄 Class Reviews (live)", expanded=False):
                st.markdown(CLASS_REVIEWS.read_text())
        else:
            st.caption("_No approved reviews yet._")


# ── Main tabs ─────────────────────────────────────────────────────────────────

def render_tabs() -> None:
    tab_review, tab_csv, tab_class, tab_log = st.tabs(
        ["📝 Current Student", "📊 Student CSV", "📄 Class Reviews", "🔍 Agent Logs"]
    )
    with tab_review:
        render_review_tab()
    with tab_csv:
        render_csv_tab()
    with tab_class:
        render_class_reviews_tab()
    with tab_log:
        render_log_tab()


# ── Review tab ────────────────────────────────────────────────────────────────

def render_review_tab() -> None:
    state = st.session_state["state"]

    # ── Background agent running (either pass) ── poll until done ────────────
    if "running" in state:
        _poll_future()
        return

    # ── Upload / ready screen ─────────────────────────────────────────────────
    if state == "upload":
        st.header("Welcome")
        st.markdown(
            "Load your student CSV in the **Student CSV** tab, then click "
            "**Start Reviews** to begin processing students one by one."
        )
        students = st.session_state["students"]
        if students:
            st.success(f"{len(students)} students loaded.")
            if st.button("▶ Start Reviews", type="primary"):
                _start_pass1(students[0])
                st.rerun()
        else:
            st.info("Go to the **Student CSV** tab to load students first.")
        return

    # ── Complete screen ────────────────────────────────────────────────────────
    if state == "complete":
        render_complete()
        return

    # ── Per-student screens ───────────────────────────────────────────────────
    row = current_student()
    if row is None:
        st.warning("No current student — check CSV.")
        return

    slug = student_slug(row)
    idx = st.session_state["student_index"]
    total = len(st.session_state["students"])

    st.subheader(
        f"[{idx + 1}/{total}]  {row['first_name']} {row['last_name']}  "
        f"·  `{row['student_id']}`"
    )
    st.caption("A-Level Business Studies")
    st.divider()

    # ── Grade gate ───────────────────────────────────────────────────────────
    if state == "grade_gate":
        pending = REVIEWS_DIR / f"pending_{slug}.md"

        if st.session_state["agent_log"]:
            with st.expander("Agent reasoning — Pass 1", expanded=False):
                for chunk in st.session_state["agent_log"]:
                    st.markdown(f"> {chunk}")

        if pending.exists():
            st.markdown(pending.read_text())
        else:
            st.warning("Pending review not written yet — check agent reasoning above.")

        st.divider()
        st.markdown("#### ⚑ Grade Review")
        predicted = extract_grade_from_review(slug)
        default_idx = GRADES.index(predicted) if predicted in GRADES else 0
        chosen = st.selectbox(
            "Predicted grade",
            GRADES,
            index=default_idx,
            help="Agent-calculated grade. Override if needed.",
            key="grade_selectbox",
        )
        if chosen != predicted and predicted != "?":
            st.info(f"⚑ Grade overridden: **{predicted}** → **{chosen}**")

        if st.button("Confirm grade →", type="primary", key="confirm_grade"):
            st.session_state["accepted_grade"] = chosen
            st.session_state["state"] = "ratings_gate"
            st.rerun()

    # ── Ratings gate ─────────────────────────────────────────────────────────
    elif state == "ratings_gate":
        st.markdown("#### ⚑ Teacher Ratings")
        st.caption(
            "Rate this student on each dimension. "
            "These feed into the progress summary paragraph."
        )
        ratings: dict[str, int] = {}
        for dim, labels in RATING_LABELS.items():
            val = st.select_slider(
                dim,
                options=list(range(1, 6)),
                value=3,
                format_func=lambda v, l=labels: f"{v} — {l[v - 1]}",
                key=f"rating_{dim}",
            )
            ratings[dim] = val

        if st.button(
            "Submit ratings & generate summary →",
            type="primary",
            key="submit_ratings",
        ):
            st.session_state["ratings"] = ratings
            # Submit to background executor — does NOT block the main thread
            _start_pass2(row, st.session_state["accepted_grade"], ratings)
            st.rerun()

    # ── Approve gate ─────────────────────────────────────────────────────────
    elif state == "approve":
        pending = REVIEWS_DIR / f"pending_{slug}.md"

        if st.session_state["agent_log"]:
            with st.expander("Agent reasoning — Pass 2", expanded=False):
                for chunk in st.session_state["agent_log"]:
                    st.markdown(f"> {chunk}")

        if pending.exists():
            st.markdown(pending.read_text())

        st.divider()
        st.markdown("#### ⚑ Final Approval")
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "✓ Approve and file", type="primary",
                use_container_width=True, key="approve_btn",
            ):
                approved = REVIEWS_DIR / f"{slug}.md"
                if pending.exists():
                    pending.rename(approved)
                append_to_class_reviews(
                    slug,
                    row["first_name"],
                    row["last_name"],
                    st.session_state["accepted_grade"],
                    st.session_state["ratings"],
                )
                _advance_to_next_student()
        with col2:
            if st.button(
                "✗ Reject", type="secondary",
                use_container_width=True, key="reject_btn",
            ):
                _advance_to_next_student()


def render_complete() -> None:
    t = st.session_state["session_totals"]
    cached_pct = int(100 * t[4] / (t[1] + t[4])) if (t[1] + t[4]) > 0 else 0
    total = len(st.session_state["students"])
    st.success(f"✓ All {total} students processed!")
    st.markdown(
        f"| Metric | Value |\n|---|---|\n"
        f"| Total cost | **${t[0]:.4f}** |\n"
        f"| Input tokens | {t[1]:,} |\n"
        f"| Output tokens | {t[2]:,} |\n"
        f"| Cache written | {t[3]:,} |\n"
        f"| Cache read | {t[4]:,} ({cached_pct}% of input) |"
    )
    if CLASS_REVIEWS.exists():
        st.divider()
        st.markdown("### 📄 Class Reviews")
        st.markdown(CLASS_REVIEWS.read_text())


# ── CSV tab ───────────────────────────────────────────────────────────────────

def render_csv_tab() -> None:
    st.header("Student CSV")
    uploaded = st.file_uploader(
        "Upload a CSV to replace data/students.csv",
        type=["csv"],
        help=(
            "Required columns: student_id, first_name, last_name, "
            "unit1_test, unit2_test, unit3_essay, unit4_presentation, "
            "mock_exam, final_exam"
        ),
    )
    if uploaded:
        raw = uploaded.read()
        students = load_csv_from_bytes(raw)
        # Also write to disk so the agent can read it via bash
        out = HARNESS_DIR / "data" / "students.csv"
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(raw)
        st.session_state.update({
            "students": students,
            "state": "upload",
            "student_index": 0,
            "session_id": None,
            "agent_future": None,
            "next_state": None,
            "agent_log": [],
            "session_totals": [0.0, 0, 0, 0, 0],
        })
        st.success(f"Loaded {len(students)} students from uploaded file.")
    elif not st.session_state["students"]:
        if CSV_PATH.exists():
            students = load_csv_from_path(str(CSV_PATH))
            st.session_state["students"] = students
            st.info(f"Using {CSV_PATH.relative_to(HARNESS_DIR)}")
        else:
            st.warning("No CSV found. Upload one above.")
            return

    students = st.session_state["students"]
    if students:
        try:
            import pandas as pd
            df = pd.DataFrame(students)
            st.dataframe(df, use_container_width=True, hide_index=True)
        except ImportError:
            for row in students:
                st.write(row)
        st.caption(f"{len(students)} students")


# ── Class reviews tab ─────────────────────────────────────────────────────────

def render_class_reviews_tab() -> None:
    st.header("Class Reviews")
    if CLASS_REVIEWS.exists():
        content = CLASS_REVIEWS.read_text()
        st.markdown(content)
        st.divider()
        st.download_button(
            "⬇ Download class-reviews.md",
            data=content,
            file_name="class-reviews.md",
            mime="text/markdown",
        )
    else:
        st.info("No approved reviews yet. Approve students in the **Current Student** tab.")


# ── Agent logs tab ────────────────────────────────────────────────────────────

def render_log_tab() -> None:
    st.header("Agent Logs")
    log_files = sorted(LOGGING_DIR.glob("*.md")) if LOGGING_DIR.exists() else []
    if not log_files:
        st.info("No log files yet — logs appear here after processing starts.")
        return
    selected = st.selectbox(
        "Select student log",
        log_files,
        format_func=lambda p: p.stem,
    )
    if selected:
        st.markdown(selected.read_text())
        st.divider()
        st.download_button(
            f"⬇ Download {selected.name}",
            data=selected.read_text(),
            file_name=selected.name,
            mime="text/markdown",
        )


# ── Render ────────────────────────────────────────────────────────────────────
render_sidebar()
render_tabs()
