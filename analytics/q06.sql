/* =====================================================================
STAGE 5 — Question 6 of the case-study PDF (p.6):
  "Departments where paid overtime exceeds computed overtime by more than 15%."
Business rules / sources (identical to q05):
  paid     = payroll OVERTIME line units (rule 20), whole six months.
  computed = fact_attendance_daily.ot_hours (rules 14-15), whole six months.
Condition: paid > computed * 1.15. Departments with 0 computed hours cannot
have a percentage comparison and are excluded.

Grain: one row per qualifying department.

Deliverable: pipeline/warehouse/analytics/q06.sql (+ q06_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q06
)
===================================================================== */

WITH computed AS (
    SELECT fa.dept_id, SUM(fa.ot_hours) AS computed_ot_hours
    FROM warehouse.fact_attendance_daily fa
    GROUP BY fa.dept_id
),
paid AS (
    SELECT fp.dept_id, SUM(fp.units) AS paid_ot_hours
    FROM warehouse.fact_payroll_line fp
    WHERE fp.component = 'OVERTIME'
    GROUP BY fp.dept_id
)
SELECT cn.dept_id,
       dd.dept_name,
       CAST(cn.computed_ot_hours AS decimal(10, 2)) AS computed_ot_hours,
       CAST(ISNULL(p.paid_ot_hours, 0) AS decimal(10, 2)) AS paid_ot_hours,
       CAST(100.0 * (ISNULL(p.paid_ot_hours, 0) - cn.computed_ot_hours) / cn.computed_ot_hours
            AS decimal(9, 2)) AS over_computed_pct
FROM computed cn
JOIN paid p ON p.dept_id = cn.dept_id
JOIN warehouse.dim_department dd ON dd.dept_id = cn.dept_id
WHERE ISNULL(p.paid_ot_hours, 0) > cn.computed_ot_hours * 1.15
ORDER BY over_computed_pct DESC;
