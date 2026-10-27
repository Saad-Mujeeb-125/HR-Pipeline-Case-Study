/* =====================================================================
STAGE 5 — Question 9 of the case-study PDF (p.6):
  "Payroll cost per employee by department, with month-over-month change."
Business rule:
  rule 21 - payroll cost = sum of EARNING lines.
  rule 3  - cost is attributed to the department at month end, or the
            separation date within the month (fixed ranks in fact Payline).
Definitions fixed here:
  cost          = SUM(EARNING amounts) for (dept, payroll month).
  employees     = DISTINCT employees paid in that dept-month (same attribution
                  engine, so numerator and denominator are consistent).
  cost_per_emp  = cost / employees.
  mom_change_pct= cost_per_emp vs the PREVIOUS payroll month within the same
                  department (LAG), percentage 2 dp; April (the first month)
                  has no previous month -> NULL.
Grain: one row per (dept, payroll_month) - 150 rows.

Deliverable: pipeline/warehouse/analytics/q09.sql (+ q09_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q09
)
===================================================================== */

WITH monthly AS (
    SELECT fp.dept_id,
           CAST(fp.payroll_month AS varchar(7)) AS payroll_month,
           SUM(CASE WHEN fp.component_type = 'EARNING' THEN fp.amount ELSE 0 END) AS cost,
           COUNT(DISTINCT CAST(fp.emp_id AS varchar(20))) AS employees_paid
    FROM warehouse.fact_payroll_line fp
    GROUP BY fp.dept_id, CAST(fp.payroll_month AS varchar(7))
),
per_emp AS (
    SELECT m.dept_id,
           m.payroll_month,
           m.cost,
           m.employees_paid,
           CAST(m.cost / m.employees_paid AS decimal(12, 2)) AS cost_per_emp,
           LAG(CAST(m.cost / m.employees_paid AS decimal(12, 2))) OVER (
               PARTITION BY m.dept_id ORDER BY m.payroll_month) AS prev_cost_per_emp
    FROM monthly m
)
SELECT p.*,
       dd.dept_name,
       CASE WHEN p.prev_cost_per_emp IS NULL OR p.prev_cost_per_emp = 0 THEN NULL
            ELSE CAST(100.0 * (p.cost_per_emp - p.prev_cost_per_emp) / p.prev_cost_per_emp AS decimal(9, 2))
       END AS mom_change_pct
FROM per_emp p
JOIN warehouse.dim_department dd ON dd.dept_id = p.dept_id
ORDER BY p.payroll_month, p.dept_id;
