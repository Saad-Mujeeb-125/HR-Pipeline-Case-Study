"""STAGE 6 check family 1 of the case-study PDF (p.7):

    "Uniqueness and not-null checks on every primary key."

Scope: the CLEANED layers (staging + warehouse). The raw layer is loaded
"exactly as delivered" (Stage 1 bullet 1) and deliberately contains the
planted duplicates (employees.csv has 50 duplicate emp_id rows already split
into the merge log), so raw tables are reconciled in check 03 instead.

rows_failed = rows with a NULL key part + surplus duplicated rows.
rows_checked = total rows of the table. All queries read-only.

Deliverable: pipeline/quality/stage6_check01_pk.py (via quality/run_all.py).
"""


def _sql(table: str, cols) -> str:
    cs = ", ".join(cols)
    nullcond = " OR ".join(f"{c} IS NULL" for c in cols)
    return f"""
    WITH k AS (SELECT {cs} FROM {table}),
         s AS (SELECT COUNT(*) AS total,
                      SUM(CASE WHEN {nullcond} THEN 1 ELSE 0 END) AS nulls
               FROM k),
         g AS (SELECT COUNT(*) AS groups
               FROM (SELECT {cs} FROM k WHERE NOT ({nullcond}) GROUP BY {cs}) x),
         d AS (SELECT COUNT(*) AS dupes FROM (
                   SELECT {cs} FROM k WHERE NOT ({nullcond}) GROUP BY {cs}) d)
    SELECT s.total,
           s.nulls + (s.total - s.nulls - g.groups),
           N'distinct=' + CAST(g.groups AS nvarchar(20))
           + N', null_keys=' + CAST(s.nulls AS nvarchar(20))
           + N', surplus_dupes=' + CAST(s.total - s.nulls - g.groups AS nvarchar(20))
    FROM s, g
    """


def _ck(cid, table: str, cols) -> dict:
    return {"id": cid, "category": "pk",
            "name": f"{table} PK ({', '.join(cols)})",
            "target": table,
            "sql": _sql(table, cols)}


class Stage6Check01Pk:
    """Family PK — uniqueness + not-null on every staging/warehouse key."""

    CHECKS = [
        _ck("PK01", "warehouse.dim_date", ["date_key"]),
        _ck("PK02", "warehouse.dim_department", ["dept_id"]),
        _ck("PK03", "warehouse.dim_shift", ["shift_code"]),
        _ck("PK04", "warehouse.dim_employee", ["employee_sk"]),
        _ck("PK05", "warehouse.dim_employee", ["emp_id", "valid_from"]),
        _ck("PK06", "warehouse.fact_attendance_daily", ["emp_id", "work_date"]),
        _ck("PK07", "warehouse.fact_leave_day",
            [*("leave_request_id", "emp_id", "leave_day")]),
        _ck("PK08", "warehouse.fact_overtime_approved", ["request_id"]),
        _ck("PK09", "warehouse.fact_payroll_line", ["line_id"]),
        _ck("PK10", "warehouse.fact_payroll_line",
            [*("emp_id", "payroll_month", "component")]),
        _ck("PK11", "staging.employees_final", ["emp_id"]),
        _ck("PK12", "staging.employment_history_cleaned",
            [*("emp_id", "effective_from", "change_reason")]),
        _ck("PK13", "staging.roster_shift_daily", ["emp_id", "work_date"]),
        _ck("PK14", "staging.punches_mapped", ["punch_id"]),
        _ck("PK15", "staging.punches_deduped", ["punch_id"]),
        _ck("PK16", "staging.punches_clean", ["punch_id"]),
        _ck("PK17", "staging.rejected_punches", ["punch_id"]),
        _ck("PK18", "staging.attendance_daily", ["emp_id", "work_date"]),
        _ck("PK19", "staging.leave_requests_flat", ["request_id"]),
        _ck("PK20", "staging.leave_request_approvals", ["request_id", "step"]),
        _ck("PK21", "staging.leave_days", ["request_id", "leave_day"]),
        _ck("PK22", "staging.device_clock_offsets", ["device_id"]),
    ]


CHECKS = Stage6Check01Pk.CHECKS   # module surface used by dq_common/run_all

if __name__ == "__main__":
    import dq_common
    dq_common.run_scripts(["stage6_check01_pk"])
