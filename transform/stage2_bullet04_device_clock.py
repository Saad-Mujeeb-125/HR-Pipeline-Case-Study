"""STAGE 2, bullet 4 of the case-study PDF (p.5):
    "Detect and correct the device whose clock is off. Explain how you found it."
Business rule: rule 11 — "Device clocks can drift."

HOW THE FAULTY DEVICE IS FOUND (evidence printed at runtime, stored in
staging.device_clock_offsets):
  1. For every employee/day take the FIRST punch (check-in) per calendar date.
  2. Join the employee's planned shift for that date (built from
     raw.shift_roster with rule-6 inheritance and rule-5 GEN default).
  3. delta = first-punch time-of-day minus shift start (minutes). NIGHT shift
     is excluded: its punches cross midnight and would muddy the comparison.
  4. Per (device, work_date, shift) compute the MEAN delta (first_punches mean).
  5. RESIDUAL per (work_date, shift) = that device's mean minus the MEDIAN of
     the other three devices on the same day+shift. Using the median of the
     other devices removes plant-wide effects (holidays, lateness waves).
  6. A device whose MONTHLY median residual reaches >= 45 minutes is the faulty
     device; the first month where that happens is the fault month; the first
     work_date whose daily median residual >= 45 is the break date; the hourly
     residuals within that day pin the break time (midnight if all hours are
     faulty). offset_minutes = recorded - real, rounded to a whole hour.

CORRECTION: only punches RECORDED at/after the break timestamp have the offset
subtracted (DATEADD(minute, -offset, punch_ts)); earlier punches keep their
timestamps. Result tables:
  staging.roster_shift_daily    per employee/date planned shift (also used by
                                Stage 3 attendance)
  staging.device_clock_offsets  detected device/break/offset + evidence
  staging.punches_clean         bullet-5 punches with corrected timestamps,
                                clock_corrected flag marks changed rows

Run AFTER stage2_bullet05_punches_dedup_2min.py (needs staging.punches_deduped).
    python -X utf8 pipeline/transform/stage2/stage2_bullet04_device_clock.py
"""
import os
import statistics
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage2Bullet04DeviceClock(PipelineTask):
    """Stage 2 bullet 4 — rule 11 faulty-device detection + clock correction."""

    PERIOD_FROM, PERIOD_TO = "2026-04-01", "2026-09-30"  # case-study window Apr 1 - Sep 30
    FLAG_THRESHOLD_MIN = 45  # monthly median residual at least this large = faulty segment

    SQL_TABLES_READY = """
    SELECT SUM(CASE WHEN t.name = 'employees_final' THEN 1 ELSE 0 END) AS has_employees,
           SUM(CASE WHEN t.name = 'punches_deduped'  THEN 1 ELSE 0 END) AS has_punches
    FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = 'staging' AND t.name IN ('employees_final', 'punches_deduped')
    """

    SQL_ROSTER_DUP_CHECK = """
    SELECT COUNT(*) AS rows_n, COUNT(DISTINCT CONCAT(emp_id, '|', week_start)) AS pairs_n
    FROM raw.shift_roster
    """

    SQL_BUILD_ROSTER_DAILY = """
    IF OBJECT_ID('staging.roster_shift_daily') IS NOT NULL DROP TABLE staging.roster_shift_daily;
    WITH bounds AS (
        SELECT MIN(TRY_CAST(week_start AS date)) AS mn,
               MAX(TRY_CAST(week_start AS date)) AS mx
        FROM raw.shift_roster
    ),
    mondays AS (
        SELECT DATEADD(day, g.value * 7, b.mn) AS week_start
        FROM bounds b
        CROSS APPLY GENERATE_SERIES(0, DATEDIFF(day, b.mn, b.mx) / 7) g
    ),
    r1 AS (
        SELECT emp_id,
               TRY_CAST(week_start AS date) AS week_start,
               shift_code,
               LEAD(TRY_CAST(week_start AS date)) OVER (
                   PARTITION BY emp_id ORDER BY TRY_CAST(week_start AS date)) AS next_start
        FROM raw.shift_roster
    ),
    expanded AS (
        -- rule 6: the same shift repeats on every Monday until the next roster
        -- row starts. One row expands into all the Mondays it covers.
        SELECT r1.emp_id,
               DATEADD(day, g.value * 7, r1.week_start) AS week_start,
               r1.shift_code
        FROM r1
        CROSS APPLY GENERATE_SERIES(
            0,
            CASE WHEN r1.next_start IS NULL
                      THEN DATEDIFF(day, r1.week_start, (SELECT mx FROM bounds)) / 7
                 ELSE DATEDIFF(day, r1.week_start, r1.next_start) / 7 - 1
            END) g
    ),
    emp_weeks AS (
        SELECT e.emp_id, m.week_start,
               x.shift_code AS roster_shift     -- NULL where no (inherited) roster row
        FROM (SELECT DISTINCT emp_id FROM staging.employees_final) e
        CROSS JOIN mondays m
        LEFT JOIN expanded x
               ON x.emp_id    = e.emp_id
              AND x.week_start = m.week_start
    ),
    shift_rows AS (
        -- shift definitions out of the raw shifts.json blob
        SELECT v.shift_code, CAST(v.start_time AS time) AS start_time
        FROM raw.shifts s
        CROSS APPLY OPENJSON(s.json_data, '$.shifts')
            WITH (shift_code varchar(10)  '$.shift_code',
                  start_time   varchar(8) '$.start_time') v
    ),
    workdays AS (
        SELECT ew.emp_id,
               DATEADD(day, w.value, ew.week_start) AS work_date,
               ISNULL(ew.roster_shift, 'GEN') AS shift_code,   -- rule 5: no roster row -> GEN
               CASE WHEN ew.roster_shift IS NULL THEN 0 ELSE 1 END AS is_from_roster
        FROM emp_weeks ew
        CROSS APPLY GENERATE_SERIES(0, 6) w
    )
    SELECT w2.emp_id,
           w2.work_date,
           w2.shift_code,
           s2.start_time,
           w2.is_from_roster
    INTO staging.roster_shift_daily
    FROM workdays w2
    JOIN shift_rows s2 ON s2.shift_code = w2.shift_code
    WHERE w2.work_date BETWEEN '{period_from}' AND '{period_to}';
    """

    # ---------- evidence tables -------------------------------------------------

    SQL_EVIDENCE_BASE = r"""
    IF OBJECT_ID('tempdb..#first_punch') IS NOT NULL DROP TABLE #first_punch;
    -- rule 10 preview: first punch of a calendar date = check-in
    WITH q AS (
        SELECT emp_id, device_id, punch_id,
               CAST(punch_ts AS date) AS punch_date,
               punch_ts AS first_ts,
               ROW_NUMBER() OVER (PARTITION BY emp_id, CAST(punch_ts AS date)
                                  ORDER BY punch_ts, punch_id) AS rn
        FROM {src_table}
    )
    SELECT emp_id, device_id, punch_id, punch_date, first_ts
    INTO #first_punch
    FROM q
    WHERE rn = 1;

    IF OBJECT_ID('tempdb..#dev_means') IS NOT NULL DROP TABLE #dev_means;
    -- mean delta (first punch - shift start) per (device, work_date, shift)
    SELECT f.device_id,
           r.work_date,
           r.shift_code,
           COUNT(*) AS n,
           AVG(CAST(DATEDIFF(minute, r.start_time, CAST(f.first_ts AS time)) AS decimal(9,2))) AS mean_delta
    INTO #dev_means
    FROM #first_punch f
    JOIN staging.roster_shift_daily r
         ON r.emp_id    = f.emp_id
        AND r.work_date = f.punch_date
    WHERE r.shift_code <> 'NIGHT'      -- night punches belong to the previous evening
      AND DATEDIFF(minute, r.start_time, CAST(f.first_ts AS time)) BETWEEN -90 AND 240
    GROUP BY f.device_id, r.work_date, r.shift_code;

    IF OBJECT_ID('tempdb..#residual') IS NOT NULL DROP TABLE #residual;
    -- residual = this device's mean delta minus the median of the OTHER devices
    -- (median of 3 values = their sum - min - max)
    WITH others AS (
        SELECT a.work_date, a.shift_code, a.device_id,
               MIN(b.mean_delta) AS min_o, MAX(b.mean_delta) AS max_o, SUM(b.mean_delta) AS sum_o
        FROM #dev_means a
        JOIN #dev_means b
             ON  b.work_date  = a.work_date
            AND b.shift_code = a.shift_code
            AND b.device_id <> a.device_id
        GROUP BY a.work_date, a.shift_code, a.device_id
    )
    SELECT d.work_date, d.shift_code, d.device_id, d.mean_delta, d.n,
           CAST(d.mean_delta - (o.sum_o - o.min_o - o.max_o) AS decimal(9,2)) AS residual
    INTO #residual
    FROM #dev_means d
    JOIN others o
         ON  o.work_date  = d.work_date
        AND o.shift_code = d.shift_code
        AND o.device_id  = d.device_id;
    """

    SQL_DAILY_RESIDUAL = """
    SELECT work_date,
           CAST(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY residual)
                OVER (PARTITION BY work_date) AS decimal(9,2)) AS med_daily,
           COUNT(*) AS rows_n
    FROM #residual
    WHERE device_id = ?
      AND FORMAT(work_date, 'yyyy-MM') = ?
    GROUP BY work_date, residual
    ORDER BY work_date
    """

    SQL_HOURLY_RESIDUAL_TRUE = """
    SELECT work_date, shift_code, residual, COUNT(*) AS rows_n
    FROM #residual
    WHERE device_id = ?
      AND work_date = ?
    GROUP BY work_date, shift_code, residual
    ORDER BY shift_code, residual
    """

    SQL_CREATE_OFFSETS = """
    IF OBJECT_ID('staging.device_clock_offsets') IS NOT NULL DROP TABLE staging.device_clock_offsets;
    CREATE TABLE staging.device_clock_offsets (
        device_id          varchar(30)  NOT NULL PRIMARY KEY,
        offset_minutes     int          NOT NULL,
        active_from_ts     datetime2(0) NOT NULL,
        break_date         date         NOT NULL,
        flagged_months     varchar(60)  NOT NULL,
        mean_delta_minutes decimal(9,2) NOT NULL,
        note               varchar(400) NOT NULL
    );
    """

    SQL_BUILD_PUNCHES_CLEAN = """
    IF OBJECT_ID('staging.punches_clean') IS NOT NULL DROP TABLE staging.punches_clean;
    SELECT d.punch_id, d.emp_id, d.device_id, d.device_user_id,
           p.punch_time AS punch_time_raw,                 -- original device reading
           DATEADD(minute,
                   CASE WHEN d.punch_ts >= o.active_from_ts AND o.device_id IS NOT NULL
                        THEN -o.offset_minutes ELSE 0 END,
                   d.punch_ts) AS punch_ts,                -- minus offset = real time
           CASE WHEN d.punch_ts >= o.active_from_ts AND o.device_id IS NOT NULL
                THEN 1 ELSE 0 END AS clock_corrected
    INTO staging.punches_clean
    FROM staging.punches_deduped d
    LEFT JOIN staging.device_clock_offsets o ON o.device_id = d.device_id
    JOIN raw.biometric_punches p ON p.punch_id = d.punch_id; -- punch_time text as delivered
    """

    SQL_ROSTER_STATS = """
    SELECT COUNT(*) AS days, SUM(is_from_roster) AS from_roster
    FROM staging.roster_shift_daily
    """

    @staticmethod
    def fmt_min(v):
        sign = "+" if v >= 0 else "-"
        whole = abs(int(v))
        rest = int(round((abs(v) - whole) * 60))
        return f"{sign}{whole}:{rest:02d}"

    # ------------------------- step 2-3: detection ---------------------------

    def _collect_residuals(self, cur, src_table: str):
        """(device -> [(work_date, residual), ...]) from the evidence temp tables."""
        cur.execute(self.SQL_EVIDENCE_BASE.format(src_table=src_table))
        monthly = {}
        for device, work_date, residual, _n in cur.execute(
                "SELECT device_id, work_date, residual, n FROM #residual"):
            monthly.setdefault(device, []).append((work_date, float(residual)))
        return monthly

    def _report_monthly_evidence(self, monthly):
        """Monthly MEDIAN residual per device; returns flagged months per device."""
        print("\n--- Evidence: monthly MEDIAN residual (device mean minus other devices' median) ---")
        device_flag_months = {}
        for device in sorted(monthly):
            by_month = {}
            for work_date, res in monthly[device]:
                by_month.setdefault(work_date.strftime("%Y-%m"), []).append(res)
            meds = {ym: statistics.median(vals) for ym, vals in sorted(by_month.items())}
            print(f"  {device}")
            for ym, med in meds.items():
                flag = " <-- FAULT" if med >= self.FLAG_THRESHOLD_MIN else ""
                print(f"    {ym}  median residual {self.fmt_min(med):>8}  ({len(by_month[ym]):>2} days){flag}")
            device_flag_months[device] = [ym for ym, med in meds.items() if med >= self.FLAG_THRESHOLD_MIN]
        return device_flag_months

    def _pick_culprit(self, device_flag_months):
        bad = {d for d, m in device_flag_months.items() if m}
        if not bad:
            sys.exit("ABORT: no device shows a faulty segment — no drift found (unexpected per the PDF).")
        if len(bad) > 1:
            sys.exit(f"ABORT: {len(bad)} devices flagged; methodology assumes exactly one faulty device.")
        culprit = bad.pop()
        flagged_ym = device_flag_months[culprit]
        onset_ym = flagged_ym[0]
        print(f"\nFAULTY DEVICE = {culprit}; months flagged: {', '.join(flagged_ym)}; onset month {onset_ym}.")
        return culprit, flagged_ym, onset_ym

    def _find_break_date(self, cur, culprit, onset_ym):
        """First work_date in the onset month with daily median residual >= threshold."""
        daily = cur.execute(self.SQL_DAILY_RESIDUAL, culprit, onset_ym).fetchall()
        daily = [(d, float(v)) for d, v, *_ in daily]
        bad_days = [d for d, med in sorted(daily) if med >= self.FLAG_THRESHOLD_MIN]
        if not bad_days:
            sys.exit("ABORT: onset month flagged but no faulty day found within it.")
        break_date = bad_days[0]
        print(f"Break date = {break_date} (first day whose residual median >= {self.FLAG_THRESHOLD_MIN} min).")
        print("Residuals for that day, per shift:")
        for row in cur.execute(self.SQL_HOURLY_RESIDUAL_TRUE, culprit, break_date):
            print(f"  {row[1]:<5}  {row[0]}  mean={self.fmt_min(row[2])}")
        return break_date

    # ------------------------- step 4-6: correction ---------------------------

    def _persist_offset(self, cur, culprit, flagged_ym, break_date, resid_fault, offset_min):
        """Persist the finding (recorded = real + offset; correction = recorded - offset)."""
        cur.execute(self.SQL_CREATE_OFFSETS)
        cur.execute(
            "INSERT INTO staging.device_clock_offsets"
            " (device_id, offset_minutes, active_from_ts, break_date, flagged_months,"
            "  mean_delta_minutes, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
            culprit, offset_min, break_date, break_date, ",".join(flagged_ym),
            round(statistics.mean(resid_fault), 2),
            "Found by comparing each device's mean first-punch delta vs planned shift start"
            " against the median of the other 3 devices (same day, same shift), rule 6+5."
            f" {culprit} clocks +{offset_min} min from {break_date} (recorded = real + offset).")
        print("staging.device_clock_offsets written with evidence row.")

    @staticmethod
    def _post_correction_evidence(cur, monthly_culprit_rows, break_date):
        """Verification: recompute evidence on corrected timestamps."""
        post_monthly = {}
        for device, work_date, residual, _ in cur.execute(
                "SELECT device_id, work_date, residual, n FROM #residual"):
            post_monthly.setdefault(device, []).append((work_date, float(residual)))
        print("\n--- AFTER correction: fault-period median residual per device ---")
        peak = {}
        for device, rows_ in post_monthly.items():
            post_vals = [r for d, r in rows_ if d >= break_date]
            if post_vals:
                peak[device] = statistics.median(post_vals)
        for d, m in sorted(peak.items()):
            mark = "" if abs(m) < Stage2Bullet04DeviceClock.FLAG_THRESHOLD_MIN else "  <-- STILL FAULTY?"
            print(f"  {d:<13} median residual {Stage2Bullet04DeviceClock.fmt_min(m):>8}{mark}")
        still = [d for d, m in peak.items() if abs(m) >= Stage2Bullet04DeviceClock.FLAG_THRESHOLD_MIN]
        if still:
            sys.exit(f"ABORT: {still} still faulty after correction — offset window is wrong.")

    # ------------------------- public entry -----------------------------------

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        try:
            # Guards: prerequisites from earlier bullets
            deps_ready = cur.execute(self.SQL_TABLES_READY).fetchone()
            if not deps_ready[0] or not deps_ready[1]:
                sys.exit("ABORT: run stage2_bullet02 (employees_final) and stage2_bullet05 (punches_deduped) first.")
            dup_check = cur.execute(self.SQL_ROSTER_DUP_CHECK).fetchone()
            if dup_check[0] != dup_check[1]:
                sys.exit(f"ABORT: shift_roster has {dup_check[0] - dup_check[1]} duplicate (emp_id, week_start) rows.")

            # 1. employee/day shift schedule (rule 6 inheritance; rule 5 GEN default)
            cur.execute(self.SQL_BUILD_ROSTER_DAILY.format(
                period_from=self.PERIOD_FROM, period_to=self.PERIOD_TO))
            total_days, inherited = cur.execute(self.SQL_ROSTER_STATS).fetchone()
            cn.commit()   # roster build is expensive: keep it even if later steps fail
            print(f"staging.roster_shift_daily: {total_days:,} employee-days "
                  f"({total_days - inherited:,} defaulted to GEN, {inherited:,} from roster)")

            # 2. evidence: monthly median residual per device (rows from punches_deduped)
            monthly = self._collect_residuals(cur, "staging.punches_deduped")
            device_flag_months = self._report_monthly_evidence(monthly)
            culprit, flagged_ym, onset_ym = self._pick_culprit(device_flag_months)

            # 3. break date: first work_date in the onset month whose residual is faulty
            break_date = self._find_break_date(cur, culprit, onset_ym)

            resid_fault = [r for d, r in monthly[culprit] if d >= break_date]
            offset_min = int(round(statistics.median(resid_fault) / 60.0) * 60)
            print(f"\nMean delta in fault period: {self.fmt_min(statistics.mean(resid_fault))}"
                  f"  -> offset (round to whole hour) = {offset_min} min")
            if offset_min == 0:
                sys.exit("ABORT: resolved offset rounds to zero — check threshold/method.")

            # 4. persist the finding, then 5. build the corrected punch table
            self._persist_offset(cur, culprit, flagged_ym, break_date, resid_fault, offset_min)
            cur.execute(self.SQL_BUILD_PUNCHES_CLEAN)
            fixed_rows = cur.execute("SELECT COUNT(*) FROM staging.punches_clean WHERE clock_corrected = 1").fetchval()
            print(f"staging.punches_clean     : rows with timestamps corrected: {fixed_rows:,}")

            # 6. verification: recompute evidence on corrected timestamps
            cur.execute(self.SQL_EVIDENCE_BASE.format(src_table="staging.punches_clean"))
            self._post_correction_evidence(cur, monthly[culprit], break_date)

            cn.commit()
        except Exception:
            cn.rollback()
            raise
        cur.execute("DROP TABLE #residual; DROP TABLE #dev_means; DROP TABLE #first_punch")

        deduped_total = cur.execute("SELECT COUNT(*) FROM staging.punches_deduped").fetchval()
        clean_total = cur.execute("SELECT COUNT(*) FROM staging.punches_clean").fetchval()
        print()
        print(f"RECONCILIATION: staging.punches_deduped {deduped_total:,} = staging.punches_clean {clean_total:,}"
              f"  ({fixed_rows:,} clock-corrected)  {'OK' if deduped_total == clean_total else 'MISMATCH!'}")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage2Bullet04DeviceClock().run())
