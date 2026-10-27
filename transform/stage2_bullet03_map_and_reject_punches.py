"""STAGE 2, bullet 3 of the case-study PDF (p.5):
    "Map device user IDs to employees. Park unmapped punches in a
     staging.rejected_punches table with a reason."
Business rule: rule 8 (device_mapping, keyed device_id + device_user_id).

What it builds:
  staging.punches_mapped     — punches joined to employees, typed timestamp
  staging.rejected_punches   — punches with no mapping (contractors/visitors),
                               rebuilt from scratch here with reason
                               'unmapped_device_user'. (Duplicates from bullet 5
                               are re-added by stage2_bullet05 after this runs.)

Run AFTER nothing; BEFORE: stage2_bullet05_punches_dedup_2min.py
    python -X utf8 pipeline/transform/stage2/stage2_bullet03_map_and_reject_punches.py
"""
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage2Bullet03MapAndRejectPunches(PipelineTask):
    """Stage 2 bullet 3 — rule 8 device mapping + rejected-punches parking."""

    SQL_MAPPING_CHECK = """
    SELECT COUNT(*) AS total_rows,
           COUNT(DISTINCT CONCAT(device_id, '|', device_user_id)) AS distinct_pairs
    FROM raw.device_mapping
    """

    SQL_CREATE_MAPPED = """
    IF OBJECT_ID('staging.punches_mapped') IS NOT NULL DROP TABLE staging.punches_mapped;
    SELECT p.punch_id,
           p.device_id,
           p.device_user_id,
           p.punch_time,                                        -- original text as delivered
           TRY_CONVERT(datetime2(0), p.punch_time) AS punch_ts, -- same value, typed
           m.emp_id                                             -- resolved via device mapping
    INTO staging.punches_mapped
    FROM raw.biometric_punches p
    JOIN raw.device_mapping m
         ON m.device_id       = p.device_id
        AND m.device_user_id  = p.device_user_id;
    """

    SQL_CREATE_REJECTED = """
    IF OBJECT_ID('staging.rejected_punches') IS NOT NULL DROP TABLE staging.rejected_punches;
    SELECT p.punch_id, p.device_id, p.device_user_id, p.punch_time,
           CAST(NULL AS varchar(20)) AS emp_id,
           CAST('unmapped_device_user' AS varchar(40)) AS reason   -- rule 8: no employee match
    INTO staging.rejected_punches
    FROM raw.biometric_punches p
    WHERE NOT EXISTS (
          SELECT 1 FROM raw.device_mapping m
          WHERE m.device_id      = p.device_id
            AND m.device_user_id = p.device_user_id);
    """

    def _guard_mapping(self, cur):
        """device_mapping must have exactly one row per (device, device_user)."""
        total, pairs = cur.execute(self.SQL_MAPPING_CHECK).fetchone()
        if total != pairs:
            sys.exit(f"ABORT: device_mapping rows ({total}) != unique pairs ({pairs}) — join not safe.")
        self.log(f"device_mapping OK: {total:,} rows, all (device_id, device_user_id) pairs unique")

    def _rebuild(self, cur, cn):
        """Map punches to employees (rule 8), then park unmapped ones with a
        reason; committed only after the reconcile equation holds."""
        raw_total = cur.execute("SELECT COUNT(*) FROM raw.biometric_punches").fetchval()

        cur.execute(self.SQL_CREATE_MAPPED)
        mapped = cur.execute("SELECT COUNT(*) FROM staging.punches_mapped").fetchval()

        # parse sanity: none of the typed timestamps may be NULL
        unparsed = cur.execute("SELECT COUNT(*) FROM staging.punches_mapped WHERE punch_ts IS NULL").fetchval()
        if unparsed:
            sys.exit(f"ABORT: {unparsed} punch_time values could not be parsed.")

        cur.execute(self.SQL_CREATE_REJECTED)
        unmapped = cur.execute(
            "SELECT COUNT(*) FROM staging.rejected_punches WHERE reason = 'unmapped_device_user'"
        ).fetchval()

        cn.commit()
        return raw_total, mapped, unmapped

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        try:
            self._guard_mapping(cur)
            raw_total, mapped, unmapped = self._rebuild(cur, cn)
        except Exception:
            cn.rollback()
            raise

        print(f"raw.biometric_punches     : {raw_total:,} rows")
        print(f"staging.punches_mapped    : {mapped:,} rows  (timestamps all parse)")
        print(f"staging.rejected_punches  : {unmapped:,} rows, reason 'unmapped_device_user'")
        print(f"check: mapped {mapped:,} + unmapped {unmapped:,} = {mapped + unmapped:,}"
              f"  {'OK' if mapped + unmapped == raw_total else 'MISMATCH!'}")
        print("next: run stage2_bullet05_punches_dedup_2min.py")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage2Bullet03MapAndRejectPunches().run())
