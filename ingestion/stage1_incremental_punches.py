"""BONUS B2 of the case-study PDF (p.7):
    "Incremental load: a seventh month of punches arrives mid-hackathon;
     load only the new data."

The seventh month shows up as a NEW export file next to the original six
(e.g. data/biometric_punches_2026_10.csv). The full-reload reflex — truncate
raw.biometric_punches and reload everything — would work, but it re-reads
345k rows and rewrites history; the bonus explicitly wants ONLY the new rows
appended.

What this class does:
  * finds incremental punch exports in data/: any 'biometric_punches*.csv'
    EXCEPT the canonical full export 'biometric_punches.csv' (that one is
    Stage 1's full load);
  * for each file: header must match the raw table's data columns; every
    row's _row_hash (same sha256(NUL-joined values) convention as Stage 1)
    is looked up against the hashes already in raw.biometric_punches —
    rows already present are SKIPPED, only genuinely new rows are appended
    with the full audit metadata (_source_file/_loaded_at/_row_hash);
  * every file's verdict is logged to raw.incremental_loads (file rows /
    already present / inserted / file hash), so the mid-hackathon arrival
    is auditable without touching load_history's full-load semantics;
  * reconciliation: raw rows before + inserted == raw rows after, printed;
  * the appended raw rows flow downstream via the normal idempotent re-run
    (stage 2 bullets 3-5 -> stage 3 -> stage 4 attendance fact) — no
    incremental special-casing downstream, their TRUNCATE-rebuild pattern
    absorbs the new raw rows exactly once.

Deliveries that overlap what raw already holds (late re-exports, partial
files) are the common case: loading them is a no-op by construction.

    python -X utf8 pipeline/ingestion/stage1_incremental_punches.py
"""
import csv
import datetime as dt
import hashlib
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class IncrementalPunchLoader(PipelineTask):
    """Bonus B2 — append ONLY genuinely new punch rows from a later export."""

    TABLE = "biometric_punches"
    CANONICAL = "biometric_punches.csv"     # the six-month full export (Stage 1)
    ROW_HASH_SEP = "\x00"                   # same per-row hash convention as Stage 1

    DDL_LOG = """
    IF OBJECT_ID('raw.incremental_loads') IS NULL CREATE TABLE raw.incremental_loads (
        source_file    nvarchar(255) NOT NULL PRIMARY KEY,
        file_hash      varchar(64)   NOT NULL,
        file_rows      int           NOT NULL,
        already_present int          NOT NULL,
        inserted       int           NOT NULL,
        title_note     varchar(200)  NULL,
        loaded_at      datetime2     NOT NULL);
    """

    # finding the incremental files up front means an empty data/ for bonuses
    # simply no-ops the whole bonus

    # ------------------------- helpers -----------------------------------

    @staticmethod
    def sha_bytes(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    @classmethod
    def row_hash(cls, values) -> str:
        return hashlib.sha256(cls.ROW_HASH_SEP.join(values).encode("utf-8")).hexdigest()

    @staticmethod
    def data_columns(cur):
        cur.execute("""
            SELECT c.name FROM sys.columns c
            WHERE c.object_id = OBJECT_ID('raw.biometric_punches')
              AND c.name NOT IN ('_source_file', '_loaded_at', '_row_hash')
            ORDER BY c.column_id""")
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def read_csv_rows(path):
        # utf-8-sig transparently drops a BOM if the export has one, and behaves
        # exactly like utf-8 when it does not
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        return rows[0], rows[1:]

    def find_incremental_files(self):
        names = sorted(n for n in os.listdir(self.data_dir)
                       if n.startswith("biometric_punches") and n.endswith(".csv")
                       and n != self.CANONICAL)
        return [os.path.join(self.data_dir, n) for n in names]

    # ------------------------- per-file steps ----------------------------

    def _insert_missing_rows(self, cur, cn, headers, rows, fname):
        """Append only rows whose _row_hash is not in raw yet; aborts (and
        rolls back) when the row-count reconciliation does not hold exactly."""
        existing = set(r[0] for r in cur.execute(
            f"SELECT _row_hash FROM raw.{self.TABLE} WHERE _row_hash IS NOT NULL"))
        before = cur.execute(f"SELECT COUNT(*) FROM raw.{self.TABLE}").fetchval()

        already, news = 0, []
        for r in rows:
            rh = self.row_hash(r)
            if rh in existing:
                already += 1
            else:
                news.append((*r, fname, dt.datetime.now(), rh))

        cur.fast_executemany = True
        if news:
            cur.executemany(
                f"INSERT INTO raw.{self.TABLE} ({', '.join('[' + c + ']' for c in headers)},"
                f"_source_file, _loaded_at, _row_hash) "
                f"VALUES ({', '.join('?' * len(headers))}, ?, ?, ?)", news)
        cur.fast_executemany = False
        after = cur.execute(f"SELECT COUNT(*) FROM raw.{self.TABLE}").fetchval()
        if after != before + len(news):
            cn.rollback()
            sys.exit(f"ABORT: {fname} inserted {len(news)} but count moved "
                     f"{before} -> {after}; rolled back.")
        return before, after, already, news

    def _log_verdict(self, cur, fname, file_hash, rows, already, news):
        """raw.incremental_loads upsert: one auditable row per delivery."""
        cur.execute(self.DDL_LOG)
        cur.execute("SELECT 1 FROM raw.incremental_loads WHERE source_file = ?", fname)
        verdict = "inserted" if news else "no new rows"
        if cur.fetchval():
            cur.execute("""UPDATE raw.incremental_loads
                           SET file_hash = ?, file_rows = ?, already_present = ?,
                               inserted = ?, title_note = ?, loaded_at = ?
                           WHERE source_file = ?""",
                        file_hash, len(rows), already,
                        len(news), verdict, dt.datetime.now(), fname)
        else:
            cur.execute("""INSERT INTO raw.incremental_loads
                           (source_file, file_hash, file_rows, already_present,
                            inserted, title_note, loaded_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        fname, file_hash, len(rows), already, len(news), verdict, dt.datetime.now())

    def process_file(self, cur, cn, path):
        fname = os.path.basename(path)
        file_hash = self.sha_bytes(open(path, "rb").read())
        headers, rows = self.read_csv_rows(path)
        cols = self.data_columns(cur)
        if headers != cols:
            sys.exit(f"ABORT: {fname} header {headers} != raw.{self.TABLE} columns {cols}")

        before, after, already, news = self._insert_missing_rows(cur, cn, headers, rows, fname)
        self._log_verdict(cur, fname, file_hash, rows, already, news)
        cn.commit()

        print(f"{fname}: {len(rows):,} rows in file | already in raw: {already:,} "
              f"| inserted: {len(news):,} | raw total {before:,} -> {after:,}")
        if news:
            months = sorted(set(r[headers.index('punch_time')][:7] for r in news))
            print(f"  punch months covered by the NEW rows: {months}")

    # ------------------------- public entry -------------------------------

    def run(self) -> int:
        # no argument = standard behaviour (canonically-named incremental files
        # in data/); an explicit path lets a mentor demonstrate the bonus without
        # touching the canonical dataset folder.
        if len(sys.argv) > 1:
            files = [os.path.abspath(p) for p in sys.argv[1:]]
            for p in files:
                if not os.path.exists(p):
                    sys.exit(f"ABORT: {p} does not exist.")
        else:
            files = self.find_incremental_files()
            if not files:
                print("no incremental punch exports found in data/ "
                      "(any file named biometric_punches*.csv except the full "
                      "biometric_punches.csv) — nothing to do; this is the normal "
                      "outcome until the seventh month actually arrives.")
                return 0
        cn = self.connection()
        cur = cn.cursor()
        for path in files:
            self.process_file(cur, cn, path)
        print("\nnext: re-run the idempotent chain so these punches reach the "
              "warehouse exactly once:\n"
              "  pipeline/transform/stage2/stage2_bullet03_map_and_reject_punches.py\n"
              "  pipeline/transform/stage2/stage2_bullet05_punches_dedup_2min.py\n"
              "  pipeline/transform/stage2/stage2_bullet04_device_clock.py\n"
              "  pipeline/transform/stage3/stage3_attendance_daily.py\n"
              "  (then sqlcmd stage4 DDL, stage 5, stage 6 — or just run_pipeline.py)")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(IncrementalPunchLoader().run())
