"""STAGE 6 driver of the case-study PDF (p.7):

    "Write automated checks that run after every load and write results to
     a dq_results table."

Runs the five check families (check01_pk ... check05_sanity), records every
check as one row in quality.dq_results with a fresh run_id, prints a verdict
per check and exits non-zero when anything fails — so it can gate loads.

Usage:  python -X utf8 pipeline/quality/run_all.py
"""
import sys

import dq_common

SCRIPTS = ["stage6_check01_pk", "stage6_check02_fk", "stage6_check03_reconciliation",
           "stage6_check04_accepted_values", "stage6_check05_sanity"]


class Stage6RunAll:
    """Stage 6 gate — the five check families in one run (one run_id)."""

    def __init__(self):
        self.runner = dq_common.DQCheckRunner()

    def run(self) -> int:
        blocking = self.runner.run_scripts(SCRIPTS)
        # gate semantics: the pipeline aborts when a check FAILs/ERRORs
        return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(Stage6RunAll().run())
