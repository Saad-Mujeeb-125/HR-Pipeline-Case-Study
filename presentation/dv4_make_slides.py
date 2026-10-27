"""DELIVERABLE DV4 of the case-study PDF (p.7):

    "slides.pdf (max 6 slides) for the 5-minute demo."

Builds the deck with python-pptx (each slide written by one small method so a
human can defend every line), then converts the .pptx to .pdf with the locally
installed PowerPoint via COM automation (win32com) — no extra installs.

Numbers are the verified pipeline results (see presentation/cfo_findings.md and
pipeline/warehouse/analytics/*_result.csv); do not edit them here without
re-running the pipeline.

Output:   presentation/slides.pptx + presentation/slides.pdf
Usage:    python -X utf8 pipeline/presentation/dv4_make_slides.py [--pptx-only]
"""
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))     # repo-root presentation/
_SRC_ROOT = os.path.dirname(_SRC_DIR)                     # repo root
if _SRC_ROOT not in sys.path:
    sys.path.append(_SRC_ROOT)

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt


class Dv4SlideDeck:
    """DV4 — the 6-slide demo deck: story, evidence, actions."""

    # DV4 deliverables live in the REPO-ROOT presentation/ folder
    # (this file sits in pipeline/presentation/, so that's ../../presentation)
    _PRES_DIR = os.path.abspath(os.path.join(_SRC_DIR, "..", "..", "presentation"))
    OUT_PPTX = os.path.join(_PRES_DIR, "slides.pptx")
    OUT_PDF = os.path.join(_PRES_DIR, "slides.pdf")

    NAVY = RGBColor(0x20, 0x45, 0x6B)      # headings
    STEEL = RGBColor(0x5A, 0x6B, 0x7D)     # secondary text
    RED = RGBColor(0xC0, 0x39, 0x2B)       # finding highlights
    GREEN = RGBColor(0x1E, 0x7A, 0x3C)     # DQ / good state
    DARK = RGBColor(0x1D, 0x27, 0x33)      # body text

    def __init__(self):
        self.prs = Presentation()
        # 16:9
        self.prs.slide_width = Inches(13.333)
        self.prs.slide_height = Inches(7.5)
        self.blank = self.prs.slide_layouts[6]   # fully blank slide

    # ---------------- slide scaffolding helpers ----------------

    def _add_slide(self):
        return self.prs.slides.add_slide(self.blank)

    @staticmethod
    def _box(slide, left, top, width, height):
        tb = slide.shapes.add_textbox(Inches(left), Inches(top),
                                      Inches(width), Inches(height))
        tf = tb.text_frame
        tf.word_wrap = True
        return tf

    @classmethod
    def _title(cls, slide, text, sub=None):
        tf = cls._box(slide, 0.55, 0.32, 12.3, 1.15)
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = text
        r.font.size = Pt(34)
        r.font.bold = True
        r.font.color.rgb = cls.NAVY
        if sub:
            p2 = tf.add_paragraph()
            r2 = p2.add_run()
            r2.text = sub
            r2.font.size = Pt(15)
            r2.font.color.rgb = cls.STEEL
        return tf

    @classmethod
    def _bullets(cls, tf, items):
        """items: list of (level, text, color|None, bold|None, size|None)."""
        first = True
        for level, text, color, bold, size in items:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.level = level
            r = p.add_run()
            r.text = text
            r.font.size = Pt(size or (20 if level == 0 else 16))
            r.font.bold = bool(bold)
            r.font.color.rgb = color if color is not None else cls.DARK
            p.space_after = Pt(9)

    @classmethod
    def _kicker(cls, slide, text, color):
        """Small bold line at the bottom (the 'so what' of the slide)."""
        tf = cls._box(slide, 0.55, 6.55, 12.3, 0.75)
        r = tf.paragraphs[0].add_run()
        r.text = text
        r.font.size = Pt(17)
        r.font.bold = True
        r.font.color.rgb = color

    # ---------------- the six slides ----------------

    def slide_title(self):
        s = self._add_slide()
        tf = self._box(s, 0.9, 2.35, 11.6, 2.9)
        r = tf.paragraphs[0].add_run()
        r.text = "Indus Weave Textiles — HR Data Pipeline & Payroll Audit"
        r.font.size = Pt(40)
        r.font.bold = True
        r.font.color.rgb = self.NAVY
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = ("PeopleOps Data Hackathon · six months of HCM exports (Apr–Sep 2026) · "
                   "Python 3.14 + SQL Server 2025 Express")
        r2.font.size = Pt(18)
        r2.font.color.rgb = self.STEEL
        p3 = tf.add_paragraph()
        p3.space_before = Pt(26)
        r3 = p3.add_run()
        r3.text = "One command rebuilds everything:   python -X utf8 pipeline/run_pipeline.py"
        r3.font.size = Pt(20)
        r3.font.bold = True
        r3.font.color.rgb = self.DARK

    def slide_pipeline(self):
        s = self._add_slide()
        self._title(s, "Pipeline in one command — six stages, 13 steps",
                    "345,280 punches reconcile to the row; every raw export untouched")
        tf = self._box(s, 0.55, 1.75, 12.3, 4.7)
        self._bullets(tf, [
            (0, "Stage 1 — ingest 12 files exactly as delivered  ·  columns as text, "
                "provenance columns, hash-based idempotence", None, False, 19),
            (0, "Stage 2 — seven cleaning bullets, every fix in CODE:", None, False, 19),
            (1, "3 mixed date formats → DATE   ·   1,316 duplicate-key rows → 1,266 employees + 50-row merge log", None, False, 15),
            (1, "punches: 338,318 mapped → 322,143 kept / 23,137 rejected, each with a written reason", None, False, 15),
            (1, "faulty device DEV-SITE-01 (+60 min since 1 Jul) → 45,803 punch times corrected", None, False, 15),
            (1, "leave JSON flattened: 5,372 requests → 8,604 paid single days (rules 16–18)", None, False, 15),
            (0, "Stage 3 — staging.attendance_daily: 217,584 employee-days, six statuses (rule 12)", None, False, 19),
            (0, "Stage 4 — star schema: 4 dims (dim_employee SCD2 = 3,686 rows) + 4 facts, all reconciled", None, False, 19),
            (0, "Stage 5 — 10 business questions, one .sql + one result CSV each", None, False, 19),
            (0, "Stage 6 — 68 automated checks → quality.dq_results, gating the pipeline", None, False, 19),
        ])

    def slide_quality(self):
        s = self._add_slide()
        self._title(s, "Data quality: 68 checks, 0 blocking",
                    "raw = cleaned + rejected must hold for EVERY table — or the build fails")
        tf = self._box(s, 0.55, 1.75, 12.3, 4.7)
        self._bullets(tf, [
            (0, "PK (22) — uniqueness + not-null on every key", None, False, 19),
            (0, "FK (18) — every fact row finds its dimension row (both natural and surrogate keys)", None, False, 19),
            (0, "Reconciliation (13) — employees 1,316 = 1,266 + 50 · punches 345,280 = 322,143 + 23,137 · "
                "JSON documents counted with OPENJSON", None, False, 19),
            (0, "Accepted values (8) — statuses, leave types, pay components inside whitelist (rule 12/16/21)", None, False, 19),
            (0, "Sanity (7) — no negative hours, no shift > 16 h, no overlapping SCD2 ranges", None, False, 19),
            (1, "1 documented quirk = EXPECTED, not hidden: E11259 zero-length SCD2 tie (planted in source)", RGBColor(0xB0, 0x7A, 0x00), False, 15),
            (0, "Planted issues fixed in code and documented: date soup · ghost duplicates · "
                "unmapped contractor punches · 2-min double punches · device clock drift · "
                "phantom 1900-01-01 effective_to sentinels", self.GREEN, False, 17),
        ])
        self._kicker(s, "Every check WRITES its result to the DB and fails the run — quality is a gate, not a report.", self.GREEN)

    def slide_finding1(self):
        s = self._add_slide()
        self._title(s, "Finding 1 — Stitching is paid 56% more OT than the badges show",
                    "q06.sql · paid = payroll OVERTIME units (rule 20) vs computed = punch ot_hours (rules 14–15)")
        tf = self._box(s, 0.55, 1.75, 12.3, 4.6)
        self._bullets(tf, [
            (0, "D20 Stitching: paid 7,659.0 h  vs  computed 4,902.0 h  =  +56.24%", self.RED, True, 26),
            (0, "PKR 3,771,337 of OT paid to D20 — the largest OT bill in the plant (next: Weaving 1.82M)", None, False, 20),
            (0, "Only department above the 15% threshold", None, False, 20),
            (0, "Approvals match payment (7,656 h approved vs 7,659 paid) — so the gap is NOT the approval chain",
             self.RED, True, 19),
            (0, "Hypothesis to confirm by audit: pay-figure entry — the units typed into payroll",
             self.RED, True, 19),
        ])
        self._kicker(s, "Action: audit D20's six OT months unit-by-unit against clock data; project computed OT next to paid units at every payroll run.", self.NAVY)

    def slide_finding2(self):
        s = self._add_slide()
        self._title(s, "Finding 2 — Ghost pay: 5 employees paid after leaving",
                    "q08.sql · strictly-after-separation months (rule 4) · cross-checked by q07's zero-attendance logic")
        tf = self._box(s, 0.55, 1.75, 12.3, 4.6)
        self._bullets(tf, [
            (0, "5 employees · 21 payroll months · PKR 1,948,000 paid after separation", self.RED, True, 24),
            (0, "Worst case: E10471 Umair Baloch — separated 2026-04-23, PAID May–Sep = PKR 660,000", self.RED, True, 20),
            (0, "E11222 PKR 418,100 · E10332 PKR 322,000 · E10989 PKR 294,100 · E10295 PKR 253,800", None, False, 20),
            (0, "Airtight: two INDEPENDENT queries agree — separation-date comparison (q08) and "
                "attendance anti-join (q07) both find exactly 21 (employee, month) rows", self.GREEN, False, 19),
            (0, "Catchable at the first monthly close: PKR 132,000 (May) + PKR 454,000 (June) — "
                "≈ PKR 0.59M, not 1.95M; the q07 query is all it takes", None, False, 19),
        ])
        self._kicker(s, "Action: block all 5 from next payroll; recovery letters for PKR 1,948,000; make offboarding a same-day, payroll-blocking event.", self.NAVY)

    def slide_finding3(self):
        s = self._add_slide()
        self._title(s, "Finding 3 — 20 employees burned a full year's leave in 6 months",
                    "q10.sql · approved Annual days Apr–Sep vs FULL-YEAR entitlement (rule 18, Sundays excluded)")
        tf = self._box(s, 0.55, 1.75, 12.3, 4.3)
        self._bullets(tf, [
            (0, "E10770 Danish Iqbal: 28 days used vs 14 entitlement — 2× the year in half a year", self.RED, True, 22),
            (0, "19 more employees over entitlement (E10826 27/14, E10748 25/14, ...)", None, False, 20),
            (0, "Approvals exceeding entitlement means the balance check simply isn't in the loop", None, False, 20),
            (0, "Deliverables: README (rebuild in 1 command) · cfo_findings.md · ERD · HTML dashboard (bonus B4)", None, False, 17),
        ])
        self._kicker(s, "Recommendation: enforce the balance gate in the approval UI; audit every approval that pushed past entitlement.", self.NAVY)

    def save(self):
        self.prs.save(self.OUT_PPTX)
        return os.path.abspath(self.OUT_PPTX)

    def to_pdf(self):
        """Convert the saved .pptx with the installed PowerPoint (COM)."""
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        app = win32com.client.Dispatch("PowerPoint.Application")
        pres = app.Presentations.Open(os.path.abspath(self.OUT_PPTX),
                                      WithWindow=False)
        pres.SaveAs(os.path.abspath(self.OUT_PDF), 32)   # 32 = ppSaveAsPDF
        pres.Close()
        app.Quit()
        return os.path.abspath(self.OUT_PDF)

    def run(self) -> int:
        builders = [self.slide_title, self.slide_pipeline, self.slide_quality,
                    self.slide_finding1, self.slide_finding2, self.slide_finding3]
        for b in builders:
            b()
        print(f"slides: {len(self.prs.slides)} (expect 6)")
        pptx = self.save()
        print(f"pptx -> {pptx} ({os.path.getsize(pptx):,} bytes)")
        if "--pptx-only" not in sys.argv:
            pdf = self.to_pdf()
            print(f"pdf  -> {pdf} ({os.path.getsize(pdf):,} bytes)")
        return 0


if __name__ == "__main__":
    sys.exit(Dv4SlideDeck().run())
