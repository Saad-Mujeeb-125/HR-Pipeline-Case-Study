/* =====================================================================
STAGE 5 — Question 10 of the case-study PDF (p.6):
  "Employees whose approved Annual leave days in these six months already
   exceed their full-year entitlement."
Business rules:
  rule 16 - only requests approved by BOTH steps and not cancelled were
            expanded to leave days (Stage 2 bullet 7).
  rule 17 - Sundays and plant holidays are NOT leave days (excluded there).
  rule 18 - annual_leave_entitlement is the employee's FULL-YEAR entitlement
            for Annual leave (static attribute, rule 1-consistent).

Definition: SUM of Annual leave days across 2026-04..2026-09 (fact is
restricted to employment anyway) compared to the entitlement; report only
employees whose use EXCEEDS the entitlement.

Grain: one row per employee whose Annual leave overused the entitlement.

Deliverable: pipeline/warehouse/analytics/q10.sql (+ q10_result.csv via
    python -X utf8 pipeline/warehouse/analytics/run_all.py q10
)
===================================================================== */

WITH annual_used AS (
    SELECT CAST(fl.emp_id AS varchar(20)) AS emp_id,
           COUNT(*) AS annual_leave_days
    FROM warehouse.fact_leave_day fl
    WHERE fl.leave_type = 'Annual'
    GROUP BY CAST(fl.emp_id AS varchar(20))
),
current_entitlement AS (   -- rule 18: entitlement is a full-year static attribute
    SELECT emp_id, MAX(COALESCE(annual_leave_entitlement, 0)) AS annual_leave_entitlement
    FROM warehouse.dim_employee
    WHERE is_current = 1
    GROUP BY emp_id
)
SELECT a.emp_id,
       e.full_name,
       ce.annual_leave_entitlement,
       a.annual_leave_days,
       a.annual_leave_days - ce.annual_leave_entitlement AS days_over_entitlement
FROM annual_used a
JOIN current_entitlement ce ON CAST(ce.emp_id AS varchar(20)) = a.emp_id
JOIN warehouse.dim_employee e
  ON e.emp_id = a.emp_id AND e.is_current = 1
WHERE a.annual_leave_days > ce.annual_leave_entitlement
ORDER BY days_over_entitlement DESC, a.emp_id;
