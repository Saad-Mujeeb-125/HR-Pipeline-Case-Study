"""STAGE 5 runner of the case-study PDF (p.6):
    "One .sql file per question ... Save each result as a CSV."

Executes a Stage 5 question file (q01..q10) and writes its single result
result set to analytics/results/<qXX>_result.csv (UTF-8-sig, header row).
Each qXX.sql is one batch with exactly one SELECT — the deliverable query
quoted at the top of the file.

Usage:
    python -X utf8 analytics/run_all.py q01
    python -X utf8 analytics/run_all.py all
"""
import csv
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage5AnalyticsRunner(PipelineTask):
    """Stage 5 — run the ten question .sql files, one result CSV each."""

    def __init__(self, queries_dir: str = None, verbose: bool = True):
        super().__init__(verbose=verbose)
        # the .sql files live next to this runner, in analytics/
        self.queries_dir = queries_dir or os.path.dirname(os.path.abspath(__file__))
        # and every result CSV goes to the analytics/results/ subfolder
        self.results_dir = os.path.join(self.queries_dir, "results")
        os.makedirs(self.results_dir, exist_ok=True)

    def load_sql(self, name: str) -> str:
        path = os.path.join(self.queries_dir, f"{name}.sql")
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def run_one(self, name: str, csv_rows: dict) -> None:
        """One question -> its single result set -> <qXX>_result.csv."""
        with self.connection() as cn:
            cur = cn.cursor()
            cur.execute(self.load_sql(name))
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        out = os.path.join(self.results_dir, f"{name}_result.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for row in rows:
                w.writerow([str(v) if v is not None else "" for v in row])
        csv_rows[name] = (out, len(rows))
        print(f"{name}: {len(rows):,} rows -> {os.path.basename(out)}")

    def run(self) -> int:
        args = sys.argv[1:]
        if not args or args[0] == "all":
            names = [f"q{i:02d}" for i in range(1, 11)]
        else:
            names = args
        todo = []
        for name in names:
            if os.path.exists(os.path.join(self.queries_dir, f"{name}.sql")):
                todo.append(name)
            else:
                print(f"skip {name}: no .sql yet")
        csv_rows = {}
        for name in todo:
            self.run_one(name, csv_rows)
        return 0


if __name__ == "__main__":
    sys.exit(Stage5AnalyticsRunner().run())
