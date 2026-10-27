# CFO findings — Indus Weave Textiles (Apr–Sep 2026 payroll audit)

Prepared from the `IndusWeaveHR` warehouse (`warehouse.dim_*` / `warehouse.fact_*`), built by the
pipeline in `pipeline/` from the six delivered HCM exports. Every number below is a pipeline query
result — the SQL is quoted per finding and the matching result file sits next to it
(`pipeline/warehouse/analytics/<qXX>_result.csv`). To re-run all of them from scratch:

```
python -X utf8 pipeline/run_pipeline.py          # ~5 min, ends with 68 data-quality checks, 0 blocking
```

Business rules cited (`data/data_dictionary.md`): rule 20 (paid OT = payroll OVERTIME units),
rule 4 (separation = last day worked), rule 21 (cost = EARNING lines), rule 16/17/18
(leave approvals and entitlements).

---

## Finding 1 — Stitching (D20) is paid 56% more overtime than the badge data supports

**The number.** Over the six months, D20 Stitching was **paid 7,659.0 overtime hours**
(payroll OVERTIME units) while attendance computation from biometric punches supports only
**4,902.0 hours** — an overpayment of **2,757 hours (+56.24%)**. D20 is the *only* department
above the 15% threshold (the case study's flag). At the rates actually paid, D20 received
**PKR 3,771,337** in OT across Apr–Sep, the largest OT bill of any department
(next: Weaving PKR 1,823,707) — so this is not a rounding artefact, it is the biggest OT line in the plant.

**Evidence** — `q06.sql` (result: `q06_result.csv`, 1 row):

```sql
WITH computed AS (
    SELECT fa.dept_id, SUM(fa.ot_hours) AS computed_ot_hours      -- rules 14–15, from punches
    FROM warehouse.fact_attendance_daily fa
    GROUP BY fa.dept_id
),
paid AS (
    SELECT fp.dept_id, SUM(fp.units) AS paid_ot_hours             -- rule 20, from payroll
    FROM warehouse.fact_payroll_line fp
    WHERE fp.component = 'OVERTIME'
    GROUP BY fp.dept_id
)
SELECT cn.dept_id, dd.dept_name,
       cn.computed_ot_hours, ISNULL(p.paid_ot_hours, 0) AS paid_ot_hours,
       100.0 * (ISNULL(p.paid_ot_hours,0) - cn.computed_ot_hours) / cn.computed_ot_hours AS over_computed_pct
FROM computed cn JOIN paid p ON p.dept_id = cn.dept_id
JOIN warehouse.dim_department dd ON dd.dept_id = cn.dept_id
WHERE ISNULL(p.paid_ot_hours, 0) > cn.computed_ot_hours * 1.15      -- the PDF's threshold
ORDER BY over_computed_pct DESC;
```

Corroborating context (built during the dashboard, D026): D20's *approved* overtime requests
(7,656 h) match what was *paid* (7,659 units) — the gap is not in approvals vs payment, it is
between **paid units and computed hours**. A plausible but unproven mechanism is pay-figure
entry (units typed into payroll); the line-by-line audit in action 1 is what would confirm it.

**Recommended action.**

1. Audit D20's six payroll months line by line: compare each OVERTIME line's `units` against
   the employee's clock data for that month.
2. Before each payroll run, print the per-department projected OT (units) next to computed
   hours (this exact q06 query) and require an explanation whenever a department exceeds
   computed by >15%.
3. The overpayment is **36.0% of D20's OT bill (≈ PKR 1.36M over six months)** — hours no
   badge ever recorded. The cause (e.g. negotiated off-the-clock hours) is a hypothesis until
   the audit in action 1 reports.

---

## Finding 2 — Five employees were paid PKR 1.95M after separation

**The number.** **5 employees, 21 payroll months, PKR 1,948,000** in earnings paid for months
strictly AFTER their separation month (rule 4: separation = last day worked; the separation
month itself is legitimate). Worst case: **E10471 Umair Baloch, separated 2026-04-23, was paid
5 further months (May–Sep) totalling PKR 660,000**. Full list (`q08_result.csv`):

| emp_id | employee | separated | months paid after | PKR paid after |
|---|---|---|---|---|
| E10471 | Umair Baloch | 2026-04-23 | 5 (May–Sep) | **660,000** |
| E11222 | Naveed Ansari | 2026-05-16 | 4 (Jun–Sep) | 418,100 |
| E10332 | Amna Awan | 2026-05-14 | 4 (Jun–Sep) | 322,000 |
| E10989 | Tariq Jatoi | 2026-05-18 | 4 (Jun–Sep) | 294,100 |
| E10295 | Sohail Hussain | 2026-05-11 | 4 (Jun–Sep) | 253,800 |

**Evidence** — `q08.sql` (result: `q08_result.csv`, 5 rows). Core comparison:

```sql
WHERE p.payroll_month > FORMAT(m.sep_date, 'yyyy-MM')   -- strictly AFTER separation month
-- earnings = EARNING lines only (rule 21)
```

**Cross-check that makes it airtight** — `q07.sql` (`q07_result.csv`, 21 rows) asks a different
question ("paid in a month with ZERO attendance, i.e. no employment day at all") and surfaces
exactly the same **21 (employee, month) rows**. Two independent queries — attendance anti-join
and separation-date comparison — agree perfectly, and the DQ suite (22 PK + 18 FK + 13
reconciliation checks, 0 blocking) verifies the underlying numbers flow exactly from the raw
exports.

**Recommended action.**

1. Immediate: block all 5 from the next payroll run; issue recovery letters for the 21 months
   (PKR 1,948,000); legal review for E10471 (5 months is not an oversight window).
2. Systemic: the payroll trigger must require `payroll_month <= separation_month` in the
   HCM, and offboarding (separation date entry) must be a same-day payroll-blocking event,
   not an HR admin afterthought.
3. Process: add the q07 "money with no hours" check to every monthly close — it is one
   query, and it would have caught E10471 at the May close (PKR 132,000) and the other four
   at the June close: monthly losses of PKR 132,000 (May) and PKR 454,000 (June), instead of
   PKR 1,948,000 (verified per month against `warehouse.fact_payroll_line`).

---

## Finding 3 — 20 employees already burned through a full year's annual leave in six months

**The number.** **20 employees** used more APPROVED Annual leave days in Apr–Sep (six months)
than their full-year entitlement (rule 18). Extreme cases:

| emp_id | employee | entitlement (yr) | used (6 mo) | over |
|---|---|---|---|---|
| E10770 | Danish Iqbal | 14 | 28 | **14** (2× entitlement) |
| E10826 | Ahmed Mirza | 14 | 27 | 13 |
| E10748 | Asif Ansari | 14 | 25 | 11 |
| E10025 | Arif Gill | 14 | 24 | 10 |
| E11071 | Ahmed Hussain | 14 | 23 | 9 |

…15 more in `q10_result.csv` (19 of the 20 carry the standard 14-day entitlement; Sajid
Abbasi E10827 is on 20 and still used 27).

**Evidence** — `q10.sql` (result: `q10_result.csv`, 20 rows). Only rule-16-approved,
rule-17-filtered days count (Sundays/holidays excluded — the generous reading):

```sql
WHERE a.annual_leave_days > ce.annual_leave_entitlement   -- 6-month use > FULL-YEAR entitlement
```

**Recommended action.**

1. Audit the approval workflow for those 20: approvals exceeding entitlement mean line
   managers approved leave the system should have stopped (or balances are simply not
   checked today — both fixable with one gate).
2. Enforce the balance check in the approval UI: a request that pushes annual use past
   entitlement must escalate to leave policy, not silently approve.

---

## How these three findings were produced

Stages 2–6 of the pipeline clean and load the six exports (345,280 punches reconciled to the
row, 345,280 = 322,143 kept + 23,137 rejected; device-clock drift DEV-SITE-01 +60 min
corrected; leave flattened per rules 16–17), then the star schema (`warehouse.*`) feeds the ten
case-study queries. Data-quality gate: 68 automated checks in `quality.dq_results`, 0 blocking
(1 known source quirk reported as EXPECTED and documented). Nothing in this document touches
the source files — every figure is reproducible from the quoted queries.
