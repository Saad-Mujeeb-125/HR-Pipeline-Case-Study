"""Shared engine for the Stage 6 data-quality checks (case-study PDF p.7):

    "Write automated checks that run after every load and write results to a
     dq_results table."

Every stage6_checkNN_*.py script now defines ONE class with a CHECKS list;
this module's DQCheckRunner:

1. creates the `quality.dq_results` table on first use (idempotent),
2. runs each check query — every query must return exactly one row
   (rows_checked, rows_failed, message),
3. records one row per check in quality.dq_results (PASS / EXPECTED /
   FAIL / ERROR),
4. prints a one-line verdict per check and returns the tally of blocking
   checks (FAIL or ERROR; EXPECTED is reported but does not block).

Checks never mutate the data they inspect — read-only queries + one insert
each, so re-running stages 1..5 after a Stage 6 run is safe.

EXPECTED (decision D021): failures that are a known, documented quirk of the
SOURCE data (preserved by design) must still be reported — but leaving them
FAIL would block every future run and mask a NEW regression. So a FAIL whose
check_id is listed here AND whose rows_failed matches the expected magnitude
is recorded as status EXPECTED with the reason in the message. Anything else
stays FAIL.
"""
import os
import sys
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)
if _HERE not in sys.path:
    sys.path.append(_HERE)

from db_connect import get_connection  # noqa: E402


class DQCheckRunner:
    """Runs the check-family modules' CHECKS lists and writes dq_results."""

    # check_id -> (expected rows_failed, reason)
    EXPECTED_FAILURES = {
        "PK05": (1, "E11259 planted tie: Hire + Salary Revision share valid_from "
                    "2026-07-01, so (emp_id, valid_from) is duplicated once; rule 2 "
                    "ignores effective_to -> the zero-length row gets valid_to = "
                    "LEAD-1 and never matches a date lookup (dq_note recorded)"),
    }

    SQL_DDL = """
    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'quality')
        EXEC('CREATE SCHEMA quality');
    IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
                   WHERE s.name = 'quality' AND t.name = 'dq_results')
        CREATE TABLE quality.dq_results (
            dq_id         int IDENTITY(1,1) PRIMARY KEY,
            run_id        uniqueidentifier  NOT NULL,
            checked_at    datetime2(3)      NOT NULL DEFAULT sysdatetime(),
            check_id      varchar(30)       NOT NULL,
            check_name    nvarchar(300)     NOT NULL,
            check_category varchar(40)      NOT NULL,
            target_object nvarchar(200)     NOT NULL,
            rows_checked  bigint            NOT NULL,
            rows_failed   bigint            NOT NULL,
            status        varchar(10)       NOT NULL,   -- PASS/EXPECTED/FAIL/ERROR
            message       nvarchar(2048)    NOT NULL
        );
    """

    SQL_INSERT = """
        INSERT INTO quality.dq_results
            (run_id, check_id, check_name, check_category, target_object,
             rows_checked, rows_failed, status, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    def ensure_table(self, cur) -> None:
        cur.execute(self.SQL_DDL)

    def _classify(self, cur, check: dict):
        """Execute one check query and grade the result. Returns
        (rows_checked, rows_failed, status, message)."""
        try:
            cur.execute(check["sql"])
            rows_checked, rows_failed, msg = cur.fetchone()
            rows_checked = 0 if rows_checked is None else int(rows_checked)
            rows_failed = 0 if rows_failed is None else int(rows_failed)
            expected = self.EXPECTED_FAILURES.get(check["id"])
            if not rows_failed:
                status = "PASS"
            elif expected and rows_failed == expected[0]:
                status = "EXPECTED"
                msg = f"KNOWN QUIRK ({rows_failed}): {expected[1]} | {msg}"
            else:
                status = "FAIL"
        except Exception as ex:  # a broken check must still be recorded
            rows_checked, rows_failed, msg = 0, 0, f"ERROR: {ex}"
            status = "ERROR"
        return rows_checked, rows_failed, status, msg

    @staticmethod
    def _verdict_line(check: dict, rows_checked, rows_failed, status, msg) -> str:
        return (f"[{status}] {check['id']} {check['name']:52s}"
                f" checked={rows_checked:>9,} failed={rows_failed:>7,}"
                + ("" if status in ("PASS", "EXPECTED") else f"  {msg}"))

    def run_scripts(self, script_names, run_id: str = None) -> int:
        """Run the listed check-scripts' CHECKS lists; return the number of
        blocking checks (FAIL or ERROR; EXPECTED is reported, not blocking).
        Each script lives in this folder and exposes a module-level CHECKS list
        of dicts:
            id, category, name, target, sql  (sql -> rows_checked, rows_failed, message)
        """
        run_id = run_id or str(uuid.uuid4())
        blocking = 0
        total_checks = 0
        with get_connection() as cn:
            cur = cn.cursor()
            self.ensure_table(cur)
            cn.commit()
            for name in script_names:
                mod = __import__(name)
                for check in getattr(mod, "CHECKS"):
                    total_checks += 1
                    rows_checked, rows_failed, status, msg = self._classify(cur, check)
                    if status in ("FAIL", "ERROR"):
                        blocking += 1
                    cur.execute(self.SQL_INSERT,
                                run_id, check["id"], check["name"], check["category"], check["target"],
                                rows_checked, rows_failed, status, str(msg)[:2000])
                    print(self._verdict_line(check, rows_checked, rows_failed, status, msg))
            cn.commit()
        print(f"\nrun_id {run_id}: {total_checks} checks, {blocking} blocking -> quality.dq_results")
        return blocking


def run_scripts(script_names, run_id: str = None) -> int:
    """Compatibility shim: the thin procedural surface the check scripts and
    quality/run_all.py call (decision D027 keeps one class per file; this
    delegates to DQCheckRunner())."""
    return DQCheckRunner().run_scripts(script_names, run_id)
