"""STAGE 2, bullet 7 of the case-study PDF (p.5):
    "Expand each approved leave request into one row per leave day."
Business rules:
  rule 16 — a leave request counts ONLY if BOTH approval steps (Manager, then
            HR) say Approved, and cancelled_at is empty. Requests whose workflow
            ended after the Manager step (never reached HR) do NOT count.
  rule 17 — a leave day = any day in the request's from..to range; Sundays and
            the employee's plant holidays inside that range are NOT leave days
            (rule 12 gives them their own attendance status instead).

What it builds:
  staging.leave_days   one row per counted leave day: request_id, emp_id,
                       plant, leave_type, leave_day

Method:
  1. Filter to rule-16 approved requests (both roles Approved, not cancelled).
  2. Explode each request with GENERATE_SERIES over from..to (inclusive).
  3. Drop Sundays: DATEDIFF(day, '2026-01-04' (a verified Sunday), leave_day)
     % 7 = 0 - a DATEFIRST-independent anchor date instead of DATEPART(weekday).
  4. Drop plant holidays: scope 'ALL' or the employee's plant code
     (Head Office=HO, Korangi Plant=KOR, SITE Plant=SITE, Faisalabad Plant=FSD).

Run AFTER stage2_bullet06_leave_flatten.py. Idempotent (table rebuilt).
    python -X utf8 pipeline/transform/stage2/stage2_bullet07_leave_days.py
"""
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage2Bullet07LeaveDays(PipelineTask):
    """Stage 2 bullet 7 — rule 16 approvals -> rule 17 one row per leave day."""

    SQL_TABLES_READY = """
    SELECT COUNT(DISTINCT t.name) FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name IN ('staging') AND t.name IN ('leave_requests_flat', 'leave_request_approvals', 'employees_final')
    """

    SQL_BUILD_LEAVE_DAYS = """
    IF OBJECT_ID('staging.leave_days') IS NOT NULL DROP TABLE staging.leave_days;

    WITH approved AS (
        -- rule 16: BOTH steps (Manager AND HR) Approved AND never cancelled.
        -- A request whose workflow stopped after the Manager step has no HR row
        -- and is therefore excluded automatically by this EXISTS pair.
        SELECT f.request_id, f.emp_id, f.plant, f.leave_type, f.leave_from, f.leave_to
        FROM staging.leave_requests_flat f
        WHERE f.cancelled_at IS NULL
          AND EXISTS (
                SELECT 1 FROM staging.leave_request_approvals a
                WHERE a.request_id = f.request_id
                  AND a.approver_role = 'Manager' AND a.action = 'Approved')
          AND EXISTS (
                SELECT 1 FROM staging.leave_request_approvals a
                WHERE a.request_id = f.request_id
                  AND a.approver_role = 'HR'      AND a.action = 'Approved')
    ),
    expanded AS (
        -- explode from..to inclusive (rule 17) and tag the holiday scope code
        SELECT ap.request_id, ap.emp_id, ap.plant, ap.leave_type,
               ap.leave_from, ap.plant_code,
               DATEADD(day, g.value, ap.leave_from) AS leave_day
        FROM (
            SELECT request_id, emp_id, plant, leave_type, leave_from, leave_to,
                   CASE plant                            -- holiday scope code (holidays.csv)
                       WHEN 'Head Office'      THEN 'HO'
                       WHEN 'Korangi Plant'    THEN 'KOR'
                       WHEN 'SITE Plant'       THEN 'SITE'
                       WHEN 'Faisalabad Plant' THEN 'FSD'
                   END AS plant_code
            FROM approved
        ) ap
        CROSS APPLY GENERATE_SERIES(0, DATEDIFF(day, ap.leave_from, ap.leave_to)) g
    )
    SELECT e.request_id, e.emp_id, e.plant, e.leave_type, e.plant_code,
           CAST(e.leave_day AS date) AS leave_day,
           CAST(DATEDIFF(day, e.leave_from, e.leave_day) AS int) + 1 AS day_in_request
    INTO staging.leave_days
    FROM expanded e
    WHERE DATEDIFF(day, '2026-01-04', e.leave_day) % 7 <> 0   -- rule 17: not a Sunday
      AND NOT EXISTS (
            SELECT 1 FROM raw.holidays h
            WHERE TRY_CAST(h.holiday_date AS date) = e.leave_day
              AND (h.scope = 'ALL' OR h.scope = e.plant_code)); -- rule 17 + rule 12: not plant holiday
    """

    SQL_RULE16_BREAKDOWN = """
        WITH per_request AS (
            SELECT f.request_id,
                   CASE WHEN f.cancelled_at IS NOT NULL THEN 1 ELSE 0 END AS cancelled,
                   CASE WHEN EXISTS (SELECT 1 FROM staging.leave_request_approvals a
                                     WHERE a.request_id = f.request_id
                                       AND a.approver_role = 'Manager'
                                       AND a.action = 'Approved') THEN 1 ELSE 0 END AS mgr_ok,
                   CASE WHEN EXISTS (SELECT 1 FROM staging.leave_request_approvals a
                                     WHERE a.request_id = f.request_id
                                       AND a.approver_role = 'HR'
                                       AND a.action = 'Approved') THEN 1 ELSE 0 END AS hr_ok
            FROM staging.leave_requests_flat f
        )
        SELECT SUM(cancelled) AS cancelled, SUM(never_approved) AS never_approved,
               SUM(mgr_only) AS mgr_only, SUM(hr_only) AS hr_only
        FROM (
            SELECT cancelled,
                   CASE WHEN cancelled = 0 AND mgr_ok = 0 AND hr_ok = 0 THEN 1 ELSE 0 END AS never_approved,
                   CASE WHEN cancelled = 0 AND mgr_ok = 1 AND hr_ok = 0 THEN 1 ELSE 0 END AS mgr_only,
                   CASE WHEN cancelled = 0 AND mgr_ok = 0 AND hr_ok = 1 THEN 1 ELSE 0 END AS hr_only
            FROM per_request
        ) t"""

    def _build(self, cur, cn):
        """Rebuild staging.leave_days and collect the reporting tallies."""
        if cur.execute(self.SQL_TABLES_READY).fetchval() != 3:
            sys.exit("ABORT: run stage2_bullet06 (leave flattening) first.")

        cur.execute(self.SQL_BUILD_LEAVE_DAYS)

        kept = cur.execute("SELECT COUNT(*) FROM staging.leave_days").fetchval()
        requests = cur.execute("SELECT COUNT(DISTINCT request_id) FROM staging.leave_days").fetchval()

        # Why other requests do NOT count (rule 16 story for the mentor):
        breakdown = cur.execute(self.SQL_RULE16_BREAKDOWN).fetchone()
        total_requests = cur.execute("SELECT COUNT(*) FROM staging.leave_requests_flat").fetchval()

        per_type = cur.execute(
            "SELECT leave_type, COUNT(*) FROM staging.leave_days"
            " GROUP BY leave_type ORDER BY leave_type").fetchall()
        per_month = cur.execute(
            "SELECT FORMAT(leave_day, 'yyyy-MM'), COUNT(*) FROM staging.leave_days"
            " GROUP BY FORMAT(leave_day, 'yyyy-MM') ORDER BY 1").fetchall()

        cn.commit()
        return kept, requests, breakdown, total_requests, per_type, per_month

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        try:
            (kept, requests, breakdown,
             total_requests, per_type, per_month) = self._build(cur, cn)
        except Exception:
            cn.rollback()
            raise

        print(f"staging.leave_days          : {kept:,} leave-day rows")
        print(f"distinct approved requests  : {requests:,}")
        cancelled, never_approved, manager_no_hr, hr_no_manager = breakdown
        other = total_requests - requests - cancelled - never_approved - manager_no_hr - hr_no_manager
        print("rule-16 story (all", f"{total_requests:,} requests):")
        print(f"  cancelled                                  : {cancelled:,}")
        print(f"  approved by no one (not counted)           : {never_approved:,}")
        print(f"  Manager approved, no HR step (not counted) : {manager_no_hr:,}   <- rule 16 needs BOTH")
        print(f"  HR approved, no Manager step (not counted) : {hr_no_manager:,}")
        if other:
            print(f"  other exclusions                           : {other:,}")
        print(f"  counted (both steps Approved, not cancelled): {requests:,}")
        print(f"per type   : {', '.join(f'{t} {n:,}' for t, n in per_type)}")
        print(f"per month  : {', '.join(f'{ym} {n:,}' for ym, n in per_month)}")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage2Bullet07LeaveDays().run())
