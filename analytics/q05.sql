/* =====================================================================
STAGE 5 — Question 5 of the case-study PDF (p.6):
  "Overtime hours computed from punches vs approved vs paid, by department
   and month."
Business rules:
  rule 14 - OT minutes after shift end, floored to half-hours (Stage 3's
            fact_attendance_daily.ot_hours on Present days).
  rule 15 - Sunday/holiday work is all OT (also in fact_attendance_daily.ot_hours,
            distinguishable via is_sunday/is_holiday).
  rule 19 - only overtime_requests with status = Approved count as approved.
  rule 20 - payroll's OVERTIME line units = hours paid.

The three measures are attributed to (department, payroll month) exactly as
their grain is defined in the warehouse:
  computed_ot_hours  <- fact_attendance_daily (rule 3 dept on the work date)
  approved_ot_hours  <- fact_overtime_approved (rule 3 dept on the ot date)
  paid_ot_hours      <- fact_payroll_line OVERTIME lines
                        (rule 3: dept at month end / separation)
A department-month with no rows in one source reports 0 for that source, so
the comparison matrix is complete.

Grain: one row per (dept, payroll_month) - 150 rows.

Deliverable: pipeline/warehouse/analytics/q05.sql (+ q05_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q05
)
===================================================================== */

WITH computed AS (
    SELECT fa.dept_id,
           FORMAT(fa.work_date, 'yyyy-MM') AS payroll_month,
           SUM(fa.ot_hours) AS computed_ot_hours
    FROM warehouse.fact_attendance_daily fa
    GROUP BY fa.dept_id, FORMAT(fa.work_date, 'yyyy-MM')
),
approved AS (
    SELECT fo.dept_id,
           FORMAT(fo.ot_date, 'yyyy-MM') AS payroll_month,
           SUM(fo.approved_hours) AS approved_ot_hours
    FROM warehouse.fact_overtime_approved fo
    GROUP BY fo.dept_id, FORMAT(fo.ot_date, 'yyyy-MM')
),
paid AS (
    SELECT fp.dept_id,
           CAST(fp.payroll_month AS varchar(7)) AS payroll_month,
           SUM(fp.units) AS paid_ot_hours
    FROM warehouse.fact_payroll_line fp
    WHERE fp.component = 'OVERTIME'
    GROUP BY fp.dept_id, CAST(fp.payroll_month AS varchar(7))
),
combos AS (
    SELECT DISTINCT de.dept_id
    FROM warehouse.dim_employee de
),
months AS (
    SELECT m.m_key FROM (VALUES ('2026-04'), ('2026-05'), ('2026-06'),
                                ('2026-07'), ('2026-08'), ('2026-09')) m(m_key)
)
SELECT c.dept_id,
       dd.dept_name,
       m.m_key AS payroll_month,
       CAST(ISNULL(cp.computed_ot_hours, 0) AS decimal(10, 2)) AS computed_ot_hours,
       CAST(ISNULL(ap.approved_ot_hours, 0) AS decimal(10, 2)) AS approved_ot_hours,
       CAST(ISNULL(pa.paid_ot_hours, 0)     AS decimal(10, 2)) AS paid_ot_hours
FROM combos c
CROSS JOIN months m
JOIN warehouse.dim_department dd ON dd.dept_id = c.dept_id
LEFT JOIN computed cp ON cp.dept_id = c.dept_id AND cp.payroll_month = m.m_key
LEFT JOIN approved ap ON ap.dept_id = c.dept_id AND ap.payroll_month = m.m_key
LEFT JOIN paid    pa ON pa.dept_id = c.dept_id AND pa.payroll_month = m.m_key
ORDER BY m.m_key, c.dept_id;
