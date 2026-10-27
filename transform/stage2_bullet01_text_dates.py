"""STAGE 2, bullet 1 of the case-study PDF (p.5):
    "Build a staging schema with typed, cleaned tables.
     Trim text, fix casing, and convert all dates to ISO YYYY-MM-DD."

What it builds (from raw.employees / raw.employment_history / raw.shift_roster):
  staging.employees_cleaned            1,316 rows: trimmed text, department
                                       casing normalized, 3 date formats
                                       (YYYY-MM-DD / DD/MM/YYYY / DD-Mon-YYYY)
                                       -> typed DATE columns
  staging.employment_history_cleaned   3,686 rows: dates typed incl. the
                                       rule-2-ignored 1900-01-01 effective_to
                                       sentinel (kept as-is; rule 2 says use
                                       LEAD-from, so downstream never reads it)
  staging.shift_roster_cleaned        36,402 rows: week_start typed

Cleaning recipe (applied in Python so it is auditable line by line):
  * every text column: trimmed
  * full_name: if ALL-CAPS -> title case ('USMAN BALOCH' -> 'Usman Baloch')
  * department: strip -> Title Case, EXCEPT short ALL-CAPS acronyms kept
    ('IT' stays 'IT'; a naive .title() yields 'It'). Renamed-department old
    names ('Procurement', 'Processing') are NOT renamed here — they are the
    CSV's own text, preserved for downstream resolution (documented in
    staging.department_mapping_issues).
  * dates: explicit 3-format parser, day-first for the slash format, hard
    error on anything unparseable (no silent NULLs)
  * basic_salary -> decimal(10,2); annual_leave_entitlement / updated_at
    stay text (bullet 2 re-ranks by updated_at; entitlement typed downstream)

Idempotency: tables are rebuilt every run. Before committing, the class
proves itself against the live DB: rebuilt rows must be cell-identical to the
existing tables — the ONLY allowed difference is the deliberate 'It' -> 'IT'
department fix on raw ' IT'/'IT' employee rows (decision D022; the department
text never drives warehouse FKs — facts use employment_history dept_id).
Run stage2_bullet02 afterwards to refresh staging.employees_final.

    python -X utf8 pipeline/transform/stage2/stage2_bullet01_text_dates.py
"""
import datetime as dt
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage2Bullet01TextDates(PipelineTask):
    """Stage 2 bullet 1 — trim / casing / 3 date formats on text raw rows."""

    EMP_COLS = ["emp_id", "full_name", "gender", "date_of_birth", "email", "phone",
                "plant", "department", "designation", "grade", "employment_type",
                "hire_date", "separation_date", "status", "annual_leave_entitlement",
                "updated_at"]
    HIST_COLS = ["emp_id", "effective_from", "effective_to", "dept_id",
                 "designation", "grade", "basic_salary", "change_reason"]
    ROS_COLS = ["emp_id", "week_start", "shift_code"]

    DDL = """
    IF OBJECT_ID('staging.shift_roster_cleaned') IS NOT NULL DROP TABLE staging.shift_roster_cleaned;
    IF OBJECT_ID('staging.employment_history_cleaned') IS NOT NULL DROP TABLE staging.employment_history_cleaned;
    IF OBJECT_ID('staging.employees_cleaned') IS NOT NULL DROP TABLE staging.employees_cleaned;
    CREATE TABLE staging.employees_cleaned (
        emp_id varchar(20), full_name varchar(100), gender varchar(10),
        date_of_birth date, email varchar(120), phone varchar(25), plant varchar(60),
        department varchar(60), designation varchar(60), grade varchar(10),
        employment_type varchar(20), hire_date date, separation_date date,
        status varchar(10), annual_leave_entitlement varchar(10), updated_at varchar(30));
    CREATE TABLE staging.employment_history_cleaned (
        emp_id varchar(20), effective_from date, effective_to date, dept_id varchar(10),
        designation varchar(60), grade varchar(10), basic_salary decimal(10,2),
        change_reason varchar(30));
    CREATE TABLE staging.shift_roster_cleaned (
        emp_id varchar(20), week_start date, shift_code varchar(20));
    """

    SQL_GUARD = """
    SELECT SUM(CASE WHEN t.name = 'employees' THEN 1 ELSE 0 END)
         + SUM(CASE WHEN t.name = 'employment_history' THEN 1 ELSE 0 END)
         + SUM(CASE WHEN t.name = 'shift_roster' THEN 1 ELSE 0 END)
    FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = 'raw' AND t.name IN ('employees', 'employment_history', 'shift_roster')
    """

    # ------------------------------------------------------------- transform

    @staticmethod
    def txt(v):
        """Trim text; None-safe."""
        return "" if v is None else str(v).strip()

    @staticmethod
    def title_if_caps(s):
        """'USMAN BALOCH' -> 'Usman Baloch'; leaves already-mixed names alone."""
        return s.title() if s and s == s.upper() and s != s.lower() else s

    @staticmethod
    def dept_casing(s):
        """Strip + Title Case; short ALL-CAPS words are acronyms and stay 'IT'."""
        if not s:
            return s
        s = s.strip()
        if s == s.upper() and len(s) <= 3:
            return s
        return s.title()

    @staticmethod
    def parse_date(v):
        """Exactly the three exported formats; anything else is a hard error so a
        delimiter regression can never pass silently."""
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"):
            try:
                return dt.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"unrecognised date text {s!r} (expected ISO, DD/MM/YYYY or DD-Mon-YYYY)")

    @staticmethod
    def as_cell(v):
        """Value -> comparable text (dates ISO, floats 2dp)."""
        if v is None or v == "":
            return ""
        if isinstance(v, dt.date):
            return v.isoformat()
        if isinstance(v, float):
            return "%.2f" % v
        return str(v)

    @staticmethod
    def fetch_raw(cursor, table, cols, schema="raw"):
        cursor.execute(f"SELECT {', '.join(cols)} FROM {schema}.{table}")
        return cursor.fetchall()

    @classmethod
    def _rows_counter(cls, rows):
        """Multiset of fully serialized rows (order-independent equality):
        SELECTs without ORDER BY may return rows in any physical order, so
        the exactness proof compares value multisets, not row positions."""
        from collections import Counter
        return Counter(tuple(cls.as_cell(v) for v in r) for r in rows)

    def clean_employees(self, emp_raw):
        out = []
        for emp_id, full_name, gender, dob, email, phone, plant, dept, designation, \
                grade, etype, hire, sep, status, alae, upd in emp_raw:
            out.append([
                emp_id, self.title_if_caps(self.txt(full_name)), self.txt(gender), self.parse_date(dob),
                self.txt(email), self.txt(phone), self.txt(plant), self.dept_casing(dept),
                self.txt(designation), self.txt(grade), self.txt(etype), self.parse_date(hire),
                self.parse_date(sep), self.txt(status), self.txt(alae), self.txt(upd),
            ])
        return out

    def clean_history(self, his_raw):
        out = []
        for emp_id, eff_from, eff_to, dept_id, designation, grade, salary, reason in his_raw:
            end = self.parse_date(eff_to)
            if end is None:
                # sentinel for "no end" (current record; rule 2 never reads
                # this column - LEAD(effective_from) defines valid_to instead)
                end = dt.date(1900, 1, 1)
            out.append([
                emp_id, self.parse_date(eff_from), end, self.txt(dept_id),
                self.txt(designation), self.txt(grade),
                round(float(salary), 2) if salary not in (None, "") else None,
                self.txt(reason),
            ])
        return out

    def clean_roster(self, ros_raw):
        return [[emp_id, self.parse_date(week_start), self.txt(shift_code)]
                for emp_id, week_start, shift_code in ros_raw]

    # ------------------------------------------------------------- proof

    def _prove_exactness(self, cur, emp_new, his_new, ros_new, emp_raw, his_raw, ros_raw):
        """Cell-exactness proof vs the live DB (delivery check for this class):
        all three rebuilt tables must reproduce their current content; the
        only tolerated difference is the D022 'It' -> 'IT' fix."""
        if (cur.execute("SELECT COUNT(*) FROM staging.employees_cleaned").fetchval() != len(emp_raw)
                or cur.execute("SELECT COUNT(*) FROM staging.employment_history_cleaned").fetchval() != len(his_raw)
                or cur.execute("SELECT COUNT(*) FROM staging.shift_roster_cleaned").fetchval() != len(ros_raw)):
            sys.exit("ABORT: existing staging tables' row counts differ from raw — pipeline moved on.")
        emp_old = self.fetch_raw(cur, "employees_cleaned", self.EMP_COLS, schema="staging")
        his_old = self.fetch_raw(cur, "employment_history_cleaned", self.HIST_COLS, schema="staging")
        ros_old = self.fetch_raw(cur, "shift_roster_cleaned", self.ROS_COLS, schema="staging")

        for table, new_rows, old_rows in (
                ("employment_history_cleaned", his_new, his_old),
                ("shift_roster_cleaned", ros_new, ros_old)):
            new_only = self._rows_counter(new_rows) - self._rows_counter(old_rows)
            old_only = self._rows_counter(old_rows) - self._rows_counter(new_rows)
            if new_only or old_only:
                sys.exit(f"ABORT: {table} differs unexpectedly, e.g. "
                         f"{next(iter(new_only or old_only))}")

        # employees: the one deliberate difference is D022's dept fix
        new_only = self._rows_counter(emp_new) - self._rows_counter(emp_old)
        old_only = self._rows_counter(emp_old) - self._rows_counter(emp_new)
        if sum(new_only.values()) != sum(old_only.values()):
            sys.exit("ABORT: employees_cleaned differs unexpectedly (asymmetric diff).")
        remaining = dict(old_only)
        wart_rows = 0
        for row_new, cnt_new in new_only.items():
            if row_new[7] != "IT":
                sys.exit(f"ABORT: employees_cleaned unexpected new-only row {row_new}")
            key = row_new[:7] + row_new[8:]
            match = next((r for r, c in remaining.items()
                          if c and r[7] == "It" and r[:7] + r[8:] == key), None)
            if match is None:
                sys.exit(f"ABORT: employees_cleaned unexpected diff at emp_id {row_new[0]}: "
                         f"new-only row {row_new} has no mirrored 'It' row")
            del remaining[match]
            wart_rows += cnt_new
        if any(c > 0 for c in remaining.values()):
            sys.exit("ABORT: employees_cleaned unexpected old-only rows "
                     f"e.g. {next(iter(remaining))}")
        return wart_rows

    # ------------------------------------------------------------- public entry

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        cur.fast_executemany = True

        if cur.execute(self.SQL_GUARD).fetchval() != 3:
            sys.exit("ABORT: raw.employees / employment_history / shift_roster missing — run Stage 1 first.")
        n_existing = cur.execute("""
            SELECT COUNT(*) FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = 'staging'
              AND t.name IN ('employees_cleaned', 'employment_history_cleaned', 'shift_roster_cleaned')
        """).fetchval()
        if n_existing != 3:
            sys.exit("ABORT: the three target tables must already exist for the exactness "
                     "check against the current build (delete row only after reviewing).")

        emp_raw = self.fetch_raw(cur, "employees", self.EMP_COLS)
        his_raw = self.fetch_raw(cur, "employment_history", self.HIST_COLS)
        ros_raw = self.fetch_raw(cur, "shift_roster", self.ROS_COLS)
        print(f"raw pulled: employees {len(emp_raw):,} / history {len(his_raw):,} / roster {len(ros_raw):,}")

        emp_new = self.clean_employees(emp_raw)
        his_new = self.clean_history(his_raw)
        ros_new = self.clean_roster(ros_raw)

        wart_rows = self._prove_exactness(cur, emp_new, his_new, ros_new, emp_raw, his_raw, ros_raw)

        # all checks green -> rebuild the tables with the fully owned recipe
        cur.execute(self.DDL)
        cur.executemany(
            "INSERT INTO staging.employees_cleaned VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            emp_new)
        cur.executemany(
            "INSERT INTO staging.employment_history_cleaned VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)", his_new)
        cur.executemany(
            "INSERT INTO staging.shift_roster_cleaned VALUES (?, ?, ?)", ros_new)

        counts = [
            cur.execute("SELECT COUNT(*) FROM staging.employees_cleaned").fetchval(),
            cur.execute("SELECT COUNT(*) FROM staging.employment_history_cleaned").fetchval(),
            cur.execute("SELECT COUNT(*) FROM staging.shift_roster_cleaned").fetchval(),
        ]
        if counts != [len(emp_raw), len(his_raw), len(ros_raw)]:
            cn.rollback()
            sys.exit(f"ABORT: rebuilt counts {counts} do not reconcile with raw — rolled back.")
        cn.commit()
        print(f"exactness: history/roster identical; employees diff = only the 'It'->'IT' fix ({wart_rows} rows)")
        print(f"inserted  : employees_cleaned {counts[0]:,} / history {counts[1]:,} / roster {counts[2]:,}")
        print("reconcile : raw == cleaned for all three (dedup is bullet 2's job) OK")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage2Bullet01TextDates().run())
