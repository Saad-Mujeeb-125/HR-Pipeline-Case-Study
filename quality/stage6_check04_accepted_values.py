"""STAGE 6 check family 4 of the case-study PDF (p.7):

    "Accepted values: attendance status, leave type, pay component."

Whitelists come from data_dictionary.md's rule set (rule 12 statuses,
rule 16 leave types, rule 21 payroll components). rows_failed = rows whose
value is outside the whitelist; rows_checked = all rows of the column.

Deliverable: pipeline/quality/stage6_check04_accepted_values.py
(via quality/run_all.py).
"""

STATUSES = ("'Present'", "'Absent'", "'On Leave'", "'Holiday'", "'Weekly Off'", "'Missing Punch'")
LEAVE_TYPES = ("'Annual'", "'Casual'", "'Sick'")
COMPONENT_TYPES = ("'EARNING'", "'DEDUCTION'")
COMPONENTS = ("'BASIC'", "'HOUSE_RENT'", "'MEDICAL'", "'CONVEYANCE'", "'OVERTIME'",
              "'EOBI'", "'INCOME_TAX'", "'ABSENCE_DEDUCTION'", "'LOAN_INSTALLMENT'")
OT_STATUSES = ("'Approved'", "'Pending'", "'Rejected'")


def _ck(cid, name, table, col, allowed) -> dict:
    inlist = ", ".join(allowed)
    return {"id": cid, "category": "accepted_values", "name": name, "target": table,
            "sql": f"""
            SELECT COUNT(*) AS rows_checked,
                   SUM(CASE WHEN {col} IS NULL OR {col} NOT IN ({inlist}) THEN 1 ELSE 0 END) AS rows_failed,
                   N'rows outside whitelist' AS message
            FROM {table}
            """}


class Stage6Check04AcceptedValues:
    """Family AV — all coded columns stay inside data_dictionary whitelists."""

    CHECKS = [
        _ck("AV01", "staging.attendance_daily.status values", "staging.attendance_daily", "status", STATUSES),
        _ck("AV02", "fact_attendance_daily.status values", "warehouse.fact_attendance_daily", "status", STATUSES),
        _ck("AV03", "staging.leave_requests_flat.leave_type values", "staging.leave_requests_flat", "leave_type", LEAVE_TYPES),
        _ck("AV04", "staging.leave_days.leave_type values", "staging.leave_days", "leave_type", LEAVE_TYPES),
        _ck("AV05", "fact_leave_day.leave_type values", "warehouse.fact_leave_day", "leave_type", LEAVE_TYPES),
        _ck("AV06", "fact_payroll_line.component_type values", "warehouse.fact_payroll_line", "component_type", COMPONENT_TYPES),
        _ck("AV07", "fact_payroll_line.component values", "warehouse.fact_payroll_line", "component", COMPONENTS),
        _ck("AV08", "raw.overtime_requests.status values", "raw.overtime_requests", "status", OT_STATUSES),
    ]


CHECKS = Stage6Check04AcceptedValues.CHECKS   # module surface used by dq_common/run_all

if __name__ == "__main__":
    import dq_common
    dq_common.run_scripts(["stage6_check04_accepted_values"])
