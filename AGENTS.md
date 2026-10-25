# AGENTS.md — Indus Weave Textiles HR Pipeline (PeopleOps Data Hackathon)

## What this workspace is
- Dataset-only workspace for the PeopleOps Data Hackathon: six months (1 Apr – 30 Sep 2026) of synthetic HR exports for fictional Indus Weave Textiles, plus the case study PDF. **No pipeline code exists yet** — the task is to build a Python + SQL pipeline from scratch.
- Read both sources of truth before touching data:
  - `data/data_dictionary.md` — the 21 business rules, "the law" for the case study. Where a rule and the data disagree, **the rule wins** (ignore `employment_history.effective_to`, ignore leave `days_requested`).
  - `PeopleOps Data Hackathon HR Pipeline Case Study.pdf` — 6 stages, prescribed repo layout, the 10 SQL questions, DQ requirements, judging rubric, timeline. Some models can't read PDFs; extract text with:
    `python -X utf8 -c "from pypdf import PdfReader; [print(p.extract_text()) for p in PdfReader('PeopleOps Data Hackathon HR Pipeline Case Study.pdf').pages]"`

## Workspace layout (agreed decisions)
- Canonical raw data is **`data/`**. Identical copies also sit at repo root — spurious duplicates; do not load from them.
- Pipeline code goes in **`pipeline/`**, organized as the PDF tree: `ingestion/`, `transform/`, `warehouse/ddl/`, `analytics/` (q01…q10 .sql + one result CSV each), `quality/`, `presentation/`.
- Target database: **SQL Server (SSMS), accessed via JDBC**. No psql/PostgreSQL on this machine. Connection details are not recorded in the repo — ask the user for the server/connection string.

## Dataset facts (verified)
- Row counts — reconciliation targets (`raw = staging + rejected`): employees 1,316 · employment_history 3,686 · departments 25 · shift_roster 36,402 · device_mapping 1,260 · biometric_punches 345,280 · holidays 12 · overtime_requests 22,098 · payroll_lines 53,617 · applications 3,835 · leave_requests.json 5,372 requests · shifts.json 4.
- `employees.csv` mixes three date formats: `YYYY-MM-DD` (791), `DD/MM/YYYY` (322), `DD-Mon-YYYY` (203); also 50 duplicate `emp_id` rows (1,316 rows → 1,266 distinct).
- NIGHT shift crosses midnight: 30 Sep night-shift check-outs punch on 1 Oct. A night punch belongs to the shift **start** date (rule 7), not the calendar date.
- `payroll_lines.csv` is long format (one row per emp/month/component); paid OT hours = `units` on the `OVERTIME` line. Punch data has no in/out flag — first punch = check-in, last = check-out.

## Environment gotchas
- Windows + PowerShell. Available: Python 3.14, Node 24, git. Not installed: PostgreSQL.
- Prefix Python one-liners with `python -X utf8`; otherwise printing Unicode (e.g. box-drawing chars) raises cp1252 `UnicodeEncodeError`.

## Hard rules that drive scoring
- **Never edit the raw export files** — every fix must be in code. Stage 1 load must be idempotent (all columns as text + `_source_file`, `_loaded_at`, `_row_hash`).
- Correct answers are the biggest grade (25/100, checked against a hidden answer key) — exactness over tooling. Every planted data issue must be fixed in code *and documented* (employee merge log, `staging.rejected_punches` with reason, faulty-device explanation).
- Team must be able to explain every line in Q&A — prefer plain, readable SQL/Python a human can defend.
