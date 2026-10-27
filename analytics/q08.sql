/* =====================================================================
STAGE 5 — Question 8 of the case-study PDF (p.6):
  "Employees still receiving pay after their separation date."
Business rule:
  rule 4 - "separation_date is the last day worked" -> the month of the
           separation date is legitimately paid (the employee worked part of
           it); every payroll month STRICTLY AFTER the separation month is
           a "still receiving pay" violation.
Rule 21 - payroll cost = sum of EARNING lines, so the violation amount here
           uses EARNING lines only (the full payslip's earnings).

Grain: one row per employee who received at least one payroll month strictly
after their separation month, listing the months (ordered, semicolon-list),
count of months, and total EARNING amount over them.

Deliverable: pipeline/warehouse/analytics/q08.sql (+ q08_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q08
)
===================================================================== */

WITH paid AS (
    SELECT CAST(fp.emp_id AS varchar(20)) AS emp_id,
           CAST(fp.payroll_month AS varchar(7)) AS payroll_month,
           SUM(CASE WHEN fp.component_type = 'EARNING' THEN fp.amount ELSE 0 END) AS earned_amount
    FROM warehouse.fact_payroll_line fp
    GROUP BY CAST(fp.emp_id AS varchar(20)), CAST(fp.payroll_month AS varchar(7))
),
after_sep AS (
    SELECT p.emp_id, p.payroll_month, p.earned_amount, m.sep_date
    FROM paid p
    JOIN (
        SELECT TRY_CAST(e.separation_date AS date) AS sep_date,
               CAST(e.emp_id AS varchar(20)) AS emp_id
        FROM staging.employees_final e
        WHERE TRY_CAST(e.separation_date AS date) IS NOT NULL
    ) m ON m.emp_id = p.emp_id
    WHERE p.payroll_month > FORMAT(m.sep_date, 'yyyy-MM')   -- strictly AFTER separation month
),
grouped AS (
    SELECT a.emp_id,
           MIN(a.sep_date) AS separation_date,
           STRING_AGG(a.payroll_month, ';') WITHIN GROUP (ORDER BY a.payroll_month) AS months_paid_after_sep,
           COUNT(*) AS months_count,
           SUM(a.earned_amount) AS total_paid_after_sep
    FROM after_sep a
    GROUP BY a.emp_id
)
SELECT g.emp_id,
       e.full_name,
       g.separation_date,
       g.months_paid_after_sep,
       g.months_count,
       CAST(g.total_paid_after_sep AS decimal(14, 2)) AS total_paid_after_sep
FROM grouped g
JOIN warehouse.dim_employee e
  ON e.emp_id = g.emp_id AND e.is_current = 1
ORDER BY g.separation_date, g.emp_id;
