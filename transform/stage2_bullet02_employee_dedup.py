"""STAGE 2, bullet 2 of the case-study PDF (p.5):
    "Deduplicate employees and keep a log of which records were merged and why."
Business rule: rule 1 — "employees.csv may contain the same emp_id more than
once. Keep the row with the latest updated_at."

What it builds:
  staging.employees_final    one row per emp_id (rule 1: keep latest updated_at)
  staging.employee_dedup_log One row per MERGED duplicate: how many rows the
                             employee had, which updated_at was kept vs dropped.

The rebuild starts from staging.employees_cleaned (the text-cleaned employees).
Rule 1's order is text-safe here because updated_at is exported ISO
('2026-05-07 18:42:00' sorts chronologically as text, but we cast anyway).

Run AFTER the employees cleaning (stages 1-2 text/date fixes), anywhere before
Stage 3. Idempotent: tables are rebuilt every run.
    python -X utf8 pipeline/transform/stage2/stage2_bullet02_employee_dedup.py
"""
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage2Bullet02EmployeeDedup(PipelineTask):
    """Stage 2 bullet 2 — rule 1 dedup + merge log via SQL rebuild."""

    SQL_EMPS_READY = """
    SELECT COUNT(*) FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = 'staging' AND t.name = 'employees_cleaned'
    """

    SQL_TIE_CHECK = """
    -- deterministic rebuild requires no (emp_id, updated_at) ties among duplicates
    SELECT COUNT(*) FROM (
        SELECT emp_id, updated_at FROM staging.employees_cleaned
        GROUP BY emp_id, updated_at HAVING COUNT(*) > 1) t
    """

    SQL_REBUILD = """
    IF OBJECT_ID('staging.employees_final') IS NOT NULL DROP TABLE staging.employees_final;
    IF OBJECT_ID('staging.employee_dedup_log') IS NOT NULL DROP TABLE staging.employee_dedup_log;

    WITH ranked AS (
        SELECT s.*,
               ROW_NUMBER() OVER (PARTITION BY s.emp_id
                                  ORDER BY s.updated_at DESC) AS keep_rank   -- rule 1
        FROM staging.employees_cleaned s
    )
    SELECT ranked_col.*, keep_rank AS rn
    INTO staging.employees_final
    FROM ranked ranked_col
    WHERE ranked_col.keep_rank = 1;   -- rule 1: ONE row per emp_id (kept the latest updated_at)

    -- one row per emp_id with more than one record = the merge log
    SELECT q.emp_id,
           q.group_rows                            AS merged_rows,
           q.kept_updated_at,
           q.dropped_updated_at,
           CAST('rule 1: keep the row with the latest updated_at' AS varchar(200)) AS reason
    INTO staging.employee_dedup_log
    FROM (
        SELECT emp_id,
               ROW_NUMBER() OVER (PARTITION BY emp_id ORDER BY updated_at DESC) AS keep_rank,
               COUNT(*)            OVER (PARTITION BY emp_id) AS group_rows,
               MAX(updated_at)     OVER (PARTITION BY emp_id) AS kept_updated_at,
               MIN(updated_at)     OVER (PARTITION BY emp_id) AS dropped_updated_at
        FROM staging.employees_cleaned
    ) q
    WHERE q.keep_rank > 1;
    """

    def _verify(self, cur, cn):
        """Guards first, then the rebuild; committed only after the rule-1
        equation (cleaned = final + merged) holds."""
        if cur.execute(self.SQL_EMPS_READY).fetchval() != 1:
            sys.exit("ABORT: staging.employees_cleaned missing — run the cleaning first.")
        if cur.execute(self.SQL_TIE_CHECK).fetchval() > 0:
            sys.exit("ABORT: duplicated (emp_id, updated_at) ties — rule-1 ordering is not deterministic.")

        cur.execute(self.SQL_REBUILD)

        final_rows = cur.execute("SELECT COUNT(*) FROM staging.employees_final").fetchval()
        distinct_ids = cur.execute("SELECT COUNT(DISTINCT emp_id) FROM staging.employees_final").fetchval()
        if final_rows != distinct_ids:
            sys.exit(f"ABORT: employees_final has {final_rows} rows but only {distinct_ids} distinct emp_id.")

        log_rows = cur.execute("SELECT COUNT(*) FROM staging.employee_dedup_log").fetchval()
        clean_rows = cur.execute("SELECT COUNT(*) FROM staging.employees_cleaned").fetchval()
        merged = cur.execute(
            "SELECT TOP 3 emp_id, merged_rows, kept_updated_at, dropped_updated_at"
            " FROM staging.employee_dedup_log ORDER BY emp_id"
        ).fetchall()

        cn.commit()
        return final_rows, log_rows, clean_rows, merged

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        try:
            final_rows, log_rows, clean_rows, merged = self._verify(cur, cn)
        except Exception:
            cn.rollback()
            raise

        print(f"staging.employees_cleaned : {clean_rows:,} rows")
        print(f"staging.employees_final   : {final_rows:,} rows (1 per emp_id, rule 1)")
        print(f"staging.employee_dedup_log: {log_rows:,} merged duplicate groups")
        if clean_rows != final_rows + log_rows:
            print("check                     : MISMATCH! cleaned != final + merged")
        else:
            print(f"check                     : {final_rows:,} + {log_rows:,} = {clean_rows:,}  OK")
        print("\nSample merged log rows:")
        for row in merged:
            print(f"  {row[0]}  rows={row[1]}  kept={row[2]}  dropped={row[3]}")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage2Bullet02EmployeeDedup().run())
