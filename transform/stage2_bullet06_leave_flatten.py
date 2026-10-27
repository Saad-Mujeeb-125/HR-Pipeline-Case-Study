"""STAGE 2, bullet 6 of the case-study PDF (p.5):
    "Flatten leave_requests.json into one row per request and one row per
     approval step."
Business rules set the frame (applied downstream in bullet 7 and Stage 3):
  rule 16 — leave counts ONLY if both approval steps (Manager, then HR) say
            Approved and cancelled_at is empty.
  rule 17 — a leave day = any day in from..to; Sundays and plant holidays
            inside the range are NOT leave days (bullet 7 / rule 12).

What it builds:
  staging.leave_requests_flat     5,372 rows — one per request, with the
                                  employee header, leave range, cancellation
                                  status and how many approval steps were recorded
  staging.leave_request_approvals One row per approval step (~2 per request:
                                  Manager step 1 (rule 16), HR step 2).

Notes from the raw JSON (verified while building):
  - approval workflow sometimes stops after step 1 (a rejection ends it) — so
    not every request has 2 approvals;
  - actions seen: Approved / Rejected (there are no pending actions in this
    export); 254 requests were cancelled;
  - leave types: Casual / Sick / Annual;
  - days_requested is employee-entered and NOT trusted for counting (rule 17).

Run anytime after Stage 1. Idempotent: both tables rebuilt every run.
    python -X utf8 pipeline/transform/stage2/stage2_bullet06_leave_flatten.py
"""
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage2Bullet06LeaveFlatten(PipelineTask):
    """Stage 2 bullet 6 — leave_requests.json -> flat requests + approval steps."""

    SQL_BUILD_REQUESTS = """
    IF OBJECT_ID('staging.leave_requests_flat') IS NOT NULL DROP TABLE staging.leave_requests_flat;
    SELECT v.request_id,
           v.emp_id,
           v.plant,
           v.leave_type,
           TRY_CAST(v.leave_from AS date) AS leave_from,
           TRY_CAST(v.leave_to   AS date) AS leave_to,          -- rule 17 range, typed
           v.days_requested,                                    -- rule 17: NOT trusted for counting
           v.submitted_at,
           v.cancelled_at,                                      -- rule 16: must be empty to count
           a.approvals_n
    INTO staging.leave_requests_flat
    FROM raw.leave_requests s
    CROSS APPLY OPENJSON(s.json_data) WITH (
        request_id    varchar(20) '$.request_id',
        emp_id        varchar(20) '$.employee.emp_id',
        plant         varchar(60) '$.employee.plant',
        leave_type    varchar(20) '$.leave.type',
        leave_from    date        '$.leave.from',
        leave_to      date        '$.leave.to',
        days_requested int        '$.leave.days_requested',
        submitted_at  datetime2   '$.submitted_at',
        cancelled_at  datetime2   '$.cancelled_at',
        approvals     nvarchar(max) '$.approvals' AS JSON
    ) v
    CROSS APPLY (SELECT COUNT(*) AS approvals_n FROM OPENJSON(v.approvals)) a;
    """

    SQL_BUILD_APPROVALS = """
    IF OBJECT_ID('staging.leave_request_approvals') IS NOT NULL DROP TABLE staging.leave_request_approvals;
    SELECT v.request_id,
           a.step,                                              -- rule 16: step 1 Manager, step 2 HR
           a.approver_role,
           a.approver_id,
           a.action,
           a.acted_at
    INTO staging.leave_request_approvals
    FROM raw.leave_requests s
    CROSS APPLY OPENJSON(s.json_data) WITH (
        request_id varchar(20) '$.request_id',
        approvals  nvarchar(max) '$.approvals' AS JSON
    ) v
    CROSS APPLY OPENJSON(v.approvals) WITH (
        step          int         '$.step',
        approver_role varchar(20) '$.approver_role',
        approver_id   varchar(30) '$.approver_id',
        action        varchar(20) '$.action',
        acted_at      datetime2   '$.acted_at'
    ) a;
    """

    def _flatten(self, cur, cn):
        """Build both flat tables + the rule-16/17 sanity tallies."""
        cur.execute(self.SQL_BUILD_REQUESTS)
        cur.execute(self.SQL_BUILD_APPROVALS)

        total_requests = cur.execute("SELECT COUNT(*) FROM staging.leave_requests_flat").fetchval()
        total_approvals = cur.execute("SELECT COUNT(*) FROM staging.leave_request_approvals").fetchval()
        requests_with_steps = cur.execute(
            "SELECT COUNT(DISTINCT request_id) FROM staging.leave_request_approvals").fetchval()
        if requests_with_steps != total_requests:
            sys.exit("ABORT: some flattened requests have no approval rows — flattening incomplete.")

        # sanity checks (rule 16 / 17 preparation)
        bad_dates = cur.execute(
            "SELECT COUNT(*) FROM staging.leave_requests_flat WHERE leave_from > leave_to").fetchval()
        unparsed = cur.execute(
            "SELECT COUNT(*) FROM staging.leave_requests_flat WHERE leave_from IS NULL OR leave_to IS NULL").fetchval()
        null_captured = cur.execute(
            "SELECT COUNT(*) FROM staging.leave_requests_flat WHERE emp_id IS NULL OR request_id IS NULL").fetchval()

        action_counts = cur.execute(
            "SELECT action, COUNT(*) FROM staging.leave_request_approvals"
            " GROUP BY action ORDER BY action").fetchall()
        step_counts = cur.execute(
            "SELECT approvals_n, COUNT(*) FROM staging.leave_requests_flat"
            " GROUP BY approvals_n ORDER BY approvals_n").fetchall()
        type_counts = cur.execute(
            "SELECT leave_type, COUNT(*) FROM staging.leave_requests_flat"
            " GROUP BY leave_type ORDER BY leave_type").fetchall()
        cancelled = cur.execute(
            "SELECT COUNT(*) FROM staging.leave_requests_flat WHERE cancelled_at IS NOT NULL").fetchval()

        cn.commit()
        return (total_requests, total_approvals, bad_dates, unparsed, null_captured,
                action_counts, step_counts, type_counts, cancelled)

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        try:
            (total_requests, total_approvals, bad_dates, unparsed, null_captured,
             action_counts, step_counts, type_counts, cancelled) = self._flatten(cur, cn)
        except Exception:
            cn.rollback()
            raise

        print(f"staging.leave_requests_flat     : {total_requests:,} rows (one per request)")
        print(f"staging.leave_request_approvals : {total_approvals:,} rows (one per approval step)")
        print(f"date sanity: {bad_dates} ranges with to < from; {unparsed} unparsed dates; {null_captured} null keys")
        print("approval steps per request:")
        for n, reqs in step_counts:
            print(f"  {n} step(s): {reqs:,}")
        print("approval actions:")
        for action, n in action_counts:
            print(f"  {action:<10} {n:,}")
        print("leave types:")
        for t, n in type_counts:
            print(f"  {t:<10} {n:,}")
        print(f"cancelled requests (rule 16 excludes): {cancelled:,}")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage2Bullet06LeaveFlatten().run())
