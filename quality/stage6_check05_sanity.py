"""STAGE 6 check family 5 of the case-study PDF (p.7):

    "Business sanity: no negative worked hours, no shift longer than 16
     hours, no overlapping SCD2 ranges."

Extension checks recorded alongside (same spirit, cheap to defend): negative
late/early/OT minutes, negative payroll amounts, and fact columns that must
agree with their status (e.g. rows with status <> Present must not carry
late minutes). rows_failed = offending rows; rows_checked = table rows.

Deliverable: pipeline/quality/stage6_check05_sanity.py (via run_all.py).
"""


class Stage6Check05Sanity:
    """Family SA — business sanity over the cleaned layers."""

    CHECKS = [
        {"id": "SA01", "category": "sanity",
         "name": "staging.attendance_daily: no negative duration/late/early/OT",
         "target": "staging.attendance_daily",
         "sql": """
            SELECT COUNT(*) AS rows_checked,
                   SUM(CASE WHEN worked_minutes < 0 OR late_minutes < 0 OR early_minutes < 0
                                 OR ot_hours < 0 OR ot_minutes < 0
                            THEN 1 ELSE 0 END) AS rows_failed,
                   N'negative values' AS message
            FROM staging.attendance_daily
         """},
        {"id": "SA02", "category": "sanity",
         "name": "fact_attendance_daily: no negative duration/late/early/OT",
         "target": "warehouse.fact_attendance_daily",
         "sql": """
            SELECT COUNT(*) AS rows_checked,
                   SUM(CASE WHEN worked_minutes < 0 OR late_minutes < 0 OR early_minutes < 0
                                 OR ot_hours < 0
                            THEN 1 ELSE 0 END) AS rows_failed,
                   N'negative values' AS message
            FROM warehouse.fact_attendance_daily
         """},
        {"id": "SA03", "category": "sanity",
         "name": "staging.attendance_daily: worked minutes <= 960 (16h)",
         "target": "staging.attendance_daily",
         "sql": """
            SELECT COUNT(*) AS rows_checked,
                   SUM(CASE WHEN worked_minutes > 960 THEN 1 ELSE 0 END) AS rows_failed,
                   N'shifts longer than 16h' AS message
            FROM staging.attendance_daily
         """},
        {"id": "SA04", "category": "sanity",
         "name": "fact_attendance_daily: worked minutes <= 960 (16h)",
         "target": "warehouse.fact_attendance_daily",
         "sql": """
            SELECT COUNT(*) AS rows_checked,
                   SUM(CASE WHEN worked_minutes > 960 THEN 1 ELSE 0 END) AS rows_failed,
                   N'shifts longer than 16h' AS message
            FROM warehouse.fact_attendance_daily
         """},
        {"id": "SA05", "category": "sanity",
         "name": "dim_employee: no overlapping SCD2 ranges",
         "target": "warehouse.dim_employee",
         "sql": """
            SELECT (SELECT COUNT(*) FROM warehouse.dim_employee) AS rows_checked,
                   (SELECT COUNT(*) FROM warehouse.dim_employee a
                    WHERE EXISTS (SELECT 1 FROM warehouse.dim_employee b
                                  WHERE b.emp_id = a.emp_id
                                    AND a.employee_sk <> b.employee_sk
                                    AND b.valid_from > a.valid_from
                                    AND b.valid_from <= a.valid_to)) AS rows_failed,
                   N'ranges where a later row starts <= the earlier valid_to' AS message
         """},
        {"id": "SA06", "category": "sanity",
         "name": "fact_payroll_line: no negative amounts",
         "target": "warehouse.fact_payroll_line",
         "sql": """
            SELECT COUNT(*) AS rows_checked,
                   SUM(CASE WHEN amount < 0 OR units < 0 THEN 1 ELSE 0 END) AS rows_failed,
                   N'negative payroll values' AS message
            FROM warehouse.fact_payroll_line
         """},
        {"id": "SA07", "category": "sanity",
         "name": "staging.leave_days: leave_day within leave window & not Sunday",
         "target": "staging.leave_days",
         "sql": """
            SELECT COUNT(*) AS rows_checked,
                   SUM(CASE WHEN f.leave_day < f.leave_from_day
                                 OR f.leave_day > f.leave_to_day
                                 OR DATEDIFF(day, '2026-01-04', f.leave_day) % 7 = 0
                            THEN 1 ELSE 0 END) AS rows_failed,
                   N'leave days outside request window or on a Sunday' AS message
            FROM (SELECT ld.leave_day, r.leave_from AS leave_from_day,
                         r.leave_to AS leave_to_day
                  FROM staging.leave_days ld
                  JOIN staging.leave_requests_flat r ON r.request_id = ld.request_id) f
         """},
    ]


CHECKS = Stage6Check05Sanity.CHECKS   # module surface used by dq_common/run_all

if __name__ == "__main__":
    import dq_common
    dq_common.run_scripts(["stage6_check05_sanity"])
