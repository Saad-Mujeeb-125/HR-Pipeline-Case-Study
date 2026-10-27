/* =====================================================================
STAGE 4, part 2 of the case-study PDF (p.6):
  "Facts: fact_attendance_daily, fact_leave_day, fact_overtime_approved,
   fact_payroll_line."
Grain and keys (star schema, PK/FK enforced):
  fact_attendance_daily  one row per employee per employment day (217,584)
                         FKs: dim_employee (validity period), dim_date,
                              dim_department (rule 2: department at that date),
                              dim_shift.
  fact_leave_day         one row per approved leave day (8,604)
  fact_overtime_approved rule 19 "only status = Approved" (19,666)
  fact_payroll_line      one row per payslip line (53,617); department
                         resolved per rule 3: last day of the month, OR
                         separation_date when the employee left mid-month.

Every employee-day resolves to at most one dim_employee SCD2 period
(valid_from <= d <= valid_to or open). Fact loads join through that validity
window; rows that find no period are counted by the verify block at the end.

Run:  sqlcmd -S "localhost\SQLEXPRESS" -E -i "pipeline/warehouse/ddl/stage4_facts.sql"
Idempotent: warehouse fact tables are dropped and rebuilt.
===================================================================== */
:ON ERROR EXIT

USE IndusWeaveHR;
GO

/* --------------------------------------------------- fact_attendance_daily */
IF OBJECT_ID('warehouse.fact_attendance_daily') IS NOT NULL DROP TABLE warehouse.fact_attendance_daily;
CREATE TABLE warehouse.fact_attendance_daily (
    emp_id          varchar(20)    NOT NULL,
    work_date       date           NOT NULL,
    employee_sk     int            NOT NULL,
    date_key        int            NOT NULL,
    dept_id         varchar(10)    NOT NULL,
    shift_code      varchar(10)    NOT NULL,
    plant           varchar(60)    NOT NULL,
    status          varchar(20)    NOT NULL,
    is_from_roster  int            NOT NULL,
    punch_count     int            NOT NULL,
    check_in        datetime2      NULL,
    check_out       datetime2      NULL,
    late_minutes    int            NOT NULL,
    early_minutes   int            NOT NULL,
    ot_hours        decimal(4, 1)  NULL,
    worked_minutes  int            NULL,
    is_sunday       bit            NOT NULL,
    is_holiday      bit            NOT NULL,
    on_leave        bit            NOT NULL,
    leave_request_id varchar(20)   NULL,
    PRIMARY KEY (emp_id, work_date),
    FOREIGN KEY (employee_sk) REFERENCES warehouse.dim_employee (employee_sk),
    FOREIGN KEY (date_key)    REFERENCES warehouse.dim_date (date_key),
    FOREIGN KEY (dept_id)     REFERENCES warehouse.dim_department (dept_id),
    FOREIGN KEY (shift_code)  REFERENCES warehouse.dim_shift (shift_code)
);

INSERT INTO warehouse.fact_attendance_daily
SELECT CAST(a.emp_id AS varchar(20)), a.work_date, de.employee_sk,
       CAST(CONVERT(varchar(8), a.work_date, 112) AS int) AS date_key,
       de.dept_id, CAST(a.shift_code AS varchar(10)), CAST(a.plant AS varchar(60)),
       CAST(a.status AS varchar(20)), a.is_from_roster, a.punch_count,
       a.check_in, a.check_out, a.late_minutes, a.early_minutes, a.ot_hours,
       a.worked_minutes, a.is_sunday, a.is_holiday, a.on_leave, a.leave_request_id
FROM staging.attendance_daily a
JOIN warehouse.dim_employee de
  ON CAST(de.emp_id AS varchar(20)) = CAST(a.emp_id AS varchar(20))
 AND a.work_date >= de.valid_from
 AND a.work_date <= COALESCE(de.valid_to, '9999-12-31');
GO

/* ------------------------------------------------------------ fact_leave_day */
IF OBJECT_ID('warehouse.fact_leave_day') IS NOT NULL DROP TABLE warehouse.fact_leave_day;
CREATE TABLE warehouse.fact_leave_day (
    emp_id           varchar(20) NOT NULL,
    leave_day        date        NOT NULL,
    leave_request_id varchar(20) NOT NULL,
    employee_sk      int         NOT NULL,
    date_key         int         NOT NULL,
    dept_id          varchar(10) NOT NULL,
    leave_type       varchar(10) NOT NULL,
    plant            varchar(60) NOT NULL,
    day_in_request   int         NOT NULL,
    PRIMARY KEY (emp_id, leave_day, leave_request_id),
    FOREIGN KEY (employee_sk)      REFERENCES warehouse.dim_employee (employee_sk),
    FOREIGN KEY (date_key)         REFERENCES warehouse.dim_date (date_key),
    FOREIGN KEY (dept_id)          REFERENCES warehouse.dim_department (dept_id)
);

INSERT INTO warehouse.fact_leave_day
SELECT CAST(l.emp_id AS varchar(20)), l.leave_day, CAST(l.request_id AS varchar(20)) AS leave_request_id, de.employee_sk,
       CAST(CONVERT(varchar(8), l.leave_day, 112) AS int), de.dept_id,
       CAST(l.leave_type AS varchar(10)), CAST(l.plant AS varchar(60)), l.day_in_request
FROM staging.leave_days l
JOIN warehouse.dim_employee de
  ON CAST(de.emp_id AS varchar(20)) = CAST(l.emp_id AS varchar(20))
 AND l.leave_day >= de.valid_from
 AND l.leave_day <= COALESCE(de.valid_to, '9999-12-31');
GO

/* ---------------------------------------------------- fact_overtime_approved */
IF OBJECT_ID('warehouse.fact_overtime_approved') IS NOT NULL DROP TABLE warehouse.fact_overtime_approved;
CREATE TABLE warehouse.fact_overtime_approved (
    request_id      varchar(20)    NOT NULL PRIMARY KEY,
    emp_id          varchar(20)    NOT NULL,
    ot_date         date           NOT NULL,
    employee_sk     int            NOT NULL,
    date_key        int            NOT NULL,
    dept_id         varchar(10)    NOT NULL,
    requested_hours decimal(5, 2)  NOT NULL,
    approved_hours  decimal(5, 2)  NOT NULL,
    approver_id     varchar(30)    NULL,
    FOREIGN KEY (employee_sk) REFERENCES warehouse.dim_employee (employee_sk),
    FOREIGN KEY (date_key)    REFERENCES warehouse.dim_date (date_key),
    FOREIGN KEY (dept_id)     REFERENCES warehouse.dim_department (dept_id)
);

INSERT INTO warehouse.fact_overtime_approved   -- rule 19: status = 'Approved' only
SELECT CAST(o.request_id AS varchar(20)), CAST(o.emp_id AS varchar(20)),
       TRY_CAST(o.ot_date AS date), de.employee_sk,
       CAST(CONVERT(varchar(8), TRY_CAST(o.ot_date AS date), 112) AS int), de.dept_id,
       TRY_CAST(o.requested_hours AS decimal(5, 2)), TRY_CAST(o.approved_hours AS decimal(5, 2)),
       CAST(o.approver_id AS varchar(30))
FROM raw.overtime_requests o
JOIN warehouse.dim_employee de
  ON CAST(de.emp_id AS varchar(20)) = CAST(o.emp_id AS varchar(20))
 AND TRY_CAST(o.ot_date AS date) >= de.valid_from
 AND TRY_CAST(o.ot_date AS date) <= COALESCE(de.valid_to, '9999-12-31')
WHERE CAST(o.status AS varchar(20)) = 'Approved';
GO

/* -------------------------------------------------------- fact_payroll_line */
IF OBJECT_ID('warehouse.fact_payroll_line') IS NOT NULL DROP TABLE warehouse.fact_payroll_line;
CREATE TABLE warehouse.fact_payroll_line (
    line_id        varchar(20)     NOT NULL PRIMARY KEY,
    emp_id         varchar(20)     NOT NULL,
    employee_sk    int             NOT NULL,
    payroll_month  char(7)         NOT NULL,
    date_key       int             NOT NULL,   -- first day of the payroll month
    dept_id        varchar(10)     NOT NULL,   -- rule 3: dept at month end, or at separation
    component      varchar(30)     NOT NULL,
    component_type varchar(10)     NOT NULL,
    units          decimal(10, 2)  NULL,
    amount         decimal(14, 2)  NOT NULL,
    FOREIGN KEY (employee_sk) REFERENCES warehouse.dim_employee (employee_sk),
    FOREIGN KEY (date_key)    REFERENCES warehouse.dim_date (date_key),
    FOREIGN KEY (dept_id)     REFERENCES warehouse.dim_department (dept_id)
);

INSERT INTO warehouse.fact_payroll_line
SELECT CAST(p.line_id AS varchar(20)), CAST(p.emp_id AS varchar(20)), de.employee_sk,
       CAST(mp.payroll_month AS char(7)),
       CAST(LEFT(mp.resolve_key, 6) + '01' AS int) AS date_key,   -- month-end key -> first-of-month
       de.dept_id,
       CAST(p.component AS varchar(30)), CAST(p.component_type AS varchar(10)),
       TRY_CAST(p.units AS decimal(10, 2)), TRY_CAST(p.amount AS decimal(14, 2))
FROM raw.payroll_lines p
JOIN (
    /* rule 3: department of the LAST DAY OF THE MONTH, or of the employee's
       separation date when they left during that payroll month. */
    SELECT pl.line_id AS line_id_x,
           pl.payroll_month AS payroll_month,
           CONVERT(varchar(8), CASE
               WHEN TRY_CAST(e.separation_date AS date) IS NOT NULL
                AND TRY_CAST(e.separation_date AS date)
                    < EOMONTH(CAST(LEFT(pl.payroll_month, 7) + '-01' AS date))
               THEN TRY_CAST(e.separation_date AS date)
               ELSE EOMONTH(CAST(LEFT(pl.payroll_month, 7) + '-01' AS date))
           END, 112) AS resolve_key
    FROM raw.payroll_lines pl
    JOIN staging.employees_final e
      ON CAST(e.emp_id AS varchar(20)) = CAST(pl.emp_id AS varchar(20))
) mp ON mp.line_id_x = p.line_id
JOIN warehouse.dim_employee de
  ON CAST(de.emp_id AS varchar(20)) = CAST(p.emp_id AS varchar(20))
 AND CAST(mp.resolve_key AS date) >= de.valid_from
 AND CAST(mp.resolve_key AS date) <= COALESCE(de.valid_to, '9999-12-31');
GO

/* ------------------------------------------------------------- verify facts */
DECLARE @att_src int = (SELECT COUNT(*) FROM staging.attendance_daily);
DECLARE @att_orphan int = (
    SELECT COUNT(*) FROM staging.attendance_daily a
    WHERE NOT EXISTS (SELECT 1 FROM warehouse.fact_attendance_daily f
                      WHERE f.emp_id = CAST(a.emp_id AS varchar(20)) AND f.work_date = a.work_date));
DECLARE @lv_src int = (SELECT COUNT(*) FROM staging.leave_days);
DECLARE @lv_orphan int = (
    SELECT COUNT(*) FROM staging.leave_days l
    WHERE NOT EXISTS (SELECT 1 FROM warehouse.fact_leave_day f
                      WHERE f.emp_id = CAST(l.emp_id AS varchar(20))
                        AND f.leave_day = l.leave_day
                        AND f.leave_request_id = CAST(l.request_id AS varchar(20))));
DECLARE @ot_src int = (SELECT COUNT(*) FROM raw.overtime_requests WHERE CAST(status AS varchar(20)) = 'Approved');
DECLARE @ot_orphan int = (
    SELECT COUNT(*) FROM raw.overtime_requests o
    WHERE CAST(o.status AS varchar(20)) = 'Approved'
      AND NOT EXISTS (SELECT 1 FROM warehouse.fact_overtime_approved f WHERE f.request_id = CAST(o.request_id AS varchar(20))));
DECLARE @py_src int = (SELECT COUNT(*) FROM raw.payroll_lines);
DECLARE @py_orphan int = (
    SELECT COUNT(*) FROM raw.payroll_lines p
    WHERE NOT EXISTS (SELECT 1 FROM warehouse.fact_payroll_line f WHERE f.line_id = CAST(p.line_id AS varchar(20))));

SELECT 'fact_attendance_daily' AS fact, @att_src AS src_rows, (SELECT COUNT(*) FROM warehouse.fact_attendance_daily) AS loaded,
       @att_orphan AS unresolved_src
UNION ALL SELECT 'fact_leave_day', @lv_src, (SELECT COUNT(*) FROM warehouse.fact_leave_day), @lv_orphan
UNION ALL SELECT 'fact_overtime_approved', @ot_src, (SELECT COUNT(*) FROM warehouse.fact_overtime_approved), @ot_orphan
UNION ALL SELECT 'fact_payroll_line', @py_src, (SELECT COUNT(*) FROM warehouse.fact_payroll_line), @py_orphan;
GO
