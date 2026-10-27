/* =====================================================================
STAGE 5 — Question 4 of the case-study PDF (p.6):
  "The 10 employees with the most late arrivals, and their department."
Business rules:
  rule 13 - late arrival = check-in more than 10 minutes after shift start;
            counted on Present days that are not Sunday/holiday (exactly the
            rows where fact_attendance_daily.late_minutes > 0, which
            Stage 3 built under rule 13's scope).
Department shown: the employee's department on the LATEST late arrival
(the rule-2/3 department they were in at that date). Ties at the rank-10
boundary are broken deterministically: late_arrivals DESC, emp_id ASC.

Grain: exactly 10 rows (one per employee), 1..10 rank.

Deliverable: pipeline/warehouse/analytics/q04.sql (+ q04_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q04
)
===================================================================== */

WITH by_employee AS (
    SELECT fa.emp_id,
           COUNT(*) AS late_arrivals,
           MAX(fa.work_date) AS last_late_date
    FROM warehouse.fact_attendance_daily fa
    WHERE fa.late_minutes > 0
    GROUP BY fa.emp_id
),
dept_at_latest AS (
    SELECT b.emp_id, b.late_arrivals, de.dept_id, dd.dept_name
    FROM by_employee b
    JOIN warehouse.dim_employee de
      ON de.emp_id = b.emp_id
     AND b.last_late_date >= de.valid_from
     AND b.last_late_date <= COALESCE(de.valid_to, '9999-12-31')
    JOIN warehouse.dim_department dd ON dd.dept_id = de.dept_id
),
ranked AS (
    SELECT d.*,
           ROW_NUMBER() OVER (ORDER BY d.late_arrivals DESC, d.emp_id ASC) AS rank_no
    FROM dept_at_latest d
)
SELECT r.rank_no,
       r.emp_id,
       e.full_name,
       r.dept_id,
       r.dept_name,
       r.late_arrivals
FROM ranked r
LEFT JOIN warehouse.dim_employee e
       ON e.emp_id = r.emp_id AND e.is_current = 1
WHERE r.rank_no <= 10
ORDER BY r.rank_no;
