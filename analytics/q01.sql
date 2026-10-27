/* =====================================================================
STAGE 5 — Question 1 of the case-study PDF (p.6):
  "Month-end headcount by plant and department, for all six months."
Business rules:
  rule 3 - monthly figures belong to the department the employee was in on
           the last day of the month.
  rule 4 - an employee is in headcount at month end if hire_date <= month end
           AND they have no separation_date, OR separation_date is after
           month end. separation_date is the last day worked, so an employee
           who left ON the month's last day is NOT in that month-end
           headcount (they appear in question 2's separations instead).

Grain: one row per (plant, year_month, department) — the complete six-month
matrix for every (plant, dept) combination the periods contain, zero-filled.
Plant: the employee's own plant (employees.csv); verified 0 mismatches with
the department plant across all 3,686 SCD2 rows, so either source is identical.

Deliverable: pipeline/warehouse/analytics/q01.sql (+ q01_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q01
)
===================================================================== */

WITH months AS (
    SELECT * FROM (VALUES
        ('2026-04-30', '2026-04'),
        ('2026-05-31', '2026-05'),
        ('2026-06-30', '2026-06'),
        ('2026-07-31', '2026-07'),
        ('2026-08-31', '2026-08'),
        ('2026-09-30', '2026-09')
    ) m(m_date, m_key)
),
combos AS (   -- every (plant, dept) pair the employment periods contain
    SELECT DISTINCT de.plant, de.dept_id
    FROM warehouse.dim_employee de
    WHERE de.separation_date IS NULL OR de.separation_date > '2026-04-30'
),
month_headcount AS (
    SELECT m.m_key, x.plant, x.dept_id, COUNT(*) AS headcount
    FROM months m
    CROSS APPLY (
        SELECT de.emp_id, de.plant, de.dept_id
        FROM warehouse.dim_employee de
        WHERE de.hire_date <= m.m_date                                       -- rule 4a
          AND (de.separation_date IS NULL OR de.separation_date > m.m_date)   -- rule 4b
          AND de.valid_from <= m.m_date                                      -- rule 3: dept at month end
          AND COALESCE(de.valid_to, '9999-12-31') >= m.m_date
    ) x
    GROUP BY m.m_key, x.plant, x.dept_id
)
SELECT m.m_key          AS payroll_month,
       c.plant,
       c.dept_id,
       dd.dept_name,
       ISNULL(h.headcount, 0) AS headcount
FROM months m
CROSS JOIN combos c
JOIN warehouse.dim_department dd ON dd.dept_id = c.dept_id
LEFT JOIN month_headcount h
       ON h.m_key = m.m_key AND h.plant = c.plant AND h.dept_id = c.dept_id
ORDER BY m.m_key, c.plant, c.dept_id;
