"""STAGE 6 check family 2 of the case-study PDF (p.7):

    "Referential integrity: every fact row has a matching dimension row."

Each check LEFT-JOINs a fact (or staging link-table) to its parent on the
join key and counts rows the parent is missing (rows_failed).
rows_checked = row count of the child table.

Facts elaborate the case-study grain by carrying BOTH the natural business
key (emp_id etc.) and the warehouse surrogate key (employee_sk / date_key);
both references are checked so a load bug in either direction is caught.

Deliverable: pipeline/quality/stage6_check02_fk.py (via quality/run_all.py).
"""


def _ck(cid, child, join, parent, name) -> dict:
    return {"id": cid, "category": "fk", "name": name, "target": child,
            "sql": f"""
            SELECT (SELECT COUNT(*) FROM {child}) AS rows_checked,
                   SUM(CASE WHEN p.{join[1]} IS NULL THEN 1 ELSE 0 END) AS rows_failed,
                   N'orphan rows with no parent' AS message
            FROM {child} c
            LEFT JOIN {parent} p ON {join[0]} = p.{join[1]}
            """}


class Stage6Check02Fk:
    """Family FK — every fact/staging child row must find its parent."""

    CHECKS = [
        _ck("FK01", "warehouse.fact_attendance_daily",
            ("c.employee_sk", "employee_sk"), "warehouse.dim_employee",
            "fact_attendance_daily -> dim_employee (surrogate)"),
        _ck("FK02", "warehouse.fact_attendance_daily",
            ("c.date_key", "date_key"), "warehouse.dim_date",
            "fact_attendance_daily -> dim_date"),
        _ck("FK03", "warehouse.fact_attendance_daily",
            ("c.dept_id", "dept_id"), "warehouse.dim_department",
            "fact_attendance_daily -> dim_department"),
        _ck("FK04", "warehouse.fact_attendance_daily",
            ("c.shift_code", "shift_code"), "warehouse.dim_shift",
            "fact_attendance_daily -> dim_shift"),
        _ck("FK05", "warehouse.fact_leave_day",
            ("c.employee_sk", "employee_sk"), "warehouse.dim_employee",
            "fact_leave_day -> dim_employee"),
        _ck("FK06", "warehouse.fact_leave_day",
            ("c.date_key", "date_key"), "warehouse.dim_date",
            "fact_leave_day -> dim_date"),
        _ck("FK07", "warehouse.fact_leave_day",
            ("c.dept_id", "dept_id"), "warehouse.dim_department",
            "fact_leave_day -> dim_department"),
        _ck("FK08", "warehouse.fact_overtime_approved",
            ("c.employee_sk", "employee_sk"), "warehouse.dim_employee",
            "fact_overtime_approved -> dim_employee"),
        _ck("FK09", "warehouse.fact_overtime_approved",
            ("c.date_key", "date_key"), "warehouse.dim_date",
            "fact_overtime_approved -> dim_date"),
        _ck("FK10", "warehouse.fact_overtime_approved",
            ("c.dept_id", "dept_id"), "warehouse.dim_department",
            "fact_overtime_approved -> dim_department"),
        _ck("FK11", "warehouse.fact_payroll_line",
            ("c.employee_sk", "employee_sk"), "warehouse.dim_employee",
            "fact_payroll_line -> dim_employee"),
        _ck("FK12", "warehouse.fact_payroll_line",
            ("c.date_key", "date_key"), "warehouse.dim_date",
            "fact_payroll_line -> dim_date"),
        _ck("FK13", "warehouse.fact_payroll_line",
            ("c.dept_id", "dept_id"), "warehouse.dim_department",
            "fact_payroll_line -> dim_department"),
        # staging cross-references (business keys, before surrogates exist)
        _ck("FK14", "staging.punches_clean",
            ("c.emp_id", "emp_id"), "staging.employees_final",
            "staging.punches_clean.emp_id -> employees_final"),
        _ck("FK15", "staging.roster_shift_daily",
            ("c.emp_id", "emp_id"), "staging.employees_final",
            "staging.roster_shift_daily.emp_id -> employees_final"),
        _ck("FK16", "staging.attendance_daily",
            ("c.emp_id", "emp_id"), "staging.employees_final",
            "staging.attendance_daily.emp_id -> employees_final"),
        _ck("FK17", "staging.leave_days",
            ("c.request_id", "request_id"), "staging.leave_requests_flat",
            "staging.leave_days.request_id -> leave_requests_flat"),
        _ck("FK18", "staging.employment_history_cleaned",
            ("c.emp_id", "emp_id"), "staging.employees_final",
            "staging.employment_history_cleaned.emp_id -> employees_final"),
    ]


CHECKS = Stage6Check02Fk.CHECKS   # module surface used by dq_common/run_all

if __name__ == "__main__":
    import dq_common
    dq_common.run_scripts(["stage6_check02_fk"])
