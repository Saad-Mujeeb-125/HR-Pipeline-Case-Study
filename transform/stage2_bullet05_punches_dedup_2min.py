"""STAGE 2, bullet 5 of the case-study PDF (p.5):
    "Remove duplicate punches using the 2-minute rule."
Business rule: rule 9 — "Two punches by the same employee within 2 minutes
count as one."

Method ("islands"): partition a punch stream by employee; a punch starts a NEW
punch when the gap from the PREVIOUS punch is MORE than 120 seconds; every
punch inside a group except the earliest is a duplicate. This is provably
correct for chains (e.g. punches 0s/90s/180s must keep 0s and 180s), unlike a
naive LAG comparison that compares against already-removed rows. The boundary
is inclusive: "within 2 minutes" means a gap of exactly 120 s still merges.

What it builds:
  staging.punches_deduped                          — one row per real punch
  staging.rejected_punches (+ reason
      'duplicate_within_2_minutes', rows refreshed) — duplicates parked here so
                                                      raw = deduped + rejected

Run AFTER stage2_bullet03_map_and_reject_punches.py (needs staging.punches_mapped).
    python -X utf8 pipeline/transform/stage2/stage2_bullet05_punches_dedup_2min.py
"""
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from pipeline_base import PipelineTask  # noqa: E402


class Stage2Bullet05PunchesDedup2Min(PipelineTask):
    """Stage 2 bullet 5 — rule 9 2-minute dedup via the islands method."""

    GAP_SEC = 120  # rule 9: two punches within this gap count as one

    SQL_TABLES_READY = """
    SELECT SUM(CASE WHEN t.name = 'punches_mapped'   THEN 1 ELSE 0 END) AS has_mapped,
           SUM(CASE WHEN t.name = 'rejected_punches' THEN 1 ELSE 0 END) AS has_rejected
    FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = 'staging' AND t.name IN ('punches_mapped', 'rejected_punches')
    """

    SQL_CLUSTER_AND_RANK = f"""
    IF OBJECT_ID('tempdb..#punch_ranked') IS NOT NULL DROP TABLE #punch_ranked;
    WITH gaps AS (
        -- rule 9: a punch starts a NEW punch when the previous punch of the same
        -- employee is more than {{gap}} seconds earlier (or there is no previous one)
        SELECT punch_id, device_id, device_user_id, punch_time, punch_ts, emp_id,
               CASE WHEN LAG(punch_ts) OVER (
                         PARTITION BY emp_id ORDER BY punch_ts, punch_id) IS NULL
                         OR DATEDIFF(SECOND,
                                     LAG(punch_ts) OVER (
                                         PARTITION BY emp_id ORDER BY punch_ts, punch_id),
                                     punch_ts) > {{gap}}
                    THEN 1 ELSE 0 END AS starts_new_punch
        FROM staging.punches_mapped
    ),
    punch_groups AS (
        -- running total of "starts_new_punch" gives every punch a group number
        SELECT punch_id, device_id, device_user_id, punch_time, punch_ts, emp_id,
               SUM(starts_new_punch) OVER (
                   PARTITION BY emp_id ORDER BY punch_ts, punch_id
                   ROWS UNBOUNDED PRECEDING) AS punch_cluster
        FROM gaps
    )
    SELECT punch_id, device_id, device_user_id, punch_time, punch_ts, emp_id,
           ROW_NUMBER() OVER (
               PARTITION BY emp_id, punch_cluster
               ORDER BY punch_ts, punch_id) AS dup_rank    -- 1 = the punch we keep
    INTO #punch_ranked
    FROM punch_groups;
    """

    SQL_CREATE_DEDUPED = """
    IF OBJECT_ID('staging.punches_deduped') IS NOT NULL DROP TABLE staging.punches_deduped;
    SELECT punch_id, emp_id, punch_ts, device_id, device_user_id
    INTO staging.punches_deduped
    FROM #punch_ranked
    WHERE dup_rank = 1;
    """

    SQL_REFILL_DUP_REJECTIONS = """
    DELETE FROM staging.rejected_punches WHERE reason = 'duplicate_within_2_minutes';
    INSERT INTO staging.rejected_punches
          (punch_id, device_id, device_user_id, punch_time, emp_id, reason)
    SELECT punch_id, device_id, device_user_id, punch_time, emp_id,
           'duplicate_within_2_minutes'                        -- rule 9
    FROM #punch_ranked
    WHERE dup_rank > 1;
    """

    SQL_NAIVE_LAG_COUNT = """
    -- What a naive "drop anything within 2 min of the raw previous punch" would drop
    SELECT COUNT(*)
    FROM (SELECT CASE WHEN DATEDIFF(SECOND,
                                    LAG(punch_ts) OVER (
                                        PARTITION BY emp_id ORDER BY punch_ts, punch_id),
                                    punch_ts) <= 120
                      THEN 1 END AS d
          FROM staging.punches_mapped) x
    WHERE d = 1
    """

    SQL_RECONCILIATION = """
    SELECT
        (SELECT COUNT(*) FROM raw.biometric_punches)                                                AS raw_total,
        (SELECT COUNT(*) FROM staging.punches_deduped)                                              AS deduped,
        (SELECT COUNT(*) FROM staging.rejected_punches WHERE reason = 'duplicate_within_2_minutes') AS rej_dupes
    """

    def _rebuild(self, cur):
        """rule 9 via the islands method, plus the naive-LAG teaching aid."""
        # Guards: this step depends on bullet 3 outputs.
        has_mapped, has_rejected = cur.execute(self.SQL_TABLES_READY).fetchone()
        if not has_mapped or not has_rejected:
            sys.exit("ABORT: run stage2_bullet03_map_and_reject_punches.py first "
                     "(staging.punches_mapped / staging.rejected_punches missing).")

        cur.execute(self.SQL_CLUSTER_AND_RANK.format(gap=self.GAP_SEC))
        cur.execute(self.SQL_CREATE_DEDUPED)
        deduped = cur.execute("SELECT COUNT(*) FROM staging.punches_deduped").fetchval()
        cur.execute(self.SQL_REFILL_DUP_REJECTIONS)
        rej_dupes = cur.execute(
            "SELECT COUNT(*) FROM staging.rejected_punches WHERE reason = 'duplicate_within_2_minutes'"
        ).fetchval()
        cur.execute("DROP TABLE #punch_ranked")

        naive = cur.execute(self.SQL_NAIVE_LAG_COUNT).fetchval()
        return deduped, rej_dupes, naive

    def run(self) -> int:
        cn = self.connection()
        cur = cn.cursor()
        try:
            deduped, rej_dupes, naive = self._rebuild(cur)
            extra = naive - rej_dupes
            print(f"staging.punches_deduped   : {deduped:,} rows")
            print(f"rejected as 2-min dupes   : {rej_dupes:,} rows")
            print(f"naive LAG would have dropped {naive:,}; islands dropped {rej_dupes:,}"
                  f"  -> {extra:,} extra rows a naive version would wrongly delete"
                  if extra else "naive LAG and islands agree on this dataset")
            cn.commit()
        except Exception:
            cn.rollback()
            raise

        raw_total, deduped_t, rej_dupes_t = cur.execute(self.SQL_RECONCILIATION).fetchone()
        unmapped_t = cur.execute(
            "SELECT COUNT(*) FROM staging.rejected_punches WHERE reason = 'unmapped_device_user'"
        ).fetchval()

        print()
        print("RECONCILIATION (raw = deduped + rejected)")
        print(f"  raw.biometric_punches      = {raw_total:,}")
        print(f"  staging.punches_deduped    = {deduped_t:,}")
        print(f"  + rejected (2-min dupes)   = {rej_dupes_t:,}")
        print(f"  + rejected (unmapped)      = {unmapped_t:,}")
        balance = deduped_t + rej_dupes_t + unmapped_t
        print(f"  = {balance:,}  {'OK' if balance == raw_total else 'MISMATCH!'}")
        cn.close()
        return 0


if __name__ == "__main__":
    sys.exit(Stage2Bullet05PunchesDedup2Min().run())
