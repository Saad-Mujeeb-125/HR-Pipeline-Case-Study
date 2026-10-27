"""BONUS B4 of the case-study PDF (p.7):
    "A simple dashboard in any tool, built on the warehouse tables."

Tool chosen: plain Python + the DB helper + ONE self-contained HTML file
(bonus_b4_dashboard.html). No JS framework, no chart library, no extra
installs — every chart is a styled <div> bar, so any browser opens it and a
human can read every number in the source. Every panel reads ONLY the
warehouse star schema (dim_* / fact_*), which is the point of the bonus:
the dashboard proves the warehouse actually serves the business story.

Panels (each with the exact warehouse query in the SQL dict below):
  1  KPI tiles        attendance rows, current employees, approved OT hours,
                      paid leave days, total EARNING paid, employees paid
  2  Attendance mix   fact_attendance_daily status distribution
  3  Payroll trend    monthly EARNING total (the CFO's money view)
  4  OT: paid vs approved by department — D20 Stitching overpayment
                      (paid units vs approved hours) pops out here
  5  Ghost pay        EARNING paid for months AFTER the separation month
                      (the q08 finding, re-derived from the warehouse)
  6  Paid leave days  fact_leave_day by leave_type

Usage:
    python -X utf8 pipeline/presentation/bonus_b4_dashboard.py
    python -X utf8 pipeline/presentation/bonus_b4_dashboard.py --open
"""
import datetime as dt
import os
import sys
import textwrap

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))     # repo-root presentation/
_SRC_ROOT = os.path.dirname(_SRC_DIR)                     # repo root
if _SRC_ROOT not in sys.path:
    sys.path.append(_SRC_ROOT)

from pipeline_base import PipelineTask  # noqa: E402


class BonusB4Dashboard(PipelineTask):
    """Bonus B4 — dependency-free HTML dashboard over warehouse.* only."""

    OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "bonus_b4_dashboard.html")

    SQL = {
        # ---- 1. KPI tiles ---------------------------------------------------
        "kpis": """
        SELECT
            (SELECT COUNT(*) FROM warehouse.fact_attendance_daily)              AS attendance_rows,
            (SELECT COUNT(*) FROM warehouse.dim_employee WHERE is_current = 1)   AS current_employees,
            (SELECT SUM(approved_hours) FROM warehouse.fact_overtime_approved)   AS approved_ot_hours,
            (SELECT COUNT(*) FROM warehouse.fact_leave_day)                      AS paid_leave_days,
            (SELECT SUM(amount) FROM warehouse.fact_payroll_line
             WHERE component_type = 'EARNING')                                   AS total_earning,
            (SELECT COUNT(DISTINCT emp_id)
             FROM warehouse.fact_payroll_line)                                   AS employees_paid
        """,
        # ---- 2. attendance status mix ---------------------------------------
        "status_mix": """
        SELECT status, COUNT(*) AS n
        FROM warehouse.fact_attendance_daily
        GROUP BY status ORDER BY n DESC
        """,
        # ---- 3. monthly payroll trend ---------------------------------------
        "payroll_trend": """
        SELECT payroll_month, SUM(amount) AS earning
        FROM warehouse.fact_payroll_line
        WHERE component_type = 'EARNING'
        GROUP BY payroll_month ORDER BY payroll_month
        """,
        # ---- 4. overtime: PAID units (payroll) vs COMPUTED OT (attendance) ---
        # q06's definition: the +56% Stitching overpayment is paid units vs
        # worked/computed ot_hours, NOT vs approved hours (approvals match pay).
        "ot_by_dept": """
        SELECT d.dept_name,
               ISNULL(c.computed_ot_hours, 0) AS computed_ot_hours,
               ISNULL(p.paid_ot_units, 0)     AS paid_ot_units
        FROM warehouse.dim_department d
        LEFT JOIN (SELECT dept_id, SUM(ot_hours) AS computed_ot_hours
                   FROM warehouse.fact_attendance_daily GROUP BY dept_id) c
                   ON c.dept_id = d.dept_id
        LEFT JOIN (SELECT dept_id, SUM(units) AS paid_ot_units
                   FROM warehouse.fact_payroll_line
                   WHERE component = 'OVERTIME' GROUP BY dept_id) p
                   ON p.dept_id = d.dept_id
        WHERE ISNULL(c.computed_ot_hours, 0) + ISNULL(p.paid_ot_units, 0) > 0
        ORDER BY p.paid_ot_units DESC
        """,
        # ---- 5. ghost pay: paid months strictly AFTER the separation month --
        # (the q08 definition; months sum must equal 21 and E10471 tops the list)
        "ghost_pay": """
        SELECT p.emp_id,
               MAX(e.full_name) AS full_name,
               COUNT(DISTINCT p.payroll_month) AS months_after_separation,
               SUM(CASE WHEN p.component_type = 'EARNING' THEN p.amount ELSE 0 END) AS earned_after
        FROM warehouse.fact_payroll_line p
        JOIN warehouse.dim_employee e
             ON e.emp_id = p.emp_id AND e.is_current = 0
        WHERE TRY_CONVERT(date, p.payroll_month + '-01')
            > CONVERT(date, CONVERT(char(7), e.separation_date, 126) + '-01')
        GROUP BY p.emp_id
        HAVING SUM(CASE WHEN p.component_type = 'EARNING' THEN p.amount ELSE 0 END) > 0
        ORDER BY earned_after DESC
        """,
        # ---- 6. paid leave days by type -------------------------------------
        "leave_by_type": """
        SELECT leave_type, COUNT(*) AS n
        FROM warehouse.fact_leave_day
        GROUP BY leave_type ORDER BY n DESC
        """,
    }

    CSS = textwrap.dedent("""
    body { font-family: 'Segoe UI', Arial, sans-serif; margin: 24px auto; max-width: 1100px;
           color: #1d2733; background: #f4f6f9; }
    h1 { font-size: 22px; border-bottom: 3px solid #20456b; padding-bottom: 8px; }
    h2 { font-size: 16px; margin: 30px 0 8px; color: #20456b; }
    .sub { color: #5a6b7d; font-size: 13px; }
    .tiles { display: flex; flex-wrap: wrap; gap: 12px; }
    .tile { background: #fff; border: 1px solid #d8dee7; border-radius: 8px;
            padding: 14px 18px; min-width: 170px; box-shadow: 0 1px 2px rgba(0,0,0,.06); }
    .tile .v { font-size: 24px; font-weight: 700; color: #20456b; }
    .tile .l { font-size: 12px; color: #5a6b7d; margin-top: 2px; }
    .bar-row { display: flex; align-items: center; margin: 4px 0; }
    .bar-l { width: 190px; font-size: 13px; text-align: right; padding-right: 8px; }
    .bar-a { flex: 1; background: #e8edf4; border-radius: 4px; position: relative; height: 22px; }
    .bar-f { background: linear-gradient(90deg, #2e6da4, #57a0d3); border-radius: 4px;
             height: 22px; min-width: 2px; }
    .bar-v { width: 110px; font-size: 13px; padding-left: 8px; white-space: nowrap; }
    table { border-collapse: collapse; background: #fff; }
    th, td { border: 1px solid #d8dee7; padding: 6px 12px; font-size: 13px; }
    th { background: #20456b; color: #fff; }
    tr.flag td { background: #fdecec; font-weight: 600; }
    """)

    HTML_HEAD = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="en"><head><meta charset="utf-8">
    <title>Indus Weave Textiles - PeopleOps Dashboard</title>
    <style>{css}</style></head><body>
    <h1>Indus Weave Textiles &mdash; PeopleOps Dashboard</h1>
    <div class="sub">Generated {gen} &middot; reads ONLY the IndusWeaveHR warehouse
    star schema (dim_* / fact_*) &middot; bonus task B4, case-study PDF p.7</div>
    """)
    HTML_FOOT = "\n</body></html>\n"

    # ------------------------- helpers ---------------------------------------

    @staticmethod
    def fmt(v):
        if v is None:
            return "&mdash;"
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,}"

    @classmethod
    def bars(cls, rows, decimals=0):
        """rows = [(label, value, flag)]; renders relative CSS bars."""
        top = float(max(float(v) for _, v, _ in rows) or 1)
        out = []
        for label, val, flag in rows:
            val = float(val)
            pct = 100.0 * val / top
            shown = f"{val:=,.{decimals}f}"
            out.append(f'<div class="bar-row"><div class="bar-l">{label}</div>'
                       f'<div class="bar-a"><div class="bar-f" style="width:{pct:.1f}%"'
                       f'{";background:linear-gradient(90deg,#c0392b,#e07b6e)" if flag else ""}'
                       f'></div></div><div class="bar-v">{shown}</div></div>')
        return "\n".join(out)

    @staticmethod
    def table(headers, rows, flag_col=None):
        """rows: tuples; if flag_col is set, that position marks a red row and is
        NOT printed."""
        head = "".join(f"<th>{h}</th>" for h in headers)
        body = []
        for row in rows:
            cls = ' class="flag"' if flag_col is not None and row[flag_col] else ""
            vals = row[: flag_col] + row[flag_col + 1:] if flag_col is not None else row
            cells = "".join(f"<td>{v if isinstance(v, str) else BonusB4Dashboard.fmt(v)}</td>" for v in vals)
            body.append(f"<tr{cls}>{cells}</tr>")
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    # ------------------------- steps -----------------------------------------

    def _fetch(self, cur):
        """Run every panel query once; {panel_name: rows}."""
        return {k: cur.execute(sql).fetchall() for k, sql in self.SQL.items()}

    def self_check_ghosts(self, ghosts):
        """Self-check the ghost-pay panel against the q07/q08 finding (21
        months, 5 employees): wrong warehouse state must be VISIBLE, not silent."""
        months_total = sum(g[2] for g in ghosts)
        print(f"self-check: ghost-pay months = {months_total} (q07 said 21), "
              f"employees = {len(ghosts)} (q08 said 5), top = {ghosts[0][0] if ghosts else None}")

    @classmethod
    def build_html(cls, data) -> str:
        """All panels -> the final self-contained HTML document."""
        k = data["kpis"][0]

        ghosts = [(g[0], g[1], int(g[2]), float(g[3])) for g in data["ghost_pay"]]
        tiles = [
            (cls.fmt(k[0]), "attendance employee-days"),
            (cls.fmt(k[1]), "current employees"),
            (cls.fmt(k[2] or 0), "approved OT hours"),
            (cls.fmt(k[3] or 0), "paid leave days"),
            ("PKR " + cls.fmt(k[4] or 0), "payroll EARNING (6 months)"),
            (cls.fmt(k[5] or 0), "distinct employees paid"),
        ]
        status_rows = [(s, n, False) for s, n in data["status_mix"]]
        trend_rows = [(m, e, False) for m, e in data["payroll_trend"]]
        ot_rows = [(nm, co, po, po > co * 1.05) for nm, co, po in
                   [(r[0], float(r[1]), float(r[2])) for r in data["ot_by_dept"]]]
        leave_rows = [(t, n, False) for t, n in data["leave_by_type"]]

        html = [cls.HTML_HEAD.format(css=cls.CSS,
                                     gen=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))]

        html.append("<div class='tiles'>")
        for v, l in tiles:
            html.append(f"<div class='tile'><div class='v'>{v}</div><div class='l'>{l}</div></div>")
        html.append("</div>")

        html.append("<h2>Attendance status mix (217k employee-days, Apr&ndash;Sep 2026)</h2>")
        html.append(cls.bars(status_rows))

        html.append("<h2>Payroll EARNING by month</h2>")
        html.append(cls.bars(trend_rows))

        html.append("<h2>Overtime: PAID units (payroll) vs COMPUTED hours (attendance) "
                    "per department &mdash; red = paid &gt; computed +5% (the q06 finding)</h2>")
        top_ot = [(nm, co, po, fl) for nm, co, po, fl in ot_rows][:10]
        html.append(cls.bars([(f"{nm} &middot; computed {co:,.0f} h", po, fl)
                              for nm, co, po, fl in top_ot], decimals=1))

        html.append("<h2>Ghost pay &mdash; months paid strictly AFTER separation "
                    "(q08 finding re-derived from the warehouse)</h2>")
        html.append(cls.table(["emp_id", "employee", "months after separation", "PKR paid after"],
                              [(e, n, m, a, False) for e, n, m, a in ghosts], flag_col=4))

        html.append("<h2>Paid leave days by type</h2>")
        html.append(cls.bars(leave_rows))

        html.append(cls.HTML_FOOT)
        return "\n".join(html)

    # ------------------------- public entry -----------------------------------

    def run(self) -> int:
        open_browser = "--open" in sys.argv
        with self.connection() as cn:
            cur = cn.cursor()
            data = self._fetch(cur)

        ghosts = [(g[0], g[1], int(g[2]), float(g[3])) for g in data["ghost_pay"]]
        # ghost self-check happens before writing (visible console evidence)
        self.self_check_ghosts(ghosts)

        html = self.build_html(data)
        with open(self.OUT, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"dashboard written -> {self.OUT} ({os.path.getsize(self.OUT):,} bytes)")
        if open_browser:
            os.startfile(self.OUT)
        return 0


if __name__ == "__main__":
    sys.exit(BonusB4Dashboard().run())
