"""BONUS B3 runner of the case-study PDF (p.7):
    "Recruitment funnel from applications.csv: conversion and median days
     at each stage."

Executes the single-batch query in bonus_b3_recruitment_funnel.sql and writes
its result set to bonus_b3_recruitment_funnel_result.csv (UTF-8-sig with a
header row — same result-CSV convention as the Stage 5 qXX files), then
prints a compact funnel view for the console.

Definitions live in the .sql header comment (funnel pipe Applied -> Screened
-> Interviewed -> Offered -> Hired; exits Rejected / Offer Declined;
conversion vs the immediately previous stage; PERCENTILE_CONT median days).

    python -X utf8 pipeline/analytics/bonus_b3_recruitment_funnel.py
"""
import csv
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))          # repo-root analytics/
_SRC_ROOT = os.path.dirname(_SRC_DIR)                          # repo root
if _SRC_ROOT not in sys.path:
    sys.path.append(_SRC_ROOT)

from pipeline_base import PipelineTask  # noqa: E402


class BonusB3RecruitmentFunnel(PipelineTask):
    """Bonus B3 — applications.csv funnel query -> result CSV + console view."""

    NAME = "bonus_b3_recruitment_funnel"

    @property
    def sql_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{self.NAME}.sql")

    def _execute(self):
        """Run the single-batch funnel query; returns (columns, rows)."""
        with open(self.sql_path, encoding="utf-8") as fh:
            sql = fh.read()
        with self.connection() as cn:
            cur = cn.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return cols, rows

    def _write_csv(self, cols, rows) -> str:
        out = os.path.join(os.path.dirname(self.sql_path), f"{self.NAME}_result.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for row in rows:
                w.writerow([str(v) if v is not None else "" for v in row])
        return out

    def run(self) -> int:
        cols, rows = self._execute()
        out = self._write_csv(cols, rows)

        print(f"funnel written -> {out}\n")
        for seq, stage, reached, conv, n_med, med in rows:
            star = "*" if seq == 0 else ("exit" if seq < 0 else "")
            print(f"  {seq:>3} {stage:20s} reached {reached:>5,} "
                  f"conv {('' if conv is None else f'{conv:5.2f}%'):>6s} "
                  f"median {('' if med is None else f'{med} d'):>6s} (n={n_med or 0:,}) {star}")
        print("\n  conv = vs the immediately previous pipe stage;")
        print("  median = days from the previous stage, PERCENTILE_CONT(0.5).")
        return 0


if __name__ == "__main__":
    sys.exit(BonusB3RecruitmentFunnel().run())
