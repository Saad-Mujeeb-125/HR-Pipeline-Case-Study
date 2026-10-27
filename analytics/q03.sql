/* =====================================================================
STAGE 5 — Question 3 of the case-study PDF (p.6):
  "Absenteeism rate by plant and month, excluding approved leave."
Business rules:
  rule 12 - attendance statuses; Scheduled work days are employment days that
            are neither Weekly Off (Sunday) nor a plant Holiday. Approved
            leave days are excluded from BOTH sides of the ratio per the
            question wording ("excluding approved leave").
  rule 16 - only rule-16-approved leave became leave days in Stage 2 bullets
            6-7, so the On-Leave exclusions are exact.

Definition fixed in this query:
  expected workdays = rows with status Present / Missing Punch / Absent
      (a Missing Punch day is still a day the employee was expected to work).
  absent days = rows with status = 'Absent'.
  absenteeism rate = absent / expected, reported as percentage (2 dp).
Grain: one row per (plant, year_month) - four plants x six months.

Deliverable: pipeline/warehouse/analytics/q03.sql (+ q03_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q03
)
===================================================================== */

WITH monthly AS (
    SELECT fa.plant,
           FORMAT(fa.work_date, 'yyyy-MM') AS payroll_month,
           SUM(CASE WHEN fa.status IN ('Present', 'Missing Punch', 'Absent') THEN 1 ELSE 0 END) AS expected_days,
           SUM(CASE WHEN fa.status = 'Absent' THEN 1 ELSE 0 END)                              AS absent_days
    FROM warehouse.fact_attendance_daily fa
    GROUP BY fa.plant, FORMAT(fa.work_date, 'yyyy-MM')
)
SELECT m.payroll_month,
       m.plant,
       m.absent_days,
       m.expected_days,
       CAST(100.0 * m.absent_days / m.expected_days AS decimal(6, 2)) AS absenteeism_pct
FROM monthly m
ORDER BY m.payroll_month, m.plant;
