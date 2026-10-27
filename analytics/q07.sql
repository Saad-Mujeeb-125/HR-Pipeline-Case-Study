/* =====================================================================
STAGE 5 — Question 7 of the case-study PDF (p.6):
  "Employees paid in a month with zero attendance in that month."
Business rules:
  rule 4 / rule 12 - every day of EMPLOYMENT has an attendance row (Stage 3
                     built one row per employment day for every status), so
                     "zero attendance rows in a month" can only happen when
                     the employee was not even employed during the paid
                     month: paid before hire (ghost pay) or paid for months
                     where no employment day exists.
Definition fixed here: zero attendance = NO fact_attendance_daily row for
that (emp_id, payroll_month), any status counts as attendance.
Grain: one row per (emp_id, payroll_month). Pay after separation is a
different question (q08) - it has attendance until separation and then
might look "zero" only for full months after... no employment days exist
then either; that is why BOTH checks share the anti-join logic but q07
reports every affected (emp, month) and q08 focuses on the separation story.

Deliverable: pipeline/warehouse/analytics/q07.sql (+ q07_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q07
)
===================================================================== */

WITH paid_months AS (
    SELECT DISTINCT CAST(fp.emp_id AS varchar(20)) AS emp_id,
           CAST(fp.payroll_month AS varchar(7))    AS payroll_month,
           SUM(CASE WHEN fp.component_type = 'EARNING' THEN fp.amount ELSE 0 END) AS paid_amount
    FROM warehouse.fact_payroll_line fp
    GROUP BY CAST(fp.emp_id AS varchar(20)), CAST(fp.payroll_month AS varchar(7))
)
SELECT pm.payroll_month,
       pm.emp_id,
       e.full_name,
       pm.paid_amount
FROM paid_months pm
JOIN warehouse.dim_employee e
  ON e.emp_id = pm.emp_id AND e.is_current = 1
WHERE NOT EXISTS (
    SELECT 1 FROM warehouse.fact_attendance_daily fa
    WHERE fa.emp_id = pm.emp_id
      AND FORMAT(fa.work_date, 'yyyy-MM') = pm.payroll_month)
ORDER BY pm.payroll_month, pm.emp_id;
