/* =====================================================================
STAGE 5 — Question 2 of the case-study PDF (p.6):
  "Monthly attrition rate by department (separations ÷ average headcount)."
Business rules:
  rule 3 - department of the employee on the last day of the month (for
           headcount attribution) AND on the last working day when they left
           mid-month (the employee's separation month belongs to the dept
           they left in).
  rule 4 - month-end headcount definition (identical to q01).
Definitions fixed in this query:
  separations(month, dept) = employees whose separation_date falls in that
      month AND who were in that department on their last working day
      (rule 3's "last working day" branch).
  average headcount(month, dept) = (headcount at month START + headcount at
      month END) / 2; month start = the population that meets rule 4 against
      the month's FIRST day (e.g. 2026-04-01 for April).
  attrition rate = separations / average headcount, reported as
      percentage with 2 dp (a rate of 0.05 = "5%"; flagged in the header).
Months where the department has no headcount and no separation are excluded
(headcount zero on both ends has no meaningful rate).
Grain: one row per (year_month, dept) that has headcount or separations.

Deliverable: pipeline/warehouse/analytics/q02.sql (+ q02_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q02
)
===================================================================== */

WITH boundary_options AS (
    SELECT * FROM (VALUES
        ('2026-04-01', '2026-04'),
        ('2026-04-30', '2026-04'),
        ('2026-05-31', '2026-05'),
        ('2026-06-30', '2026-06'),
        ('2026-07-31', '2026-07'),
        ('2026-08-31', '2026-08'),
        ('2026-09-30', '2026-09')
    ) b(b_date, m_key)
),
headcounts AS (
    SELECT b.m_key,
           CASE WHEN DAY(b.b_date) = 1 THEN 'start' ELSE 'end' END AS which_end,
           x.dept_id,
           COUNT(*) AS headcount
    FROM boundary_options b
    CROSS APPLY (
        SELECT de.dept_id
        FROM warehouse.dim_employee de
        WHERE de.hire_date <= b.b_date                                          -- rule 4a
          AND (de.separation_date IS NULL OR de.separation_date > b.b_date)      -- rule 4b
          AND de.valid_from <= b.b_date                                         -- rule 3: dept at that date
          AND COALESCE(de.valid_to, '9999-12-31') >= b.b_date
    ) x
    GROUP BY b.m_key, x.dept_id, CASE WHEN DAY(b.b_date) = 1 THEN 'start' ELSE 'end' END
),
pivoted AS (
    SELECT m_key, dept_id,
           ISNULL(SUM(CASE WHEN which_end = 'start' THEN headcount END), 0) AS hc_start,
           ISNULL(SUM(CASE WHEN which_end = 'end'   THEN headcount END), 0) AS hc_end
    FROM headcounts
    GROUP BY m_key, dept_id
),
separations AS (
    SELECT FORMAT(s.sep_date, 'yyyy-MM') AS m_key, s.dept_id, COUNT(*) AS separations
    FROM (
        SELECT TRY_CAST(e.separation_date AS date) AS sep_date,
               de.dept_id
        FROM warehouse.dim_employee de
        JOIN staging.employees_final e
          ON CAST(e.emp_id AS varchar(20)) = de.emp_id
        WHERE TRY_CAST(e.separation_date AS date) IS NOT NULL
          AND de.valid_from <= TRY_CAST(e.separation_date AS date)
          AND COALESCE(de.valid_to, '9999-12-31') >= TRY_CAST(e.separation_date AS date)
    ) s
    WHERE s.sep_date BETWEEN '2026-04-01' AND '2026-09-30'
    GROUP BY FORMAT(s.sep_date, 'yyyy-MM'), s.dept_id
)
SELECT p.m_key          AS payroll_month,
       p.dept_id,
       dd.dept_name,
       ISNULL(s.separations, 0) AS separations,
       (p.hc_start + p.hc_end) / 2.0 AS avg_headcount,
       CASE WHEN p.hc_start + p.hc_end = 0 THEN NULL
            ELSE CAST(100.0 * ISNULL(s.separations, 0) / ((p.hc_start + p.hc_end) / 2.0) AS decimal(9, 2))
       END AS attrition_pct
FROM pivoted p
JOIN warehouse.dim_department dd ON dd.dept_id = p.dept_id
LEFT JOIN separations s
       ON s.m_key = p.m_key AND s.dept_id = p.dept_id
ORDER BY p.m_key, p.dept_id;
