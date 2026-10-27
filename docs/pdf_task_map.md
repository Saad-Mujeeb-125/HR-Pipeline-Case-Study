# PDF task → code file map

The traceability index for the hackathon: every task written in `PeopleOps Data Hackathon HR Pipeline Case Study.pdf` (pages 5–8) and the file that executes it. File names carry the PDF reference (bullet number / qNN / checkNN). When a file's job changes, update this map **and** `docs/tasks.md`.

Conventions enforced in code:
1. Every script's docstring **quotes the PDF bullet** it implements (stage, page, rule numbers).
2. File names are named after the PDF reference: `stage2_bulletNN_*` (PDF p.5 lists 7 bullets), `q01…q10` (PDF's own file names, p.8), `stage6_checkNN_*`.

## Stage 1 — Ingest the raw data (PDF p.5)

| PDF task (quote) | Code | Status |
|---|---|---|
| "Load every file into a raw schema exactly as delivered, all columns as text" | `pipeline/ingestion/stage1_ingest.py` | ✅ all 12 files → `raw.*`, exact counts, CSV = one text row per record / JSON = one document row (`json_data`), audit metadata populated everywhere |
| "Add load metadata: _source_file, _loaded_at, _row_hash" | same | ✅ every table (incl. `raw.shifts`, which lacked the columns until this script ALTERed them in); `_row_hash` = sha256 of the row's values joined with NUL; file sha256 → `raw.load_history` |
| "Make the load idempotent … Log row counts" | same | ✅ re-run = 12 × "skip (already loaded)" (file-hash + row-count short-circuit); source-vs-DB counts checked per file into `raw.row_count_log`, FAIL aborts. pyodbc lesson (D023): no nested `BEGIN TRAN` — commit per file |

## Stage 2 — Clean and standardize (PDF p.5, bullets 1–7)

| PDF bullet (quote) | Code | Status |
|---|---|---|
| 1. "Trim text, fix casing, convert all dates to ISO YYYY-MM-DD" | `pipeline/transform/stage2/stage2_bullet01_text_dates.py` | ✅ owns the recipe in Python: trim; ALL-CAPS names → Title; dept strip→Title with acronym guard ('IT' stays 'IT', 11 rows fixed vs the old DB-only build — D022); 3 date formats → typed DATE (hard error on anything else); empty history `effective_to` → 1900-01-01 sentinel. Rebuild verified cell-identical to the DB it replaced; bullet 2 re-run after. Rename detection ISN'T here — old dept names stay as CSV text (rule 3/`dim_department.previous_name` resolves them; see `stage6` acceptance + `staging.department_mapping_issues`) |
| 2. "Deduplicate employees and keep a log of which records were merged and why" | `stage2_bullet02_employee_dedup.py` | ✅ 1,266 kept + 50 logged merges = 1,316 ✓ |
| 3. "Map device user IDs to employees. Park unmapped punches in staging.rejected_punches with a reason" | `pipeline/transform/stage2/stage2_bullet03_map_and_reject_punches.py` | ✅ 338,318 mapped · 6,962 rejected (rule 8) |
| 4. "Detect and correct the device whose clock is off. Explain how you found it" | `stage2_bullet04_device_clock.py` | ✅ DEV-SITE-01 +60 min from 2026-07-01; 45,803 punches corrected; evidence in `staging.device_clock_offsets`. Method: residuals vs median of other 3 devices, same day+shift, NIGHT excluded. Run **after** bullet 5 (needs `punches_deduped`). |
| 5. "Remove duplicate punches using the 2-minute rule" | `stage2_bullet05_punches_dedup_2min.py` | ✅ 322,143 kept · 16,175 dupes rejected (rule 9) |
| 6. "Flatten leave_requests.json into one row per request and one row per approval step" | `stage2_bullet06_leave_flatten.py` | ✅ 5,372 requests + 10,125 approval steps |
| 7. "Expand each approved leave request into one row per leave day" | `stage2_bullet07_leave_days.py` | ✅ 4,165 approved requests (rule 16) → 8,604 `staging.leave_days` (rule 17: Sundays + plant holidays removed) |

## Stage 3 — Business logic (PDF p.6)

| PDF task | Code | Status |
|---|---|---|
| "Build staging.attendance_daily: one row per employee per scheduled day … status Present/Absent/On Leave/Holiday/Weekly Off/Missing Punch" | `pipeline/transform/stage3/stage3_attendance_daily.py` | ✅ 217,584 rows (= span roster); statuses: Present 159,825 · Weekly Off 22,215 · Holiday 10,759 · Missing Punch 10,599 · On Leave 8,604 (= leave_days) · Absent 5,582; OT via rules 14–15; late/early via rule 13 |

## Stage 4 — Warehouse (PDF p.6)

| PDF task | Code | Status |
|---|---|---|
| "Star schema in warehouse schema, PK/FK enforced. dim_employee (SCD2), dim_department, dim_shift, dim_date; 4 facts" | `pipeline/warehouse/ddl/stage4_dimensions.sql` + `pipeline/warehouse/ddl/stage4_facts.sql` | ✅ dims: dim_date 365 · dim_shift 4 · dim_department 25 · dim_employee 3,686 SCD2 rows (1,266 current); facts: attendance 217,584 · leave_day 8,604 · overtime_approved 19,666 · payroll_line 53,617 — all reconciled, 0 unresolved |
| "Include an ER diagram" | `pipeline/warehouse/erd.dbml` | ✅ dbdiagram.io source (built from the actual DDL + counts) |

## Stage 5 — Business questions (PDF p.6, Q1–Q10)

One `.sql` file per question + result CSV, using the PDF's own file names (p.8):

| PDF Q | Code | Status |
|---|---|---|
| Q1 "Month-end headcount by plant and department" | `pipeline/warehouse/analytics/q01.sql` | ✅ 150 rows (25 depts × 6 months, zero-filled; rules 3+4; monthly totals 1,199→1,176 match probe) |
| Q2 attrition rate | `q02.sql` | ✅ 150 rows; separations = rule-3 last-working-day dept; avg = (start+end)/2; Jul spike 26 seps, IT 30.77% |
| Q3 absenteeism rate | `q03.sql` | ✅ 24 rows (4 plants × 6 months); expected = Present+Missing Punch+Absent (leave/Sunday/holiday excluded on both sides) |
| Q4 top 10 late arrivals | `q04.sql` | ✅ 10 rows; rule-13 rows; dept at latest late arrival; top = E10580 58 lates |
| Q5 OT computed vs approved vs paid | `q05.sql` | ✅ 150 rows (rules 14+15 vs rule 19 vs rule 20; rule-3 dept attribution per source) |
| Q6 paid OT > computed OT by >15% | `q06_ot_overpayment.sql` → `q06.sql` | ✅ 1 dept: D20 Stitching +56.24% (7,659.0 paid vs 4,902.0 computed) |
| Q7 paid with zero attendance | `q07.sql` | ✅ 21 (emp, month) rows — exactly the post-separation months of q08's 5 employees (independent cross-check) |
| Q8 paid after separation | `q08.sql` | ✅ 5 employees; worst E10471 5 months / 660,000 PKR after 2026-04-23 |
| Q9 payroll cost MoM change | `q09.sql` | ✅ 150 rows; cost per employee = ΣEARNING ÷ distinct paid employees; LAG MoM % |
| Q10 annual leave over entitlement | `q10.sql` | ✅ 20 employees; worst E10770 28 days vs 14 entitlement |

Results CSVs → next to the .sql files (`pipeline/warehouse/analytics/qXX_result.csv`), written by `run_all.py`.

## Stage 6 — Data quality checks (PDF p.7)

| PDF check | Code | Status |
|---|---|---|
| 1. Uniqueness/not-null on every PK | `stage6_check01_pk.py` (22 checks: 10 warehouse PKs incl. both surrogate + SCD2-logical + long-grain payroll, 12 staging PKs) | ✅ 21 PASS + PK05 EXPECTED (E11259 tie) |
| 2. Referential integrity fact↔dimension | `stage6_check02_fk.py` (13 fact→dim incl. double-check natural + surrogate keys, 5 staging cross-refs) | ✅ 18 PASS (0 orphans) |
| 3. Reconciliation raw = staging + rejected | `stage6_check03_reconciliation.py` (13 equations; JSON docs counted via OPENJSON array elements) | ✅ 13 PASS |
| 4. Accepted values (status, leave type, component) | `stage6_check04_accepted_values.py` (6 statuses, 3 leave types, 2 component types, 9 components, OT status) | ✅ 8 PASS |
| 5. Sanity (no negative hours, ≤16h shifts, no SCD2 overlap) | `stage6_check05_sanity.py` (+ no negative payroll, leave days in window & not Sunday) | ✅ 7 PASS |

Driver: `pipeline/quality/run_all.py` + `dq_common.py` → `quality.dq_results` (one row per check per run, run_id = GUID; status PASS/EXPECTED/FAIL/ERROR, exit code non-zero on blocking failures). 68 checks total, 0 blocking.

## Bonus (PDF p.7)

| PDF bonus | Code | Status |
|---|---|---|
| run_pipeline.py rebuilds everything, one command | `pipeline/run_pipeline.py` | ✅ 13 steps (stage1 → bullets 01,02,03,05,04,06,07 → stage3 → dims DDL → facts DDL → analytics all → DQ gate), subprocess per step, first failure stops; **293 s full run verified 25 Oct, 68 checks 0 blocking**. Required two fixes it exposed: sqlcmd needs `-C` (self-signed cert, ODBC Driver 18); `stage4_dimensions.sql` must drop the fact tables before the dims (FKs) to be re-runnable |
| Incremental 7th-month load | `pipeline/ingestion/stage1_incremental_punches.py` | ✅ loads ONLY rows whose `_row_hash` is not already in `raw.biometric_punches` (overlap deliveries = no-op by construction); verdicts → `raw.incremental_loads`; demo: 1,000 skipped + 3 new inserted, 2nd run 0, exact restore (D024) |
| Recruitment funnel | `pipeline/analytics/bonus_b3_recruitment_funnel.sql` + `.py` runner | ✅ conversion + PERCENTILE_CONT median days per stage + exits; result CSV beside the qXX files (D025) |
| Simple dashboard on warehouse tables | `pipeline/presentation/bonus_b4_dashboard.py` → `bonus_b4_dashboard.html` | ✅ dependency-free HTML (CSS div bars), reads only `warehouse.*`; OT panel flags D20 paid-vs-computed overflow like q06; ghost-pay table self-checks against q07/q08 (D026) |

## Deliverables (PDF p.7–8)

| PDF deliverable | Where | Status |
|---|---|---|
| Public GitHub repo link before code freeze | n/a (user) | ⬜ |
| README a mentor can follow to rebuild the DB | `README.md` (repo root) | ✅ 27 Oct — prereqs (`localhost\SQLEXPRESS`, ODBC 18, sqlcmd `-C`, pyodbc+sqlalchemy), explicit CREATE DATABASE step, one command `python -X utf8 pipeline/run_pipeline.py`, 13-step + row-count tables, DQ-gate explanation (real `quality.dq_results` schema), repo layout, bonus map |
| cfo_findings.md — 3 findings: number + evidence query + action | `presentation/cfo_findings.md` (repo root) | ✅ 27 Oct — F1 D20 Stitching OT +56.24% (7,659 vs 4,902 h, PKR 3,771,337 bill), F2 ghost pay 5 employees / 21 months / PKR 1,948,000 (E10471 660k), F3 20 employees over annual entitlement (E10770 28 vs 14); each with the qXX SQL and result-CSV path; one number corrected during slide QA (leave-approval gap 369→**152**, see D029) |
| slides.pdf — max 6 slides | `presentation/slides.pdf` (+ `slides.pptx`, built by `pipeline/presentation/dv4_make_slides.py`) | ✅ 27 Oct — 6 slides (title / pipeline / DQ gate / the three findings), python-pptx + PowerPoint COM→PDF, visual page-by-page verification |
