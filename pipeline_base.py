"""Light base class shared by every pipeline task class (decision D027).

The pipeline keeps ONE code file per case-study PDF task, and each file
carries ONE class named after the task (Stage1Ingest, Stage3AttendanceDaily,
...). This module holds only what every task repeats so each class stays
explainable on its own:

  * canonical locations: data/ (never the repo-root duplicate copies,
    decision D001) and the repo root itself;
  * `get_connection()` — the reviewed helper in db_connect.py;
  * `log()` — printing helpers honouring a verbose flag, so a task embedded
    in the orchestrator can stay quiet if a future caller wants that;
  * the idempotent-re-run contract: `run()` is the sole public entry of every
    subclass and re-running it must leave the database in the same state.

Nothing here opens connections or touches data on import or construction —
only `run()` does work.

Data-quality convention (decision D001/D021, kept runnable from any folder):

    python -X utf8 ingestion/stage1_ingest.py     (or any other task script)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))       # repo root
if _HERE not in sys.path:
    sys.path.append(_HERE)

from db_connect import get_connection  # noqa: E402,F401  (re-exported)

PIPELINE_DIR = _HERE
DATA_DIR = os.path.normpath(os.path.join(_HERE, "data"))
ROOT_DIR = _HERE


class PipelineTask:
    """Base class for one per-PDF-task class.

    Subclass contract (docs/preferences.md rule 1a):
      * `__init__` sets paths/constants only — no I/O;
      * `run()` is the sole public entry and returns the process exit code;
      * one focused private method per logical step
        (_extract / _transform / _load / _verify / ...);
      * every step logs its row counts.
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.data_dir = DATA_DIR
        self.pipeline_dir = _HERE

    def log(self, message: str) -> None:
        if self.verbose:
            print(message)

    def connection(self):
        """A fresh pyodbc connection (autocommit OFF — commit per unit)."""
        return get_connection()

    def run(self) -> int:
        raise NotImplementedError(f"{type(self).__name__} must implement run()")
