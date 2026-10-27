"""BONUS B1 of the case-study PDF (p.7):
    "Provide a single run_pipeline.py script that executes the end-to-end
     pipeline."

One command, all stages, in dependency order:

    stage 1  ingestion       pipeline/ingestion/stage1_ingest.py
    stage 2  clean/standard  transform/stage2/stage2_bullet01..07 (order below)
    stage 3  business logic  transform/stage3/stage3_attendance_daily.py
    stage 4  warehouse DDL   warehouse/ddl/stage4_dimensions.sql then
                             stage4_facts.sql (via sqlcmd, idempotent
                             drop/rebuild)
    stage 5  analytics       warehouse/analytics/run_all.py all (q01..q10
                             -> <qXX>_result.csv each)
    stage 6  data quality    quality/run_all.py (68 checks -> quality.dq_results)

Failure behaviour: each step runs as its own subprocess; the first non-zero
exit stops the run (a broken upstream must not reach downstream). Stage 6
failing (FAIL/ERROR in DQ) aborts the pipeline with exit code 1, matching the
"checks gate loads" requirement. Every script is idempotent, so re-running
this file is safe: Stage 1 skips correctly-hashed files, Stages 2-4 rebuild
their tables, Stages 5-6 re-run from scratch.

Stage-2 run order (documented in each bullet's docstring):
    01 text/dates -> 02 dedup -> 03 map punches -> 05 2-min dedup ->
    04 device clock (needs punches_deduped) -> 06 leave flatten -> 07 leave days

    python -X utf8 pipeline/run_pipeline.py
"""
import os
import subprocess
import sys
import time

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))          # repo root


class PipelineStep:
    """One orchestration step: a human label + the argv to execute."""

    def __init__(self, label: str, argv: list):
        self.label = label
        self.argv = argv


class PipelineRunner:
    """Bonus B1 — executes all 13 steps; first failure stops the pipeline."""

    SQLCMD_ARGS = ["sqlcmd", "-S", "localhost\\SQLEXPRESS", "-E",
                   "-d", "IndusWeaveHR",
                   "-C"]   # trust the Express instance's self-signed certificate

    PY = [sys.executable, "-X", "utf8"]   # python steps use THIS interpreter

    # (label, argv) steps, dependency order
    STEPS = [
        PipelineStep("stage 1  ingestion (raw load, idempotent)",
                     PY + [os.path.join("ingestion", "stage1_ingest.py")]),
        PipelineStep("stage 2  bullet 1  text/casing/dates",
                     PY + [os.path.join("transform", "stage2", "stage2_bullet01_text_dates.py")]),
        PipelineStep("stage 2  bullet 2  employee dedup + merge log",
                     PY + [os.path.join("transform", "stage2", "stage2_bullet02_employee_dedup.py")]),
        PipelineStep("stage 2  bullet 3  punch mapping + rejections",
                     PY + [os.path.join("transform", "stage2", "stage2_bullet03_map_and_reject_punches.py")]),
        PipelineStep("stage 2  bullet 5  2-minute punch dedup",
                     PY + [os.path.join("transform", "stage2", "stage2_bullet05_punches_dedup_2min.py")]),
        PipelineStep("stage 2  bullet 4  device clock fix (after bullet 5)",
                     PY + [os.path.join("transform", "stage2", "stage2_bullet04_device_clock.py")]),
        PipelineStep("stage 2  bullet 6  leave JSON flatten",
                     PY + [os.path.join("transform", "stage2", "stage2_bullet06_leave_flatten.py")]),
        PipelineStep("stage 2  bullet 7  leave-day expansion",
                     PY + [os.path.join("transform", "stage2", "stage2_bullet07_leave_days.py")]),
        PipelineStep("stage 3  attendance_daily",
                     PY + [os.path.join("transform", "stage3", "stage3_attendance_daily.py")]),
        PipelineStep("stage 4  warehouse dimensions DDL",
                     SQLCMD_ARGS + ["-i", os.path.join(_SRC_DIR, "warehouse", "ddl", "stage4_dimensions.sql")]),
        PipelineStep("stage 4  warehouse facts DDL",
                     SQLCMD_ARGS + ["-i", os.path.join(_SRC_DIR, "warehouse", "ddl", "stage4_facts.sql")]),
        PipelineStep("stage 5  analytics q01..q10",
                     PY + [os.path.join("warehouse", "analytics", "run_all.py"), "all"]),
        PipelineStep("stage 6  data-quality checks (gate)",
                     PY + [os.path.join("quality", "run_all.py")]),
    ]

    def run(self) -> int:
        """Subprocess per step; first non-zero exit stops the run."""
        started = time.time()
        steps = self.STEPS
        print(f"Indus Weave HR pipeline — {len(steps)} steps, starting ...")
        for i, step in enumerate(steps, 1):
            print(f"\n=== [{i}/{len(steps)}] {step.label} "
                  f"({time.strftime('%H:%M:%S')}) ===")
            rc = subprocess.run(step.argv, cwd=_SRC_DIR).returncode
            if rc != 0:
                print(f"\nSTOPPED: '{step.label}' failed with exit code {rc}. "
                      f"Fix it and re-run (everything is idempotent).")
                return rc
        print(f"\nPIPELINE OK — all {len(steps)} steps succeeded "
              f"in {time.time() - started:,.0f} s. "
              f"Results: warehouse/analytics/*_result.csv, quality.dq_results.")
        return 0


def main() -> int:
    return PipelineRunner().run()


if __name__ == "__main__":
    sys.exit(main())
