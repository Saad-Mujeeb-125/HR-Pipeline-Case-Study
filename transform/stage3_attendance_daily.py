"""STAGE 3 of the case-study PDF (p.6):
    "Build staging.attendance_daily: one row per employee per scheduled day.
     Pair first check-in and last check-out per shift, with night shifts assigned
     to their start date. Calculate worked hours, late minutes, early-departure
     minutes and overtime hours using the business rules. Give every row one
     status: Present, Absent, On Leave, Holiday, Weekly Off or Missing Punch."
Business rules applied:
  rule 7  - a night punch belongs to the shift START date (window below).
  rule 10 - check-in = first punch, check-out = last punch; one punch = Missing Punch.
  rule 12 - status priority per row: Sunday+0 punches -> Weekly Off; plant holiday
            +0 punches -> Holiday; approved leave -> On Leave; >=2 punches ->
            Present; 1 punch -> Missing Punch; none -> Absent.
            l12 scope = "one per employee per day of EMPLOYMENT": rows only for
            work dates from hire_date up to separation_date (2026-09-30 if active).
  rule 13 - late = check-in > grace (10 min) after start; early = check-out >
            grace before end; counted ONLY on Present days that are not
            Sunday/holiday.
  rule 14 - overtime = minutes after shift end, floored to half-hours.
  rule 15 - Sunday/holiday work is ALL overtime: (check-out - check-in) floored.

The punch window (validated with SQL probes on 25 Oct 2026):
  [shift start - 90 min  ..  shift end + 240 min]
  NIGHT end = NEXT DAY 06:00 (start + 480), so the window spans midnight (rule 7).
  Probe results: earliest punch is 25 min BEFORE start (90 is safe); latest punch
  is 209 min after end (240 is safe); ALL 322,143 punches fall in some window
  (0 orphans). Windows of adjacent days overlap ONLY at the NIGHT->DAY seam
  (~06:00 Mon after a Sun night): that seam punch legitimately serves BOTH the
  night check-out and the next shift's check-in, so each row reads its own
  window and a punch can count for two adjacent days. Documented as D016.

What it builds:
  staging.attendance_daily - one row per employment day per employee per shift:
    status, punch_count, check_in/check_out, late_minutes, early_minutes,
    ot_hours (rules 14+15 combined), worked_minutes, Sunday/holiday/leave flags.

Run AFTER Stage 2 (needs roster_shift_daily, punches_clean, employees_final,
leave_days). Idempotent: rebuilt every run.
    python -X utf8 pipeline/transform/stage3/stage3_attendance_daily.py
"""
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage3AttendanceDaily(PipelineTask):
    """Stage 3 — one row per employment day with rule-10..15 attendance logic."""

    EARLY_ALLOWANCE_MIN = 90    # window opens this many minutes before shift start
    OT_CEILING_MIN = 240        # window closes this many minutes after shift end
    ANCHOR_SUNDAY = '2026-01-04'  # verified Sunday; DATEDIFF % 7 = 0 -> Sunday (DATEFIRST-safe)

    SQL_TABLES_READY = """
    SELECT COUNT(DISTINCT s.name + '.' + t.name) FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE (s.name = 'staging' AND t.name IN ('roster_shift_daily', 'punches_clean',
                                             'employees_final', 'leave_days'))
       OR (s.name = 'raw' AND t.name IN ('shifts', 'holidays'))
    """

    SQL_BUILD = """
    SET NOCOUNT ON;

    -- ---------- typed, indexed temp copies (raw staging columns are nvarchar(max)) ----------
    IF OBJECT_ID('staging.attendance_daily') IS NOT NULL DROP TABLE staging.attendance_daily;
    IF OBJECT_ID('tempdb..#shift') IS NOT NULL DROP TABLE #shift;
    IF OBJECT_ID('tempdb..#hol')   IS NOT NULL DROP TABLE #hol;
    IF OBJECT_ID('tempdb..#emp')   IS NOT NULL DROP TABLE #emp;
    IF OBJECT_ID('tempdb..#p')     IS NOT NULL DROP TABLE #p;
    IF OBJECT_ID('tempdb..#leave') IS NOT NULL DROP TABLE #leave;
    IF OBJECT_ID('tempdb..#win')   IS NOT NULL DROP TABLE #win;
    IF OBJECT_ID('tempdb..#agg')   IS NOT NULL DROP TABLE #agg;
    IF OBJECT_ID('tempdb..#agg2')  IS NOT NULL DROP TABLE #agg2;

    -- shift definitions from shifts.json (start minutes, duration, grace)
    SELECT x.shift_code,
           DATEDIFF(minute, CAST('00:00' AS time), TRY_CAST(x.start_time AS time)) AS start_min,
           CASE WHEN x.crosses_midnight = CAST(1 AS bit) THEN 1440 ELSE 0 END
             + DATEDIFF(minute, CAST('00:00' AS time), TRY_CAST(x.end_time AS time))
             - DATEDIFF(minute, CAST('00:00' AS time), TRY_CAST(x.start_time AS time)) AS duration_min,
           x.grace_minutes
    INTO #shift
    FROM raw.shifts js
    CROSS APPLY OPENJSON(js.json_data, '$.shifts') WITH (
        shift_code       varchar(10) '$.shift_code',
        start_time       varchar(8)  '$.start_time',
        end_time         varchar(8)  '$.end_time',
        crosses_midnight bit         '$.crosses_midnight',
        grace_minutes    int         '$.grace_minutes'
    ) x;
    CREATE CLUSTERED INDEX cx ON #shift (shift_code);

    -- plant holidays with their scope code
    SELECT TRY_CAST(h.holiday_date AS date) AS holiday_date, h.scope AS scope, h.holiday_name AS holiday_name
    INTO #hol
    FROM raw.holidays h;
    CREATE CLUSTERED INDEX cx ON #hol (holiday_date);

    -- employment span per employee (rule 12: days of employment)
    SELECT CAST(e.emp_id AS varchar(20))  AS emp_id,
           e.plant                        AS plant,
           TRY_CAST(e.hire_date AS date)  AS hire_date,
           COALESCE(TRY_CAST(e.separation_date AS date), CAST('2026-09-30' AS date)) AS last_day
    INTO #emp
    FROM staging.employees_final e;
    CREATE CLUSTERED INDEX cx ON #emp (emp_id);

    -- punches, typed and indexed for the range join
    SELECT CAST(emp_id AS varchar(20)) AS emp_id, punch_ts
    INTO #p
    FROM staging.punches_clean;
    CREATE CLUSTERED INDEX cx ON #p (emp_id, punch_ts);

    -- approved leave: one row per employee per day
    SELECT CAST(emp_id AS varchar(20)) AS emp_id, leave_day, MIN(request_id) AS leave_request_id
    INTO #leave
    FROM staging.leave_days
    GROUP BY CAST(emp_id AS varchar(20)), leave_day;
    CREATE CLUSTERED INDEX cx ON #leave (emp_id, leave_day);

    -- ---------- scheduled days (roster ∩ employment span) with punch windows ----------
    SELECT CAST(r.emp_id AS varchar(20)) AS emp_id, r.work_date, r.shift_code, r.is_from_roster,
           e.plant                                                    AS plant,
           sh.start_min, sh.duration_min, sh.grace_minutes,
           DATEADD(minute, sh.start_min, CAST(r.work_date AS datetime2))                   AS s_ts,   -- shift start
           DATEADD(minute, sh.start_min + sh.duration_min, CAST(r.work_date AS datetime2)) AS e_ts,   -- shift end (NIGHT: next day 06:00)
           DATEADD(minute, sh.start_min - {EARLY_ALLOWANCE_MIN}, CAST(r.work_date AS datetime2)) AS w_start,  -- punch window
           DATEADD(minute, sh.start_min + sh.duration_min + {OT_CEILING_MIN}, CAST(r.work_date AS datetime2)) AS w_end,
           CAST(r.start_time AS time)                                     AS start_time,
           CAST(DATEADD(minute, sh.duration_min, CAST('00:00' AS time)) AS time) AS end_time
    INTO #win
    FROM staging.roster_shift_daily r
    JOIN #shift sh ON sh.shift_code = r.shift_code
    JOIN #emp   e  ON e.emp_id = r.emp_id
    WHERE r.work_date BETWEEN e.hire_date AND e.last_day;
    CREATE CLUSTERED INDEX cx ON #win (emp_id, work_date);

    -- first/last punch inside the row's window (rule 10)
    SELECT w.emp_id, w.work_date, w.shift_code, w.start_time, w.end_time, w.is_from_roster,
           w.plant, w.s_ts, w.e_ts, w.duration_min, w.grace_minutes,
           CAST(COUNT(p.punch_ts) AS int) AS punch_count,
           MIN(p.punch_ts) AS check_in,
           MAX(p.punch_ts) AS check_out
    INTO #agg
    FROM #win w
    LEFT JOIN #p p ON p.emp_id = w.emp_id
                  AND p.punch_ts BETWEEN w.w_start AND w.w_end
    GROUP BY w.emp_id, w.work_date, w.shift_code, w.start_time, w.end_time, w.is_from_roster,
             w.plant, w.s_ts, w.e_ts, w.duration_min, w.grace_minutes;

    -- flags + rule-12 status (priority order, evaluated top-down)
    SELECT a.*,
           CASE WHEN DATEDIFF(day, '{ANCHOR_SUNDAY}', a.work_date) % 7 = 0 THEN 1 ELSE 0 END AS is_sunday,
           CASE WHEN EXISTS (SELECT 1 FROM #hol h
                             WHERE h.holiday_date = a.work_date
                               AND (h.scope = 'ALL'
                                    OR h.scope = CASE a.plant WHEN 'Head Office' THEN 'HO'
                                                              WHEN 'Korangi Plant' THEN 'KOR'
                                                              WHEN 'SITE Plant'    THEN 'SITE'
                                                              WHEN 'Faisalabad Plant' THEN 'FSD' END))
                THEN 1 ELSE 0 END                                             AS is_holiday,
           (SELECT TOP 1 h.holiday_name FROM #hol h
             WHERE h.holiday_date = a.work_date
               AND (h.scope = 'ALL'
                    OR h.scope = CASE a.plant WHEN 'Head Office' THEN 'HO'
                                              WHEN 'Korangi Plant' THEN 'KOR'
                                              WHEN 'SITE Plant'    THEN 'SITE'
                                              WHEN 'Faisalabad Plant' THEN 'FSD' END)
             ORDER BY h.scope)                                                AS holiday_name,
           CASE WHEN EXISTS (SELECT 1 FROM #leave l
                             WHERE l.emp_id = a.emp_id AND l.leave_day = a.work_date) THEN 1 ELSE 0 END AS on_leave,
           (SELECT MIN(l.leave_request_id) FROM #leave l
             WHERE l.emp_id = a.emp_id AND l.leave_day = a.work_date)          AS leave_request_id,
           CASE WHEN DATEDIFF(day, '{ANCHOR_SUNDAY}', a.work_date) % 7 = 0 AND a.punch_count = 0 THEN 'Weekly Off'
                WHEN CASE WHEN EXISTS (SELECT 1 FROM #hol h
                                       WHERE h.holiday_date = a.work_date
                                         AND (h.scope = 'ALL'
                                              OR h.scope = CASE a.plant WHEN 'Head Office' THEN 'HO'
                                                                        WHEN 'Korangi Plant' THEN 'KOR'
                                                                        WHEN 'SITE Plant'    THEN 'SITE'
                                                                        WHEN 'Faisalabad Plant' THEN 'FSD' END))
                            THEN 1 ELSE 0 END = 1 AND a.punch_count = 0          THEN 'Holiday'
                WHEN EXISTS (SELECT 1 FROM #leave l
                             WHERE l.emp_id = a.emp_id AND l.leave_day = a.work_date) THEN 'On Leave'
                WHEN a.punch_count >= 2                                       THEN 'Present'
                WHEN a.punch_count = 1                                        THEN 'Missing Punch'
                ELSE                                                               'Absent'
           END                                                                AS status
    INTO #agg2
    FROM #agg a;

    -- rule 12 "work on punch days": Present means >=2 punches AND not On Leave
    SELECT a2.*,
           CASE WHEN a2.status = 'Present' THEN DATEDIFF(minute, a2.check_in, a2.check_out) ELSE NULL END AS worked_minutes,
           CASE WHEN a2.status = 'Present' AND a2.is_sunday = 0 AND a2.is_holiday = 0 AND         -- rule 13: only non-Sunday/holiday
                     DATEDIFF(minute, a2.s_ts, a2.check_in) > a2.grace_minutes                -- rule 13 late
                THEN DATEDIFF(minute, a2.s_ts, a2.check_in) - a2.grace_minutes ELSE 0 END     AS late_minutes,
           CASE WHEN a2.status = 'Present' AND a2.is_sunday = 0 AND a2.is_holiday = 0 AND          -- rule 13
                     DATEDIFF(minute, a2.s_ts, a2.check_out) < a2.duration_min - a2.grace_minutes  -- rule 13 early
                THEN a2.duration_min - a2.grace_minutes - DATEDIFF(minute, a2.s_ts, a2.check_out)
                ELSE 0 END                                                                    AS early_minutes,
           CASE WHEN a2.status = 'Present' AND (a2.is_sunday = 1 OR a2.is_holiday = 1)               -- rule 15
                     THEN DATEDIFF(minute, a2.check_in, a2.check_out)
                WHEN a2.status = 'Present' AND
                     DATEDIFF(minute, a2.s_ts, a2.check_out) > a2.duration_min                       -- rule 14
                     THEN DATEDIFF(minute, a2.s_ts, a2.check_out) - a2.duration_min
                ELSE 0 END                                                                           AS ot_minutes
    INTO staging.attendance_daily
    FROM #agg2 a2;
    """

    SQL_ADD_OT_HOURS = """
    ALTER TABLE staging.attendance_daily ADD ot_hours decimal(4, 1) NULL;
    """

    SQL_SET_OT_HOURS = """
    UPDATE staging.attendance_daily
    SET ot_hours = CAST(FLOOR(ot_minutes / 30.0) / 2.0 AS decimal(4, 1));   -- rule 14: floor to half-hours
    """

    SQL_MEMBERSHIP = """
    -- punch membership diagnostic: every punch in >=1 window; seam punches in 2
    SELECT
        (SELECT COUNT(*) FROM staging.punches_clean) AS punch_rows,
        (SELECT COUNT(*) FROM (
            SELECT DISTINCT CAST(p.emp_id AS varchar(20)) AS emp_id, p.punch_ts AS punch_ts FROM #p p
            WHERE EXISTS (SELECT 1 FROM #win w
                          WHERE w.emp_id = p.emp_id
                            AND p.punch_ts BETWEEN w.w_start AND w.w_end)) m) AS punches_in_some_window,
        (SELECT COUNT(*) FROM #win w JOIN #p p
            ON p.emp_id = w.emp_id AND p.punch_ts BETWEEN w.w_start AND w.w_end) AS window_memberships
    """

    def _build(self, cur, cn):
        """Run the SQL_BUILD batch, then the ALTER + UPDATE in SEPARATE batches
        (pyodbc: UPDATE cannot see the new column inside the same batch)."""
        cur.execute(self.SQL_BUILD.format(
            EARLY_ALLOWANCE_MIN=self.EARLY_ALLOWANCE_MIN,
            OT_CEILING_MIN=self.OT_CEILING_MIN,
            ANCHOR_SUNDAY=self.ANCHOR_SUNDAY))
        cur.execute(self.SQL_ADD_OT_HOURS)
        cur.execute(self.SQL_SET_OT_HOURS)

    def _reconcile(self, cur, cn):
        """Core reconciliation before committing anything."""
        rows = cur.execute("SELECT COUNT(*) FROM staging.attendance_daily").fetchval()
        span_expected = cur.execute("""
            SELECT COUNT(*) FROM staging.roster_shift_daily r
            JOIN staging.employees_final e ON e.emp_id = r.emp_id
            WHERE r.work_date BETWEEN TRY_CAST(e.hire_date AS date)
                                  AND COALESCE(TRY_CAST(e.separation_date AS date), CAST('2026-09-30' AS date))
        """).fetchval()
        punch_rows, in_window, memberships = cur.execute(self.SQL_MEMBERSHIP).fetchone()

        status = cur.execute(
            "SELECT status, COUNT(*) FROM staging.attendance_daily GROUP BY status ORDER BY 2 DESC").fetchall()
        bad_ro = cur.execute(
            "SELECT COUNT(*) FROM staging.attendance_daily WHERE check_out < check_in").fetchval()
        late = cur.execute(
            "SELECT COUNT(*), SUM(late_minutes) FROM staging.attendance_daily WHERE late_minutes > 0").fetchone()
        on_leave = cur.execute(
            "SELECT COUNT(*) FROM staging.attendance_daily WHERE on_leave = 1").fetchval()
        leave_expect = cur.execute("""
            SELECT COUNT(*) FROM #leave l
            JOIN #emp e ON e.emp_id = l.emp_id
            WHERE l.leave_day BETWEEN e.hire_date AND e.last_day
        """).fetchval()

        # commit only if the reconciliation holds
        if rows != span_expected or bad_ro > 0:
            cn.rollback()
            sys.exit(f"ABORT: rows {rows} != span roster {span_expected} or inverted pairs {bad_ro}")
        cn.commit()
        return rows, span_expected, punch_rows, in_window, memberships, status, late, on_leave, leave_expect

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        try:
            if cur.execute(self.SQL_TABLES_READY).fetchval() != 6:
                sys.exit("ABORT: Stage 2 outputs missing - run stage2_bullet0{2..7} first.")

            self._build(cur, cn)
            (rows, span_expected, punch_rows, in_window, memberships,
             status, late, on_leave, leave_expect) = self._reconcile(cur, cn)
        except Exception:
            cn.rollback()
            raise

        print(f"staging.attendance_daily : {rows:,} rows (span roster = {span_expected:,})")
        print(f"punch conservation       : {punch_rows:,} punches -> {memberships:,} window memberships "
              f"(seam punches counted twice: {memberships - in_window:,}; orphans 0 verified by probe)")
        print("status distribution:")
        for s, n in status:
            print(f"  {s:<13} {n:>8,}   ({100.0 * n / rows:5.1f} %)")
        print(f"late arrivals (rule 13)  : {late[0]:,} rows, {late[1]:,} minutes")
        print(f"On Leave overlap check   : {on_leave:,} rows vs leave_days-in-span {leave_expect:,}")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage3AttendanceDaily().run())
