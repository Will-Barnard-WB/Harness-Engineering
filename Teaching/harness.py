"""
Student Review Generator — Claude Agent SDK Harness
====================================================

HARNESS ENGINEERING PRINCIPLES DEMONSTRATED:

  1. CLAUDE.md is the brain        — domain rules live in docs/, not Python
  2. Filesystem is the memory      — agent reads CSV, writes reviews + logs
  3. Bash is the tool              — agent uses python3/cat/grep, not custom tools
  4. claude-progress.txt           — structured state for long-running sessions
  5. Human gate is thin            — grade override + ratings collected, not computed

The Python here does four things only:
  - Read the student CSV to drive the per-student loop
  - Set up the environment (cwd, permissions, allowed tools)
  - Collect the teacher's grade override and three ratings between agent passes
  - Approve/reject the final review and append to the class rollup

SETUP:
  pip install claude-agent-sdk anyio python-dotenv
  export ANTHROPIC_API_KEY=your_key_here
  python harness.py
"""

import csv
import sys
from datetime import date
from pathlib import Path

import anyio
from dotenv import load_dotenv

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ── Colours ───────────────────────────────────────────────────────────────────
G, Y, R, C, DIM, BOLD, RST = (
    "\033[92m", "\033[93m", "\033[91m", "\033[96m",
    "\033[2m", "\033[1m", "\033[0m"
)

HARNESS_DIR = Path(__file__).parent
REVIEWS_DIR = HARNESS_DIR / "reviews"
LOGGING_DIR = HARNESS_DIR / "logging"
CSV_PATH    = HARNESS_DIR / "data" / "students.csv"
CLASS_REVIEWS = REVIEWS_DIR / "class-reviews.md"

GRADES = ["A*", "A", "B", "C", "D", "E", "U"]

RATING_LABELS = {
    "Effort":           ["Very poor", "Poor", "Adequate", "Good", "Exceptional"],
    "Class Engagement": ["Disengaged", "Passive", "Moderate", "Active", "Outstanding"],
    "Quality of Work":  ["Very weak", "Weak", "Adequate", "Strong", "Excellent"],
}


# ── Shared agent runner ───────────────────────────────────────────────────────

async def run_agent(
    prompt: str,
    session_id: str | None = None,
    slug: str = "",
    pass_label: str = "",
    text_callback=None,  # optional callable(str) for streaming text — used by UI
) -> tuple:
    """
    Run one agent query.  If session_id is provided the same Claude session is
    resumed so docs / history from previous turns are already in context.
    Returns (cost, in, out, cache_written, cache_read, new_session_id).
    """
    claude_md = (HARNESS_DIR / "CLAUDE.md").read_text()
    options = ClaudeAgentOptions(
        cwd=str(HARNESS_DIR),
        allowed_tools=["Bash"],
        permission_mode="acceptEdits",
        system_prompt=claude_md,
        resume=session_id,  # None = fresh session; str = continue same session
    )

    total_cost = 0.0
    total_in = total_out = total_cw = total_cr = 0
    new_session_id = session_id
    log_file = LOGGING_DIR / f"{slug}.md" if slug else None

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    text = block.text.strip()
                    if text_callback:
                        text_callback(text)
                    else:
                        print(f"{DIM}  {text}{RST}\n")
                elif isinstance(block, ToolUseBlock) and log_file:
                    # Log every tool call from Python — reliable regardless of agent self-logging
                    cmd = (
                        block.input.get("command", "") if isinstance(block.input, dict)
                        else str(block.input)
                    )
                    entry = (
                        f"\n### Tool [{pass_label}]: {block.name}\n"
                        f"```\n{cmd[:500]}\n```\n"
                    )
                    LOGGING_DIR.mkdir(exist_ok=True)
                    with log_file.open("a") as lf:
                        lf.write(entry)
        elif isinstance(message, ResultMessage):
            turn_cost = message.total_cost_usd or 0.0
            total_cost += turn_cost
            new_session_id = message.session_id or new_session_id
            if message.usage:
                total_in  += message.usage.get("input_tokens", 0)
                total_out += message.usage.get("output_tokens", 0)
                total_cw  += message.usage.get("cache_creation_input_tokens", 0)
                total_cr  += message.usage.get("cache_read_input_tokens", 0)
            print(f"{DIM}  ── Turn complete · {message.stop_reason} · turn cost ${turn_cost:.4f}{RST}")

    return total_cost, total_in, total_out, total_cw, total_cr, new_session_id


# ── Human-in-the-loop helpers ─────────────────────────────────────────────────

def pick_grade(predicted: str) -> str:
    """Show the predicted grade; offer override. Returns the accepted grade."""
    print(f"\n  {BOLD}Predicted grade: {C}{predicted}{RST}")
    while True:
        raw = input(
            f"  {BOLD}Press Enter to accept, or type grade to override "
            f"{DIM}(A* / A / B / C / D / E / U){RST}{BOLD}: {RST}"
        ).strip().upper()
        if raw == "":
            print(f"  {G}✓ Grade accepted: {predicted}{RST}")
            return predicted
        if raw in GRADES:
            print(f"  {Y}⚑ Grade overridden: {predicted} → {raw}{RST}")
            return raw
        print(f"  {R}  Invalid grade. Options: A* A B C D E U (or Enter to accept){RST}")


def collect_ratings() -> dict:
    """Present numbered menus for each teacher rating. Returns {dimension: 1-5}."""
    ratings: dict[str, int] = {}
    for dimension, labels in RATING_LABELS.items():
        print(f"\n  {BOLD}{dimension}{RST}")
        for i, label in enumerate(labels, 1):
            print(f"  {DIM}  {i}. {label}{RST}")
        while True:
            raw = input(f"  {BOLD}Select 1–5: {RST}").strip()
            if raw in ("1", "2", "3", "4", "5"):
                chosen = int(raw)
                print(f"  {G}✓ {dimension}: {chosen} — {labels[chosen - 1]}{RST}")
                ratings[dimension] = chosen
                break
            print(f"  {R}  Please enter a number from 1 to 5.{RST}")
    return ratings


def extract_grade_from_review(slug: str) -> str:
    """Parse the predicted grade from the pending review file."""
    review_file = REVIEWS_DIR / f"pending_{slug}.md"
    if not review_file.exists():
        return "?"
    for line in review_file.read_text().splitlines():
        # Matches lines like: **A**** — on track for...  or **B** — on track for...
        if line.startswith("**") and any(f"**{g}**" in line for g in GRADES):
            for g in GRADES:
                if f"**{g}**" in line:
                    return g
    return "?"


def append_to_class_reviews(
    slug: str,
    first: str,
    last: str,
    grade: str,
    ratings: dict,
) -> None:
    """Append the approved student section to the class rollup markdown."""
    review_file = REVIEWS_DIR / f"{slug}.md"
    if not review_file.exists():
        print(f"  {R}  Warning: approved file not found — skipping class-reviews append{RST}")
        return

    content = review_file.read_text()

    # Extract the progress summary paragraph (text under ## Progress Summary)
    paragraph = ""
    in_summary = False
    for line in content.splitlines():
        if line.strip() == "## Progress Summary":
            in_summary = True
            continue
        if in_summary:
            if line.startswith("---") or line.startswith("*Review status"):
                break
            if line.strip():
                paragraph += line.strip() + " "
    paragraph = paragraph.strip() or "_Summary not yet written._"

    # Extract weighted average from review
    weighted = ""
    for line in content.splitlines():
        if "Weighted average:" in line and "%" in line:
            # e.g. **Weighted average:** 91.05%
            part = line.split("Weighted average:")[-1].strip().strip("*").strip()
            weighted = part
            break

    effort_label  = RATING_LABELS["Effort"][ratings["Effort"] - 1]
    engage_label  = RATING_LABELS["Class Engagement"][ratings["Class Engagement"] - 1]
    quality_label = RATING_LABELS["Quality of Work"][ratings["Quality of Work"] - 1]

    section = (
        f"## {first} {last} — {grade}\n\n"
        f"> Weighted average: {weighted}  \n"
        f"> Effort: {ratings['Effort']}/5 ({effort_label}) · "
        f"Engagement: {ratings['Class Engagement']}/5 ({engage_label}) · "
        f"Quality: {ratings['Quality of Work']}/5 ({quality_label})\n\n"
        f"{paragraph}\n\n"
        f"---\n\n"
    )

    if not CLASS_REVIEWS.exists():
        CLASS_REVIEWS.write_text(
            f"# Class Reviews — A-Level Business Studies\n\n"
            f"**Academic Year:** 2025–2026  \n"
            f"**Generated:** {date.today().isoformat()}  \n"
            f"**Subject teacher:** _(approved reviews shown below)_\n\n"
            f"---\n\n"
        )

    with CLASS_REVIEWS.open("a") as f:
        f.write(section)


# ── Per-student flow ──────────────────────────────────────────────────────────

async def process_student(
    row: dict,
    index: int,
    total: int,
    session_totals: list,
    session_id: str | None,
) -> str | None:
    """Process one student (both passes). Returns the updated session_id."""
    sid   = row["student_id"]
    first = row["first_name"]
    last  = row["last_name"]
    slug  = f"{sid.lower()}-{last.lower()}"

    print(f"\n{BOLD}{C}{'═' * 56}{RST}")
    print(f"{BOLD}{C}  [{index}/{total}]  {first} {last}  ({sid}){RST}")
    print(f"{BOLD}{C}{'═' * 56}{RST}\n")

    # ── Pass 1: calculate grade ───────────────────────────────────────────────
    print(f"{BOLD}  Pass 1 — Grade Calculation{RST}\n")

    pass1_prompt = (
        f"Project root: {HARNESS_DIR}. "
        f"Pass 1. "
        f"Student: {first} {last}, student_id: {sid}, slug: {slug}. "
        f"Read the CSV row for this student from data/students.csv, calculate "
        f"their weighted average and predicted grade using python3 via bash, "
        f"and write their pending review file and log. "
        f"Follow CLAUDE.md."
    )

    cost, tin, tout, tcw, tcr, session_id = await run_agent(
        pass1_prompt, session_id=session_id, slug=slug, pass_label="Pass 1"
    )
    session_totals[0] += cost
    session_totals[1] += tin
    session_totals[2] += tout
    session_totals[3] += tcw
    session_totals[4] += tcr

    # Show what the agent wrote
    pending = REVIEWS_DIR / f"pending_{slug}.md"
    if pending.exists():
        print(f"\n{'─' * 56}")
        print(pending.read_text())
        print(f"{'─' * 56}")
    else:
        print(f"  {R}  Warning: pending review not found — {pending}{RST}")

    # ── Human gate 1: grade override ─────────────────────────────────────────
    print(f"\n{BOLD}{Y}  ⚑  GRADE REVIEW — {first} {last}{RST}")
    predicted     = extract_grade_from_review(slug)
    accepted_grade = pick_grade(predicted)

    # ── Human gate 2: teacher ratings ────────────────────────────────────────
    print(f"\n{BOLD}{Y}  ⚑  TEACHER RATINGS — {first} {last}{RST}")
    ratings = collect_ratings()

    # ── Pass 2: write summary paragraph ──────────────────────────────────────
    print(f"\n{BOLD}  Pass 2 — Progress Summary{RST}\n")

    pass2_prompt = (
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

    cost, tin, tout, tcw, tcr, session_id = await run_agent(
        pass2_prompt, session_id=session_id, slug=slug, pass_label="Pass 2"
    )
    session_totals[0] += cost
    session_totals[1] += tin
    session_totals[2] += tout
    session_totals[3] += tcw
    session_totals[4] += tcr

    # Show the completed review
    if pending.exists():
        print(f"\n{'─' * 56}")
        print(pending.read_text())
        print(f"{'─' * 56}")

    # ── Human gate 3: approve / reject ────────────────────────────────────────
    print(f"\n{BOLD}{Y}  ⚑  FINAL APPROVAL — {first} {last}{RST}")
    while True:
        choice = input(
            f"\n  {BOLD}Approve and file review? [y/n]: {RST}"
        ).strip().lower()
        if choice == "y":
            approved = REVIEWS_DIR / f"{slug}.md"
            pending.rename(approved)
            append_to_class_reviews(slug, first, last, accepted_grade, ratings)
            print(f"\n  {G}✓ Filed: {approved.name}{RST}")
            print(f"  {G}✓ Appended to class-reviews.md{RST}")
            break
        elif choice == "n":
            print(f"\n  {R}✗ Rejected — not filed.{RST}")
            break
        else:
            print("  Please enter y or n.")

    return session_id  # pass the live session forward to the next student


# ── Entry point ───────────────────────────────────────────────────────────────

async def run() -> None:
    if not CSV_PATH.exists():
        print(f"{R}Student CSV not found: {CSV_PATH}{RST}")
        sys.exit(1)

    REVIEWS_DIR.mkdir(exist_ok=True)
    LOGGING_DIR.mkdir(exist_ok=True)

    with CSV_PATH.open() as f:
        students = list(csv.DictReader(f))

    total = len(students)

    print(f"\n{BOLD}{C}{'═' * 56}{RST}")
    print(f"{BOLD}{C}  Student Review Generator — A-Level Business Studies{RST}")
    print(f"{BOLD}{C}{'═' * 56}{RST}")
    print(f"\n{DIM}  Students : {total}")
    print(f"  CSV      : {CSV_PATH.relative_to(HARNESS_DIR)}")
    print(f"  Harness  : {HARNESS_DIR}")
    print(f"  Tools    : Bash (python3, cat, grep, date){RST}\n")

    # Mutable accumulator passed into each student call
    session_totals = [0.0, 0, 0, 0, 0]  # cost, in, out, cache_w, cache_r
    session_id: str | None = None         # one Claude session for all students

    for i, row in enumerate(students, 1):
        session_id = await process_student(row, i, total, session_totals, session_id)

    # ── Session summary ───────────────────────────────────────────────────────
    cost, tin, tout, tcw, tcr = session_totals
    cached_pct = (100 * tcr / (tin + tcr)) if (tin + tcr) > 0 else 0

    print(f"\n{BOLD}  {'─' * 52}{RST}")
    print(f"{BOLD}  Session complete — {total} students processed{RST}")
    print(f"{BOLD}  Total cost     {RST}{C}${cost:.4f}{RST}")
    print(f"{DIM}  Input tokens   {tin:,}")
    print(f"  Output tokens  {tout:,}")
    print(f"  Cache written  {tcw:,} tokens")
    print(f"  Cache read     {tcr:,} tokens  ({cached_pct:.0f}% of input served from cache){RST}")
    print(f"{BOLD}  {'─' * 52}{RST}\n")

    if CLASS_REVIEWS.exists():
        print(f"  {G}Class review written to: {CLASS_REVIEWS.relative_to(HARNESS_DIR)}{RST}")
        print(f"  {DIM}Open in VS Code and press Cmd+Shift+V to preview{RST}\n")


def main() -> None:
    anyio.run(run)


if __name__ == "__main__":
    main()
