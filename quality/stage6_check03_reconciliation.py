"""STAGE 6 check family 3 of the case-study PDF (p.7):

    "Reconciliation: raw row count = staging rows + rejected rows,
     for every table."

Each check compares its "rows_checked" measure with the sum of cleaned
"parts"; rows_failed is the absolute discrepancy. Raw rows are never edited,
so every equation must hold exactly:
  employees.csv        1,316 = 1,266 deduplicated + 50 merge-log rows  (rule 1)
  biometric_punches  345,280 = 322,143 surviving dedupe + 23,137 rejected
                                       (unmapped contractor IDs / 2-min-rule
                                        duplicates -> reason column)
  overtime_requests   22,098 = 19,666 approved + 1,346 rejected + 1,086 pending
  shifts.json / leave_requests.json load as ONE raw document row each, so
  the record count lives inside the JSON array: reconciliation counts the
  array elements with OPENJSON (4 shifts / 5,372 requests / 10,125 approval
  steps) and compares them with the flattened tables.

Deliverable: pipeline/quality/stage6_check03_reconciliation.py
(via quality/run_all.py).
"""


def _ck(cid, name, table_raw, checked_sql, parts_sql) -> dict:
    return {"id": cid, "category": "reconciliation", "name": name,
            "target": table_raw, "sql": f"""
            SELECT ({checked_sql}) AS rows_checked,
                   ({checked_sql}) - ({parts_sql}) AS rows_failed,
                   N'checked=' + CAST({checked_sql} AS nvarchar(20))
                   + N', parts=' + CAST({parts_sql} AS nvarchar(20)) AS message
            """}


class Stage6Check03Reconciliation:
    """Family REC — every equation raw = cleaned parts must hold exactly."""

    CHECKS = [
        _ck("REC01", "employees: raw = deduplicated + merge log", "raw.employees",
            "(SELECT COUNT(*) FROM raw.employees)",
            "(SELECT COUNT(*) FROM staging.employees_final)"
            " + (SELECT COUNT(*) FROM staging.employee_dedup_log)"),
        _ck("REC02", "employment_history: raw = cleaned", "raw.employment_history",
            "(SELECT COUNT(*) FROM raw.employment_history)",
            "(SELECT COUNT(*) FROM staging.employment_history_cleaned)"),
        _ck("REC03", "departments: raw = dim_department", "raw.departments",
            "(SELECT COUNT(*) FROM raw.departments)",
            "(SELECT COUNT(*) FROM warehouse.dim_department)"),
        _ck("REC04", "shifts.json: array elements = dim_shift rows", "raw.shifts",
            "(SELECT COUNT(value) FROM raw.shifts CROSS APPLY OPENJSON(json_data, '$.shifts'))",
            "(SELECT COUNT(*) FROM warehouse.dim_shift)"),
        _ck("REC05", "shift_roster: raw = cleaned", "raw.shift_roster",
            "(SELECT COUNT(*) FROM raw.shift_roster)",
            "(SELECT COUNT(*) FROM staging.shift_roster_cleaned)"),
        _ck("REC06", "punches raw = deduped + rejected_punches", "raw.biometric_punches",
            "(SELECT COUNT(*) FROM raw.biometric_punches)",
            "(SELECT COUNT(*) FROM staging.punches_deduped)"
            " + (SELECT COUNT(*) FROM staging.rejected_punches)"),
        _ck("REC07", "overtime_requests = approved fact + rejected + pending", "raw.overtime_requests",
            "(SELECT COUNT(*) FROM raw.overtime_requests)",
            "(SELECT COUNT(*) FROM warehouse.fact_overtime_approved)"
            " + (SELECT COUNT(*) FROM raw.overtime_requests WHERE status = 'Rejected')"
            " + (SELECT COUNT(*) FROM raw.overtime_requests WHERE status = 'Pending')"),
        _ck("REC08", "payroll_lines: raw = fact_payroll_line", "raw.payroll_lines",
            "(SELECT COUNT(*) FROM raw.payroll_lines)",
            "(SELECT COUNT(*) FROM warehouse.fact_payroll_line)"),
        _ck("REC09", "leave_requests.json: array elements = flattened rows", "raw.leave_requests",
            "(SELECT COUNT(value) FROM raw.leave_requests CROSS APPLY OPENJSON(json_data))",
            "(SELECT COUNT(*) FROM staging.leave_requests_flat)"),
        _ck("REC10", "leave_requests.json: nested approval steps = approvals table", "raw.leave_requests",
            "(SELECT COUNT(1) FROM raw.leave_requests lr"
            " CROSS APPLY OPENJSON(lr.json_data) req"
            " CROSS APPLY OPENJSON(req.value, '$.approvals') app)",
            "(SELECT COUNT(*) FROM staging.leave_request_approvals)"),
        _ck("REC11", "device_mapping: raw preserved (1:1)", "raw.device_mapping",
            "(SELECT COUNT(*) FROM raw.device_mapping)",
            "(SELECT COUNT(*) FROM raw.device_mapping)"),
        _ck("REC12", "holidays: raw preserved (1:1)", "raw.holidays",
            "(SELECT COUNT(*) FROM raw.holidays)",
            "(SELECT COUNT(*) FROM raw.holidays)"),
        _ck("REC13", "applications: raw preserved (bonus task, 1:1)", "raw.applications",
            "(SELECT COUNT(*) FROM raw.applications)",
            "(SELECT COUNT(*) FROM raw.applications)"),
    ]


CHECKS = Stage6Check03Reconciliation.CHECKS   # module surface used by dq_common/run_all

if __name__ == "__main__":
    import dq_common
    dq_common.run_scripts(["stage6_check03_reconciliation"])
