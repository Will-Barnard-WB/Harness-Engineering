"""
VAT Receipt Analyser — Claude Agent SDK Harness
================================================

HARNESS ENGINEERING PRINCIPLES DEMONSTRATED:

  1. CLAUDE.md is the brain        — domain rules live in docs/, not Python
  2. Filesystem is the memory      — agent reads receipts, writes ledger files
  3. Bash is the tool              — agent uses grep/cat/ls, not custom tools
  4. claude-progress.txt           — structured state for long-running sessions
  5. Human gate is thin            — we approve/reject output files, not dicts

The Python here does three things only:
  - Set up the environment (cwd, permissions, allowed tools)
  - Stream and display agent messages
  - Ask for human approval before renaming pending → approved

SETUP:
  pip install claude-agent-sdk anyio
  export ANTHROPIC_API_KEY=your_key_here
  python harness.py receipts/receipt-001.txt
"""

import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

load_dotenv()

# ── Colours ───────────────────────────────────────────────────────────────────
G, Y, R, C, DIM, BOLD, RST = (
    "\033[92m", "\033[93m", "\033[91m", "\033[96m",
    "\033[2m", "\033[1m", "\033[0m"
)

HARNESS_DIR = Path(__file__).parent


def build_prompt(receipt_path: Path) -> str:
    """
    The prompt is just a pointer to a file.
    The agent reads CLAUDE.md and the docs itself — that's the harness.
    """
    return f"Analyse the receipt at {receipt_path}. Follow CLAUDE.md."


async def run(receipt_path: Path) -> None:
    print(f"\n{BOLD}{C}{'═' * 56}{RST}")
    print(f"{BOLD}{C}  VAT Compliance Agent — Harness Engineering Demo{RST}")
    print(f"{BOLD}{C}{'═' * 56}{RST}")
    print(f"\n{DIM}  Receipt : {receipt_path}")
    print(f"  Harness : {HARNESS_DIR}")
    print(f"  Tools   : Bash (grep, cat, ls, python3){RST}\n")

    options = ClaudeAgentOptions(
        # cwd tells the agent where the filesystem lives
        cwd=str(HARNESS_DIR),

        # Bash is all you need — the agent uses Unix primitives
        # to read files, write outputs, and verify its own work
        allowed_tools=["Bash"],

        # acceptEdits lets the agent write ledger files autonomously
        # In production you might use "default" (manual approval per action)
        permission_mode="acceptEdits",

        # No system_prompt here — CLAUDE.md in the cwd IS the system prompt
        # That's the harness engineering pattern: docs over code

        # Prompt caching is automatic on claude-3.5+ — no beta header needed.
        # cache_creation_input_tokens / cache_read_input_tokens will appear in
        # ResultMessage.usage whenever the model writes or reads from its cache.
    )

    # ── Accumulators for cost + cache stats across all turns ────────────────
    total_cost_usd = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation_tokens = 0
    total_cache_read_tokens = 0

    # ── Agent loop ────────────────────────────────────────────────────────────
    async for message in query(
        prompt=build_prompt(receipt_path),
        options=options,
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    # Stream agent's reasoning to terminal
                    print(f"{DIM}  {block.text.strip()}{RST}\n")

        elif isinstance(message, ResultMessage):
            turn_cost = message.total_cost_usd or 0.0
            total_cost_usd += turn_cost
            if message.usage:
                total_input_tokens         += message.usage.get("input_tokens", 0)
                total_output_tokens        += message.usage.get("output_tokens", 0)
                total_cache_creation_tokens += message.usage.get("cache_creation_input_tokens", 0)
                total_cache_read_tokens     += message.usage.get("cache_read_input_tokens", 0)
            print(f"\n{DIM}  ── Turn complete · {message.stop_reason} · turn cost ${turn_cost:.4f}{RST}")

    # ── Cost & cache summary ──────────────────────────────────────────────────
    cached_pct = (
        100 * total_cache_read_tokens / (total_input_tokens + total_cache_read_tokens)
        if (total_input_tokens + total_cache_read_tokens) > 0
        else 0
    )
    print(f"\n{BOLD}  {'─' * 52}{RST}")
    print(f"{BOLD}  Session cost   {RST}{C}${total_cost_usd:.4f}{RST}")
    print(f"{DIM}  Input tokens   {total_input_tokens:,}")
    print(f"  Output tokens  {total_output_tokens:,}")
    print(f"  Cache written  {total_cache_creation_tokens:,} tokens")
    print(f"  Cache read     {total_cache_read_tokens:,} tokens  ({cached_pct:.0f}% of input served from cache){RST}")
    print(f"{BOLD}  {'─' * 52}{RST}\n")

    # ── Human-in-the-loop gate ────────────────────────────────────────────────
    # The agent wrote files to ledger/ — we review those files, not Python dicts
    pending = sorted(HARNESS_DIR.glob("ledger/*.md"))

    if not pending:
        print(f"\n{R}  No ledger files written. Check the receipt or agent output.{RST}")
        return

    print(f"\n{BOLD}{Y}  ⚑  HUMAN REVIEW REQUIRED{RST}")

    for md_file in pending:
        print(f"\n{'─' * 56}")
        print(f"{C}  {md_file.name}{RST}\n")
        print(md_file.read_text())
        print(f"{'─' * 56}")

        while True:
            choice = input(f"\n  {BOLD}Approve and file? [y/n]: {RST}").strip().lower()
            if choice == "y":
                # Rename: pending → approved (simple state machine via filename)
                approved = md_file.with_name(md_file.name.replace("pending_", ""))
                md_file.rename(approved)
                # Also approve the matching JSON
                json_file = md_file.with_suffix(".json")
                if json_file.exists():
                    import json
                    data = json.loads(json_file.read_text())
                    data["status"] = "approved"
                    json_file.write_text(json.dumps(data, indent=2))
                print(f"\n{G}  ✓ Filed: {approved.name}{RST}")
                break
            elif choice == "n":
                print(f"\n{R}  ✗ Rejected — not filed.{RST}")
                break
            else:
                print("  Please enter y or n.")


def main() -> None:
    if len(sys.argv) < 2:
        # Default to demo receipt
        receipt = HARNESS_DIR / "receipts" / "receipt-001.txt"
        print(f"{DIM}No receipt specified — using {receipt}{RST}")
    else:
        receipt = Path(sys.argv[1])

    if not receipt.exists():
        print(f"{R}Receipt not found: {receipt}{RST}")
        sys.exit(1)

    anyio.run(run, receipt)


if __name__ == "__main__":
    main()