# Output Schema — Student Reviews

Every student must produce two outputs, written via bash.

---

## 1. Pending Review: `reviews/pending_<slug>.md`

Written after Pass 1 (grade calculation) and updated after Pass 2 (summary paragraph).

The slug is `<student_id>-<lowercase-last-name>`, e.g. `s001-harrison`.

### Full file format

```
# Student Review — [First Name] [Last Name]

**Student ID:** [student_id]
**Subject:** A-Level Business Studies
**Academic Year:** 2025–2026
**Date:** [today's date, YYYY-MM-DD]

---

## Predicted Grade

**[GRADE]** — [grade commentary from feedback-guidelines.md]
**Weighted average:** [XX.XX]%

## Assignment Breakdown

| Component            | Score | Weight | Weighted |
|----------------------|-------|--------|----------|
| Unit 1 Test          | XX%   | 10%    | X.XX     |
| Unit 2 Test          | XX%   | 10%    | X.XX     |
| Unit 3 Essay         | XX%   | 15%    | X.XX     |
| Unit 4 Presentation  | XX%   | 15%    | X.XX     |
| Mock Exam            | XX%   | 20%    | X.XX     |
| Final Exam           | XX%   | 30%    | X.XX     |
| **Total**            |       |        | **XX.XX** |

## Teacher Ratings

| Dimension         | Rating |
|-------------------|--------|
| Effort            | [1–5]  |
| Class Engagement  | [1–5]  |
| Quality of Work   | [1–5]  |

## Progress Summary

[4–5 sentence paragraph written by agent in Pass 2]

---

*Review status: pending_approval*
```

### Rules

- Write the file after Pass 1 with the grade section and assignment breakdown complete
- Leave the Teacher Ratings table as `[awaiting teacher input]` after Pass 1
- Update the file after Pass 2: fill in the ratings table and the progress summary paragraph
- After approval, the harness renames the file (removes `pending_` prefix)

---

## 2. Log File: `logging/<slug>.md`

One file per student. The agent appends timestamped entries using bash.

### Entry format

```
## [YYYY-MM-DD HH:MM] Pass 1 — Grade Calculation

- Read CSV row for [Name] (student_id: [id])
- Applied weights from docs/grade-calculation.md
- Calculated weighted average: XX.XX%
- Derived grade: [GRADE]
- Wrote reviews/pending_<slug>.md
- Verified output with cat

## [YYYY-MM-DD HH:MM] Pass 2 — Summary Paragraph

- Received teacher ratings: Effort=[n], Engagement=[n], Quality=[n]
- Read docs/progress-summary.md and docs/feedback-guidelines.md
- Wrote 4-sentence summary paragraph for [Name]
- Updated reviews/pending_<slug>.md with ratings and paragraph
- Verified output with cat
- Final status: [approved / rejected] (set by harness after human gate)
```

### Rules

- Always use `date` via bash to get the current timestamp
- Append — never overwrite the log file
- Record what documents were consulted and why
- Record the exact weighted average and derived grade
- Keep entries factual and concise — this is an audit trail, not reasoning

---

## 3. Class Review Rollup: `reviews/class-reviews.md`

Built incrementally. Each approved student is appended to this file by the harness.

### Per-student section format

```markdown
## [First Name] [Last Name] — [GRADE]

> Weighted average: XX.XX% | Effort: [n]/5 | Engagement: [n]/5 | Quality: [n]/5

[Progress summary paragraph]

---
```

This file is the deliverable — it should render cleanly in any Markdown viewer.
