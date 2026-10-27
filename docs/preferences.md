# Code preferences — how we write code in this project

Baseline drawn from: (a) the user's direction, (b) the case study's rules, (c) choices already made in `docs/decisions.md`. You're new to this, so defaults favor **simple, human-explainable code** — anything clever is a liability at the 3-minute Q&A.

Note for the user: edit this file any time you develop a preference; keep the short "updated" note at the bottom so the date is honest.

## Languages and tools
- Python 3.14 (pandas, pyodbc, SQLAlchemy) + T-SQL on SQL Server. No Spark/cloud/BI tools — case study explicitly says they're not needed.
- Browser inside SSMS or `sqlcmd -S "localhost\SQLEXPRESS" -E -C` for quick checks; Python scripts for everything repeatable.

## Style rules
1. **Explainable beats clever.** Small classes with obvious method names, no dense one-liners. If a line can't be explained out loud in the demo, rewrite it.
1a. **OOP structure (user preference, 2026-10-25; implemented 2026-10-27, D027):** every Python pipeline file carries ONE class named like the task (`Stage1Ingest`, `Stage2Bullet07LeaveDays`, `DQCheckRunner`…); `__init__` holds paths/constants, `run()` is the only public entry point, one focused private method per logical step (`_extract`, `_transform`, `_load`, `_verify`). A thin `if __name__ == "__main__"` block at the bottom instantiates and calls `run()`. Shared behaviour lives in `pipeline/pipeline_base.py` (class `PipelineTask`: paths `data_dir`/`pipeline_dir`, `log()`, `get_connection()`; `run()` raises NotImplementedError). Notes that keep it honest: SQL/T-SQL stays in class attributes or .sql files; the Stage-6 check families keep module-level `CHECKS` aliases (their check dicts are the runner's import surface — the class is the container); a thin `main()` shim only appears where the orchestrator needs a stable subprocess entry (`run_pipeline.py`).
2. **Comments cite rule numbers.** Business logic comments reference the data-dictionary rule ("rule 9: 2-minute dedup") so correctness is traceable, not re-explained.
3. **Log row counts at every step.** The case study grades reconciliation; every script prints/records what went in, came out, and got rejected.
4. **Never mutate source data.** All fixes happen in SQL/Python code; raw and `data/` files are read-only.
5. **SQL lives in .sql files**, one question per file with CTEs and window functions where they naturally fit (Stage 5 requirement); Python only orchestrates and loads.
6. **Everything runs through `pipeline/db_connect.py`** — no ad-hoc connection strings scattered in scripts.
7. Dates are parsed/normalized once, early, to ISO `YYYY-MM-DD`, and stored typed in staging — never re-parsed mid-query.
8. **Every file's docstring quotes its PDF assignment** (stage, page, the bullet/question text in quotes, and the business-rule numbers it applies) so anyone can trace a file back to the exact PDF line without opening any doc.

## Naming conventions
- Tables/schema: SQL Server layered schemas `raw` → `staging` → `warehouse` (+ `dq_results`).
- Files: **one file per PDF task**, named by the PDF reference and ordered by it — `stage2_bulletNN_<verb>_<thing>.py`, `qNN_<topic>.sql` (the PDF's own names, p.8), `stage6_checkNN_<topic>.py`; lowercase snake_case. `docs/pdf_task_map.md` must stay in sync whenever a file changes jobs.

## To be filled (decide as you learn)
- [ ] Editor of choice for SQL (SSMS vs VS Code vs DBeaver)
- [ ] Team members + GitHub repo URL (needed for DV1 in tasks.md)
- [ ] Commit conventions (e.g. one commit per stage?)

---
*updated: 2026-10-27 (rule 1a fully implemented across every pipeline file — see D027; base class `pipeline/pipeline_base.py`; verified by a full 13-step pipeline run)*
