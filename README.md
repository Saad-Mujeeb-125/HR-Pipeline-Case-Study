# Indus Weave Textiles — HR Data Pipeline

PeopleOps Data Hackathon submission: a Python + SQL pipeline that ingests **12 messy HCM
exports** (Apr–Sep 2026, 6 months) into a local **SQL Server** database, cleans and
reconciles them against the case study's 21 business rules, models a **star-schema
warehouse**, answers the **10 business questions**, and gates every load with **68 automated
data-quality checks**.

Built from the case-study PDF and `data/data_dictionary.md` (the 21 business rules — where a
rule and the data disagree, the rule wins). Raw exports are **never edited**: every fix lives
in code, and every planted data issue is documented with a query trail.

---

## 1. Quick start (clean machine)

### Prerequisites

| Software | Version used | Why |
|---|---|---|
| **SQL Server 2025 Express** (or 2019+) | local named instance `localhost\SQLEXPRESS` | stores all three layers (`raw` / `staging` / `warehouse`) |
| **ODBC Driver 18 for SQL Server** | 18 | Python↔SQL Server connectivity |
| **Python** | 3.14 (any 3.10+ works) | pipeline code |
| **pip packages** | `pyodbc`, `sqlalchemy` | see below |

Windows Authentication throughout — **no passwords anywhere**. Quick install check:

```powershell
# Python packages (pandas is pulled in by sqlalchemy tooling if ever needed)
python -m pip install pyodbc sqlalchemy

# sqlcmd ships with SQL Server; verify it + the instance is up
sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q "SELECT @@VERSION"
# (the -C flag trusts the Express instance's self-signed certificate)

# verify the ODBC driver is installed
python -c "import pyodbc; print('\n'.join(d for d in pyodbc.drivers() if 'SQL Server' in d))"
```

### Step 1 — create the database

`run_pipeline.py` does **not** create the database (it connects to it). One command:

```powershell
sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q "IF DB_ID('IndusWeaveHR') IS NULL CREATE DATABASE IndusWeaveHR"
```

### Step 2 — run the whole pipeline with ONE command

From the repo root:

```powershell
python -X utf8 pipeline/run_pipeline.py
```

(`-X utf8` keeps console output UTF-8; on other OSes it's harmless. `sqlcmd` must be on PATH
— Stage 4's DDL runs through it.)

That single script runs **13 steps in dependency order**, each a subprocess that must exit 0
before the next starts (first failure stops the run):

| # | Step | What it does |
|---|---|---|
| 1 | Stage 1 ingestion | loads all 12 files into `raw.*`, columns as text + provenance columns (`_source_file`, `_loaded_at`, `_row_hash`); **idempotent** — already-loaded files are skipped |
| 2–8 | Stage 2 bullets 1–7 | text/casing/date normalisation · employee dedup (1,316→1,266 + 50-row merge log) · punch mapping + rejections · 2-minute-rule dedup · faulty-device clock fix · leave-JSON flattening · leave-day expansion |
| 9 | Stage 3 | `staging.attendance_daily` — one attendance row per employment day, status logic (rule 12) + window rule for night shifts |
| 10–11 | Stage 4 DDL | star schema: dimensions then facts (drop/recreate — safe to re-run) |
| 12 | Stage 5 | the 10 question queries `q01…q10` → one CSV each |
| 13 | Stage 6 | 68 automated checks → `quality.dq_results` table (**acts as a gate**: any FAIL/ERROR aborts the pipeline) |

Runtime: **≈ 5 minutes** end-to-end on a laptop. The expected finale:

```
PIPELINE OK — all 13 steps succeeded ...
run_id <guid>: 68 checks, 0 blocking -> quality.dq_results
```

---

## 2. What gets built (row counts you can verify)

```sql
-- raw layer (loaded exactly as delivered)
SELECT COUNT(*) FROM raw.employees;             -- 1,316
SELECT COUNT(*) FROM raw.biometric_punches;     -- 345,280
-- ... (all 12 files, exact source row counts)
```

| Table | Rows | Layer |
|---|---|---|
| `staging.employees_final` | 1,266 | deduped (rule 1) + `staging.employee_dedup_log` 50 |
| `staging.punches_deduped` | 322,143 | + `staging.rejected_punches` 23,137 (each with a reason) |
| `staging.attendance_daily` | 217,584 | one row per employment day |
| `staging.leave_days` | 8,604 | expanded from 4,165 approved requests |
| `warehouse.dim_date` / `dim_shift` / `dim_department` | 365 / 4 / 25 | conformance dims |
| `warehouse.dim_employee` | 3,686 | SCD2 from employment history (1,266 current) |
| `warehouse.fact_attendance_daily` | 217,584 | fact table |
| `warehouse.fact_leave_day` | 8,604 | fact table |
| `warehouse.fact_overtime_approved` | 19,666 | fact table |
| `warehouse.fact_payroll_line` | 53,617 | long-format payroll |

Reconciliation identity enforced by checks: **raw rows = cleaned rows + rejected rows**, e.g.
`345,280 = 322,143 + 23,137` punches and `1,316 = 1,266 + 50` employees.

---

## 3. Repository layout

```
├── README.md                          ← you are here
├── data/                              ← CANONICAL raw exports (never modified)
│   └── data_dictionary.md             ← the 21 business rules ("the law")
├── PeopleOps Data Hackathon HR Pipeline Case Study.pdf
├── docs/                              ← project memory (kept current)
│   ├── decisions.md                   ← why every choice was made (append-only log)
│   ├── tasks.md                       ← stage-by-stage tracker with findings
│   ├── preferences.md                 ← coding conventions
│   └── pdf_task_map.md               ← which code file executes which PDF task
└── pipeline/                          ← all code, one file per PDF task
    ├── run_pipeline.py                ← BONUS B1: the single end-to-end script
    ├── db_connect.py                  ← reviewed connection helper (self-tests alone)
    ├── pipeline_base.py               ← shared PipelineTask base class
    ├── ingestion/
    │   ├── stage1_ingest.py           ← Stage 1: raw load (idempotent, provenance columns)
    │   └── stage1_incremental_punches.py  ← BONUS B2: daily incremental punch load demo
    ├── transform/
    │   ├── stage2/stage2_bullet01..07_*.py   ← Stage 2: the seven cleaning bullets
    │   └── stage3/stage3_attendance_daily.py ← Stage 3: daily attendance fact logic
    ├── warehouse/
    │   ├── ddl/stage4_dimensions.sql  ← Stage 4: dimension DDL (single file per family)
    │   ├── ddl/stage4_facts.sql       ← Stage 4: fact DDL + loader statements
    │   ├── erd.dbml                   ← ER diagram (paste into dbdiagram.io)
    │   └── analytics/q01..q10.sql     ← Stage 5: the ten answers (+ _result.csv each)
    ├── analytics/
    │   └── bonus_b3_recruitment_funnel.py    ← BONUS B3: recruitment funnel
    ├── quality/
    │   ├── dq_common.py + run_all.py  ← check runner → quality.dq_results
    │   └── stage6_check01..05_*.py    ← 5 check families (68 checks)
    └── presentation/
        ├── bonus_b4_dashboard.py     ← BONUS B4 → self-contained bonus_b4_dashboard.html
        └── cfo_findings.md           ← DV3: top-3 findings for the CFO
```

The exact PDF bullet ↔ code file mapping is in **`docs/pdf_task_map.md`**. Every code file's
docstring quotes the PDF bullet (and rule numbers) it implements.

**Conventions**: every Python file carries ONE task-named class with `run()` as its sole
public entry; SQL lives in class attributes or `.sql` files. Anything important is logged
with row counts so every step can be defended in Q&A.

---

## 4. The answers (Stage 5)

`pipeline/warehouse/analytics/q01.sql … q10.sql`, each with its result saved next to it
(`q01_result.csv`, …). Re-run any single one:

```powershell
python -X utf8 pipeline/warehouse/analytics/run_all.py q06     # or: all
```

Headline findings (full story + evidence queries + recommended actions in
**`presentation/cfo_findings.md`**):

- **Q6** — D20 Stitching paid **+56.24%** overtime vs computed hours (7,659 paid vs 4,902 h; PKR 3.77M paid OT).
- **Q7/Q8** — **ghost pay**: 5 employees, 21 paid months after separation, PKR 1,948,000 (E10471 worst: 5 months / PKR 660,000).
- **Q10** — **20 employees** exceeded their full-year annual entitlement in six months.

---

## 5. Data-quality gate (Stage 6)

`pipeline/quality/` runs 5 check families, all recorded in `quality.dq_results`

- **PK** — uniqueness + not-null on every key (22 checks)
- **FK** — every fact row finds its dimension row, natural + surrogate keys (18)
- **REC** — raw = cleaned + rejected reconciliation for every table, including
  JSON-document OPENJSON element counts (13)
- **AV** — accepted-value whitelists (attendance status, leave type, pay components) (8)
- **SA** — business sanity: no negative hours, no shift > 16 h, no overlapping SCD2 ranges (7)

Latest run: **68 checks, 0 blocking** — 67 PASS + 1 documented EXPECTED
(`PK05`: one zero-length SCD2 tie for E11259, a planted source quirk, magnitude 1).
The runner exits non-zero when anything fails/ERRORs, so `run_pipeline.py` treats
Stage 6 as a real gate. Inspect:

```sql
SELECT check_id, check_name, target_object, status, rows_checked, rows_failed, message
FROM quality.dq_results WHERE run_id = (SELECT MAX(run_id) FROM quality.dq_results)
ORDER BY check_id;
```

---

## 6. Bonus deliverables

| Task | Where |
|---|---|
| **B1** single end-to-end script | `pipeline/run_pipeline.py` (this is the whole build) |
| **B2** incremental loads | `pipeline/ingestion/stage1_incremental_punches.py` (hash-based skip demo) |
| **B3** recruitment funnel | `pipeline/analytics/bonus_b3_recruitment_funnel.py` (+ result CSV) |
| **B4** dashboard | `pipeline/presentation/bonus_b4_dashboard.py` → `bonus_b4_dashboard.html` (self-contained; warehouse-only; flags the D20 overpayment in red) |

---

## 7. Notes & gotchas

- **Never edit `data/`** — every fix is in code, and checks verify this by reconciling raw counts.
- Everything is **idempotent**; re-running `run_pipeline.py` is always safe.
- NIGHT shift crosses midnight: a punch belongs to the shift **start** date (rule 7), which is
  why Stage 3 uses a window rule instead of the calendar date.
- `data/` also has byte-identical copies at repo root — the pipeline loads **only from `data/`**.
- `python -X utf8` is required on Windows consoles for Unicode log output.
