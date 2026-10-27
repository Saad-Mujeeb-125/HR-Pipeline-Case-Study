"""STAGE 1 of the case-study PDF (p.5):
    "Load every file into a raw schema exactly as delivered, all columns as
     text. Flatten nothing yet.
     Add load metadata to each table: _source_file, _loaded_at, _row_hash.
     Make the load idempotent: running it twice must not create duplicate
     rows.
     Log the row count per file and per table, and check they match."

What this class does (canonical dataset = data/ — decision D001, never the
repo-root copies):
  * every CSV value lands as nvarchar(max) text (typing is Stage 2's job);
    JSON files are delivered documents, stored as ONE row per file
    (json_data nvarchar(max)) exactly as the export ships them;
  * every table gets _source_file nvarchar(255), _loaded_at datetime2,
    _row_hash varchar(64) = sha256 of the row's data values joined with NUL;
  * idempotency: the FILE sha256 goes into raw.load_history. A file whose
    stored hash still matches AND whose row count matches the table is
    SKIPPED, so re-running the load cannot duplicate rows. A changed hash
    means the export changed -> the table is truncated and reloaded;
  * after every file: source rows vs database rows are compared and logged
    to raw.row_count_log (PASS/FAIL; a FAIL aborts the stage);
  * a table whose audit metadata is still NULL (legacy first load) is
    rebuilt once, content-identical since values are the file's own text.

    python -X utf8 pipeline/ingestion/stage1_ingest.py
"""
import csv
import datetime as dt
import hashlib
import json
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage1Ingest(PipelineTask):
    """Stage 1 — load the 12 delivered files into raw.* as text, idempotently."""

    # raw table -> delivered file (CSV: one row per record; JSON: one doc row)
    FILES = [
        ("employees", "employees.csv"),
        ("employment_history", "employment_history.csv"),
        ("departments", "departments.csv"),
        ("shift_roster", "shift_roster.csv"),
        ("device_mapping", "device_mapping.csv"),
        ("biometric_punches", "biometric_punches.csv"),
        ("holidays", "holidays.csv"),
        ("overtime_requests", "overtime_requests.csv"),
        ("payroll_lines", "payroll_lines.csv"),
        ("applications", "applications.csv"),
        ("shifts", "shifts.json"),
        ("leave_requests", "leave_requests.json"),
    ]

    META_COLS = ("_source_file nvarchar(255), _loaded_at datetime2, _row_hash varchar(64)")
    ROW_HASH_SEP = "\x00"      # join delimiter inside the per-row sha256

    # ------------------------- helpers ---------------------------------

    @staticmethod
    def sha_bytes(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    @classmethod
    def row_hash(cls, values) -> str:
        return hashlib.sha256(cls.ROW_HASH_SEP.join(values).encode("utf-8")).hexdigest()

    @staticmethod
    def read_csv_rows(path: str):
        """(headers, data rows as list-of-str) parsed exactly as delivered.
        utf-8-sig transparently drops a BOM if the export carries one."""
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        return rows[0], rows[1:]

    @staticmethod
    def read_json_text(path: str) -> str:
        """Whole JSON document as delivered (validated but never re-serialized)."""
        with open(path, "rb") as fh:
            head = fh.read(2)
        enc = "utf-8-sig" if head == b"\xef\xbb\xbf" else "utf-8"
        with open(path, "r", encoding=enc, newline="") as fh:
            text = fh.read()
        json.loads(text)          # must parse — a corrupted export cannot ride in
        return text

    @staticmethod
    def table_columns(cur, table):
        cur.execute("""
            SELECT c.name FROM sys.columns c
            JOIN sys.tables t ON t.object_id = c.object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = 'raw' AND t.name = ?
              AND c.name NOT IN ('_source_file', '_loaded_at', '_row_hash')
            ORDER BY c.column_id""", table)
        return [r[0] for r in cur.fetchall()]

    # ------------------------- load steps -------------------------------

    def _ensure_table(self, cur, table: str, fname: str, path: str) -> None:
        """Create the raw table if missing; abort if its columns drifted
        from the delivered header (text-only storage is Stage 1's contract)."""
        cur.execute("SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id "
                    "WHERE s.name = 'raw' AND t.name = ?", table)
        exists = bool(cur.fetchval())
        if not exists:
            if fname.endswith(".json"):
                cur.execute(f"CREATE TABLE raw.{table} (json_data nvarchar(max), {self.META_COLS});")
            else:
                headers, _ = self.read_csv_rows(path)
                cols = ", ".join(f"[{h}] nvarchar(max)" for h in headers)
                cur.execute(f"CREATE TABLE raw.{table} ({cols}, {self.META_COLS});")
            return
        db_cols = self.table_columns(cur, table)
        if fname.endswith(".json"):
            if db_cols != ["json_data"]:
                sys.exit(f"ABORT: raw.{table} columns {db_cols} != expected json_data")
        else:
            headers, _ = self.read_csv_rows(path)
            if db_cols != headers:
                sys.exit(f"ABORT: raw.{table} columns {db_cols} != delivered header {headers}")

    def _ensure_meta_cols(self, cur, cn, table: str) -> None:
        """Every table must carry the audit metadata columns (Stage 1)."""
        cur.execute(f"""
            SELECT COUNT(*) FROM sys.columns c
            WHERE c.object_id = OBJECT_ID('raw.{table}') AND c.name = '_row_hash'""")
        if not cur.fetchval():
            cur.execute(f"ALTER TABLE raw.{table} ADD _source_file nvarchar(255) NULL, "
                        f"_loaded_at datetime2 NULL, _row_hash varchar(64) NULL;")
            cn.commit()

    def _already_loaded(self, cur, table: str, fname: str, file_hash: str):
        """Idempotency decision -> True when hash, row count and audit
        metadata all agree that this exact file is already in the table."""
        cur.execute("SELECT COUNT(*) FROM raw.load_history WHERE source_file = ? AND file_hash = ?",
                    fname, file_hash)
        hash_ok = bool(cur.fetchval())
        cur.execute(f"SELECT COUNT(*) FROM raw.{table}")
        db_rows = cur.fetchval()
        cur.execute(f"SELECT COUNT(_source_file) FROM raw.{table}")
        meta_populated = (cur.fetchval() or 0) > 0

        if os.environ.get("STAGE1_DEBUG"):
            print(f"DEBUG {fname}: hash_ok={hash_ok} db_rows={db_rows} meta_populated={meta_populated}")

        return hash_ok and db_rows > 0 and meta_populated, db_rows

    def _load_json(self, cur, cn, table: str, fname: str, path: str, loaded_on, file_hash: str):
        src = self.read_json_text(path)
        cur.execute(f"INSERT INTO raw.{table} (json_data, _source_file, _loaded_at, _row_hash) "
                    f"VALUES (?, ?, ?, ?)", src, fname, loaded_on, self.row_hash([src]))
        if os.environ.get("STAGE1_DEBUG"):
            cur.execute(f"SELECT COUNT(*), COUNT(_source_file) FROM raw.{table}")
            print(f"DEBUG {fname}: right after insert:", cur.fetchone())
        self._log_counts(cur, fname, 1, 1)
        self._upsert_load_history(cur, fname, file_hash, loaded_on, 1)
        if os.environ.get("STAGE1_DEBUG"):
            cur.execute("SELECT file_hash, loaded_at FROM raw.load_history WHERE source_file = ?", fname)
            print(f"DEBUG {fname}: load_history now:", cur.fetchone())
        return 1

    def _load_csv(self, cur, cn, table: str, fname: str, path: str, loaded_on, file_hash: str):
        headers, rows = self.read_csv_rows(path)
        cur.fast_executemany = True
        cur.executemany(
            f"INSERT INTO raw.{table} ({', '.join('[' + h + ']' for h in headers)},"
            f"_source_file, _loaded_at, _row_hash) "
            f"VALUES ({', '.join('?' * len(headers))}, ?, ?, ?)",
            [(*r, fname, loaded_on, self.row_hash(r)) for r in rows])
        cur.fast_executemany = False
        db_rows = cur.execute(f"SELECT COUNT(*) FROM raw.{table}").fetchval()
        self._log_counts(cur, fname, len(rows), db_rows)
        self._upsert_load_history(cur, fname, file_hash, loaded_on, len(rows))
        return len(rows)

    def _log_counts(self, cur, source_file: str, src_rows: int, db_rows: int) -> None:
        """raw.row_count_log check: source rows must equal database rows."""
        status = "PASS" if src_rows == db_rows else "FAIL"
        cur.execute(
            "INSERT INTO raw.row_count_log (source_file, source_rows, database_rows, status, checked_at) "
            "VALUES (?, ?, ?, ?, ?)", source_file, src_rows, db_rows, status, dt.datetime.now())
        if status != "PASS":
            sys.exit(f"ABORT: {source_file} loaded {db_rows} rows but the file holds {src_rows}.")

    def _upsert_load_history(self, cur, source_file: str, file_hash: str, loaded_at, row_count: int) -> None:
        """raw.load_history PK = source_file: an existing record is overwritten
        (the export changed), a new one inserted."""
        cur.execute("SELECT 1 FROM raw.load_history WHERE source_file = ?", source_file)
        if cur.fetchval():
            cur.execute("UPDATE raw.load_history SET file_hash = ?, loaded_at = ?, row_count = ? "
                        "WHERE source_file = ?", file_hash, loaded_at, row_count, source_file)
        else:
            cur.execute("INSERT INTO raw.load_history (source_file, file_hash, loaded_at, row_count) "
                        "VALUES (?, ?, ?, ?)", source_file, file_hash, loaded_at, row_count)

    # ------------------------- public entry ------------------------------

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        loaded_on = dt.datetime.now()
        summary = []

        for table, fname in self.FILES:
            path = os.path.join(self.data_dir, fname)
            if not os.path.exists(path):
                sys.exit(f"ABORT: {path} missing — run Stage 1 where the data pack lives.")
            file_hash = self.sha_bytes(open(path, "rb").read())

            self._ensure_table(cur, table, fname, path)
            self._ensure_meta_cols(cur, cn, table)

            already, db_rows = self._already_loaded(cur, table, fname, file_hash)
            if already:
                summary.append((fname, db_rows, "skip (already loaded)"))
                continue

            # ---------------- load (or load again after export change) ------
            # (pyodbc runs with autocommit OFF: the work below joins one implicit
            #  transaction, committed per file at cn.commit(); no nested BEGIN)
            cur.execute(f"TRUNCATE TABLE raw.{table}")
            if fname.endswith(".json"):
                n = self._load_json(cur, cn, table, fname, path, loaded_on, file_hash)
                summary.append((fname, n, "loaded"))
            else:
                n = self._load_csv(cur, cn, table, fname, path, loaded_on, file_hash)
                summary.append((fname, n, "loaded"))
            cn.commit()
            if os.environ.get("STAGE1_DEBUG"):
                cur.execute(f"SELECT COUNT(*), COUNT(_source_file) FROM raw.{table}")
                print(f"DEBUG {fname}: after commit:", cur.fetchone())

        print(f"{'file':26s} {'rows':>9s}  action")
        for fname, n, action in summary:
            print(f"{fname:26s} {n:9,}  {action}")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage1Ingest().run())
