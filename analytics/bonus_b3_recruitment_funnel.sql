/* =====================================================================
BONUS TASK B3 of the case-study PDF (p.7):
  "Recruitment funnel from applications.csv: conversion and median days
   at each stage."

Source: raw.applications (3,835 rows; 1,400 candidates x 30 job reqs; one
row per candidate-stage-change with the change date). The CSV is read as
delivered text, so stages/dates are converted here, NOT in Stage 1.

Funnel definition (written down because the CSV has no explicit definitions):
  pipe  = Applied -> Screened -> Interviewed -> Offered -> Hired
  exits = Rejected (possible after any stage) and Offer Declined (after Offer)
  reached(stage)      = DISTINCT applications having a row with that stage
  conversion is ALWAYS relative to the immediately previous stage in the
  funnel (not cumulative), e.g. Offered/Interviewed.
  median days = PERCENTILE_CONT(0.5) of DATEDIFF(day, previous stage date,
  this stage date) over applications that reached BOTH stages. skew-robust,
  which matters for 'days to Hired'.

Result: one row per funnel stage (seq 1-5) + two exit rows + one summary
row (seq 0 = overall Applied->Hired yield). NULL conversion/median simply
means "no previous stage" (Applied) or "not part of the pipe" (exits).

Run:  python -X utf8 pipeline/analytics/bonus_b3_recruitment_funnel.py
===================================================================== */
WITH per_app AS (
    SELECT
        a.application_id,
        TRY_CONVERT(date, MIN(CASE WHEN a.stage = 'Applied'     THEN a.stage_date END), 23) AS applied_dt,
        TRY_CONVERT(date, MIN(CASE WHEN a.stage = 'Screened'    THEN a.stage_date END), 23) AS screened_dt,
        TRY_CONVERT(date, MIN(CASE WHEN a.stage = 'Interviewed' THEN a.stage_date END), 23) AS interviewed_dt,
        TRY_CONVERT(date, MIN(CASE WHEN a.stage = 'Offered'     THEN a.stage_date END), 23) AS offered_dt,
        TRY_CONVERT(date, MIN(CASE WHEN a.stage = 'Hired'       THEN a.stage_date END), 23) AS hired_dt
    FROM raw.applications a
    GROUP BY a.application_id
),
/* every transition as one row: (funnel seq of the TO stage, days taken) —
   seq 0 = the overall Applied->Hired journey */
trans AS (
    SELECT 2 AS seq, DATEDIFF(day, applied_dt, screened_dt)   AS d
    FROM per_app WHERE screened_dt IS NOT NULL AND applied_dt IS NOT NULL
    UNION ALL
    SELECT 3, DATEDIFF(day, screened_dt, interviewed_dt)
    FROM per_app WHERE interviewed_dt IS NOT NULL AND screened_dt IS NOT NULL
    UNION ALL
    SELECT 4, DATEDIFF(day, interviewed_dt, offered_dt)
    FROM per_app WHERE offered_dt IS NOT NULL AND interviewed_dt IS NOT NULL
    UNION ALL
    SELECT 5, DATEDIFF(day, offered_dt, hired_dt)
    FROM per_app WHERE hired_dt IS NOT NULL AND offered_dt IS NOT NULL
    UNION ALL
    SELECT 0, DATEDIFF(day, applied_dt, hired_dt)
    FROM per_app WHERE hired_dt IS NOT NULL AND applied_dt IS NOT NULL
),
med0 AS (              -- percentile is a window function: no GROUP BY here,
    SELECT seq, d,     -- every row gets the median of its whole seq group
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY d) OVER () AS day_median
    FROM trans
),
med AS (
    SELECT seq, COUNT(*) AS both_n, MIN(day_median) AS day_median
    FROM med0
    GROUP BY seq
)
SELECT
    f.seq,
    f.stage,
    f.reached,
    CAST(100.0 * f.reached / NULLIF(f.prev_reached, 0)
         AS decimal(5,2))                                          AS conversion_from_prev_pct,
    m.both_n                                                 AS day_median_n,
    CAST(m.day_median AS decimal(6,1))                       AS median_days_from_prev
FROM (
    SELECT 1 AS seq, 'Applied'         AS stage,
           COUNT(*) AS reached, COUNT(*) AS prev_reached
    FROM per_app WHERE applied_dt IS NOT NULL
    UNION ALL
    SELECT 2, 'Screened', COUNT(*), (SELECT COUNT(*) FROM per_app WHERE applied_dt IS NOT NULL)
    FROM per_app WHERE screened_dt IS NOT NULL
    UNION ALL
    SELECT 3, 'Interviewed', COUNT(*), (SELECT COUNT(*) FROM per_app WHERE screened_dt IS NOT NULL)
    FROM per_app WHERE interviewed_dt IS NOT NULL
    UNION ALL
    SELECT 4, 'Offered', COUNT(*), (SELECT COUNT(*) FROM per_app WHERE interviewed_dt IS NOT NULL)
    FROM per_app WHERE offered_dt IS NOT NULL
    UNION ALL
    SELECT 5, 'Hired', COUNT(*), (SELECT COUNT(*) FROM per_app WHERE offered_dt IS NOT NULL)
    FROM per_app WHERE hired_dt IS NOT NULL
    UNION ALL
    SELECT 0, 'ALL Applied->Hired', (SELECT COUNT(*) FROM per_app WHERE hired_dt IS NOT NULL),
           (SELECT COUNT(*) FROM per_app WHERE applied_dt IS NOT NULL)
    UNION ALL
    /* exits are context, not pipe stages (no conversion: prev = NULL) */
    SELECT -1, 'exit: Rejected', COUNT(DISTINCT application_id), 0
    FROM raw.applications WHERE stage = 'Rejected'
    UNION ALL
    SELECT -2, 'exit: Offer Declined', COUNT(DISTINCT application_id), 0
    FROM raw.applications WHERE stage = 'Offer Declined'
) f
LEFT JOIN med m ON m.seq = f.seq
ORDER BY f.seq;
