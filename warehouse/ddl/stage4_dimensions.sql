/* =====================================================================
STAGE 4, part 1 of the case-study PDF (p.6):
  "Design a star schema in a warehouse schema, with primary and foreign
   keys enforced. Dimensions: dim_employee (SCD Type 2 from employment
   history), dim_department, dim_shift, dim_date."
Business rule: rule 2 - "employment_history.csv is the source of truth for
  department, grade and salary over time. The effective_to column is
  unreliable. A record is valid from its effective_from until the day
  before that employee's next record starts. The latest record has no end."

What it builds:
  warehouse.dim_date        every day of 2026 (365): date_key yyyymmdd,
                            is_sunday (DATEFIRST-safe anchor), Monday week_start
  warehouse.dim_shift       the 4 shifts from shifts.json (start/end/grace)
  warehouse.dim_department  the 25 departments incl. previous_name / renamed_on
  warehouse.dim_employee    SCD Type 2: one row per employment-history period
                            (3,686); valid_from/valid_to rebuilt per rule 2;
                            static attributes from employees_final; the one
                            invalid zero-length period (E11259) is kept with a
                            dq_note so the dimension stays complete.

Data findings (25 Oct 2026):
  - effective_to: 1,266 rows carry the 1900-01-01 sentinel, 1,149 of the 2,420
    real values happen to equal next-record-minus-1, 34 contradict it, and
    1,237 sit on the employee's LAST record (rule 2: no end) ->
    effective_to is IGNORED entirely; validity comes from LEAD(effective_from)-1.
  - every employee's earliest history record = hire_date (1,266/1,266 matched).
  - one (emp_id, effective_from) tie: E11259 has Hire and Salary Revision both
    on 2026-07-01; ordering ties with Hire first makes the Hire period
    zero-length (valid_to 2026-06-30 < valid_from) - it never matches a fact
    day, and the Salary Revision row covers the employee from 2026-07-01.

Run:  sqlcmd -S "localhost\SQLEXPRESS" -E -i "pipeline/warehouse/ddl/stage4_dimensions.sql"
Idempotent: warehouse tables are dropped and rebuilt.
===================================================================== */
:ON ERROR EXIT

USE IndusWeaveHR;
GO

IF SCHEMA_ID('warehouse') IS NULL EXEC('CREATE SCHEMA warehouse;');
GO

/* Idempotency (order for RE-runs): the four fact tables hold FKs into these
   dimensions, so a dimensions drop fails while facts exist. Facts are
   rebuilt wholesale by stage4_facts.sql right after this file, so dropping
   them here first is safe and makes "run dimensions then facts" re-runnable
   forever without manual clearing. */
IF OBJECT_ID('warehouse.fact_attendance_daily')  IS NOT NULL DROP TABLE warehouse.fact_attendance_daily;
IF OBJECT_ID('warehouse.fact_leave_day')         IS NOT NULL DROP TABLE warehouse.fact_leave_day;
IF OBJECT_ID('warehouse.fact_overtime_approved') IS NOT NULL DROP TABLE warehouse.fact_overtime_approved;
IF OBJECT_ID('warehouse.fact_payroll_line')      IS NOT NULL DROP TABLE warehouse.fact_payroll_line;
GO

/* ---------------------------------------------------------------- dim_date */
IF OBJECT_ID('warehouse.dim_date') IS NOT NULL DROP TABLE warehouse.dim_date;
CREATE TABLE warehouse.dim_date (
    date_key      int          NOT NULL PRIMARY KEY,   -- yyyymmdd
    full_date     date         NOT NULL,
    year_no       int          NOT NULL,
    quarter_no    int          NOT NULL,
    month_no      int          NOT NULL,
    month_name    varchar(10)  NOT NULL,
    year_month    char(7)      NOT NULL,               -- 'YYYY-MM' (payroll key)
    week_start    date         NOT NULL,               -- the Monday of that week
    day_of_month  int          NOT NULL,
    is_sunday     bit          NOT NULL
);
INSERT INTO warehouse.dim_date
SELECT g.date_key, g.date_key_x AS full_date,
       YEAR(g.date_key_x), DATEPART(quarter, g.date_key_x),
       MONTH(g.date_key_x), DATENAME(month, g.date_key_x),
       FORMAT(g.date_key_x, 'yyyy-MM'),
       DATEADD(day, DATEDIFF(day, '2026-01-05', g.date_key_x) / 7 * 7, '2026-01-05') AS week_start,
       DATEPART(day, g.date_key_x) AS day_of_month,
       CASE WHEN DATEDIFF(day, '2026-01-04', g.date_key_x) % 7 = 0 THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS is_sunday
FROM (
    SELECT CAST(CONVERT(varchar(8),
           DATEADD(day, gs.value, CAST('2026-01-01' AS date)), 112) AS int) AS date_key,
           DATEADD(day, gs.value, CAST('2026-01-01' AS date)) AS date_key_x
    FROM GENERATE_SERIES(0, 364) gs
) g;
GO

/* --------------------------------------------------------------- dim_shift */
IF OBJECT_ID('warehouse.dim_shift') IS NOT NULL DROP TABLE warehouse.dim_shift;
CREATE TABLE warehouse.dim_shift (
    shift_code       varchar(10) NOT NULL PRIMARY KEY,
    shift_name       varchar(30) NOT NULL,
    start_time       time        NOT NULL,
    end_time         time        NOT NULL,
    crosses_midnight bit         NOT NULL,
    grace_minutes    int         NOT NULL,
    applies_to       varchar(60) NULL
);
INSERT INTO warehouse.dim_shift
SELECT x.shift_code, x.shift_name,
       TRY_CAST(x.start_time AS time), TRY_CAST(x.end_time AS time),
       x.crosses_midnight, x.grace_minutes, x.applies_to
FROM raw.shifts js
CROSS APPLY OPENJSON(js.json_data, '$.shifts') WITH (
    shift_code       varchar(10) '$.shift_code',
    shift_name       varchar(30) '$.name',
    start_time       varchar(8)  '$.start_time',
    end_time         varchar(8)  '$.end_time',
    crosses_midnight bit         '$.crosses_midnight',
    grace_minutes    int         '$.grace_minutes',
    applies_to       varchar(60) '$.applies_to'
) x;
GO

/* ---------------------------------------------------------- dim_department */
IF OBJECT_ID('warehouse.dim_department') IS NOT NULL DROP TABLE warehouse.dim_department;
CREATE TABLE warehouse.dim_department (
    dept_id       varchar(10)  NOT NULL PRIMARY KEY,
    dept_name     varchar(100) NOT NULL,
    plant         varchar(60)  NOT NULL,
    cost_center   varchar(20)  NOT NULL,
    previous_name varchar(100) NULL,   -- the 2 renamed departments
    renamed_on    date         NULL
);
INSERT INTO warehouse.dim_department
SELECT CAST(d.dept_id AS varchar(10)),
       CAST(d.dept_name AS varchar(100)),
       CAST(d.plant AS varchar(60)),
       CAST(d.cost_center AS varchar(20)),
       NULLIF(CAST(d.previous_name AS varchar(100)), ''),
       TRY_CAST(d.renamed_on AS date)
FROM raw.departments d;
GO

/* ----------------------------------------------------------- dim_employee
   SCD Type 2 grain: one row per EMPLOYMENT-HISTORY PERIOD. The period key
   (employee_sk) is what the facts reference, so each fact date resolves to
   exactly one department/grade/salary state (rule 2). */
IF OBJECT_ID('warehouse.dim_employee') IS NOT NULL DROP TABLE warehouse.dim_employee;
CREATE TABLE warehouse.dim_employee (
    employee_sk             int IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    emp_id                  varchar(20)  NOT NULL,
    full_name               varchar(100) NOT NULL,
    gender                  varchar(10)  NULL,
    plant                   varchar(60)  NOT NULL,
    employment_type         varchar(20)  NULL,
    hire_date               date         NOT NULL,
    separation_date         date         NULL,
    status                  varchar(10)  NOT NULL,
    annual_leave_entitlement int        NULL,
    valid_from              date         NOT NULL,   -- rule 2: effective_from
    valid_to                date         NULL,       -- day BEFORE next record; NULL = open
    dept_id                 varchar(10)  NOT NULL,
    designation             varchar(50)  NULL,
    grade                   varchar(10)  NULL,
    basic_salary            decimal(10, 2) NOT NULL,
    change_reason           varchar(30)  NOT NULL,
    is_current              bit          NOT NULL,
    dq_note                 varchar(300) NULL
);
CREATE NONCLUSTERED INDEX ix_dim_emp_id ON warehouse.dim_employee (emp_id, valid_from);

/* rule 2 reconstruction: LEAD(effective_from) defines each period's end,
   regardless of what effective_to claims. */

WITH ordered AS (
    SELECT h.emp_id                                AS emp_id,
           TRY_CAST(h.effective_from AS date)      AS valid_from,
           DATEADD(day, -1,
               LEAD(TRY_CAST(h.effective_from AS date)) OVER (
                   PARTITION BY h.emp_id ORDER BY TRY_CAST(h.effective_from AS date),
                   CASE WHEN h.change_reason = 'Hire' THEN 0 ELSE 1 END)) AS valid_to,  -- rule 2
           h.dept_id, h.designation, h.grade, TRY_CAST(h.basic_salary AS decimal(10,2)) AS basic_salary,
           h.change_reason,
           ROW_NUMBER() OVER (PARTITION BY h.emp_id ORDER BY TRY_CAST(h.effective_from AS date),
                              CASE WHEN h.change_reason = 'Hire' THEN 0 ELSE 1 END) AS rn,
           COUNT(*) OVER (PARTITION BY h.emp_id)   AS recs,
           LEAD(TRY_CAST(h.effective_from AS date)) OVER (
                   PARTITION BY h.emp_id ORDER BY TRY_CAST(h.effective_from AS date),
                   CASE WHEN h.change_reason = 'Hire' THEN 0 ELSE 1 END) AS next_from
    FROM staging.employment_history_cleaned h
    WHERE TRY_CAST(h.effective_from AS date) IS NOT NULL
)
SELECT o.emp_id,
       CAST(e.full_name AS varchar(100))                 AS full_name,
       CAST(e.gender AS varchar(10))                     AS gender,
       CAST(e.plant AS varchar(60))                      AS plant,
       CAST(e.employment_type AS varchar(20))            AS employment_type,
       TRY_CAST(e.hire_date AS date)                     AS hire_date,
       TRY_CAST(e.separation_date AS date)               AS separation_date,
       CAST(e.status AS varchar(10))                     AS status,
       TRY_CAST(e.annual_leave_entitlement AS int)       AS annual_leave_entitlement,
       o.valid_from,
       CASE WHEN o.next_from IS NULL THEN NULL ELSE o.valid_to END AS valid_to,  -- latest record: no end (rule 2)
       o.dept_id, o.designation, o.grade, o.basic_salary, o.change_reason,
       CASE WHEN o.next_from IS NULL THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS is_current,
       CASE WHEN o.valid_from > o.valid_to THEN
             'zero-length period (invalid date range in export; superseded by same-day record per rule 2)'
            ELSE NULL END                                AS dq_note
INTO #emp_scd2
FROM ordered o
JOIN staging.employees_final e
  ON CAST(e.emp_id AS varchar(20)) = o.emp_id
WHERE o.rn <= o.recs;   -- keep all periods; zero-length ones simply never match a fact day

INSERT INTO warehouse.dim_employee
SELECT emp_id, full_name, gender, plant, employment_type, hire_date, separation_date, status,
       annual_leave_entitlement, valid_from, valid_to, dept_id, designation, grade, basic_salary,
       change_reason, is_current, dq_note
FROM #emp_scd2
ORDER BY emp_id, valid_from;
DROP TABLE #emp_scd2;
GO

/* ------------------------------------------------------------- verify dims */
SELECT 'dim_date'       AS dim, COUNT(*) AS rows_ FROM warehouse.dim_date
UNION ALL SELECT 'dim_shift', COUNT(*) FROM warehouse.dim_shift
UNION ALL SELECT 'dim_department', COUNT(*) FROM warehouse.dim_department
UNION ALL SELECT 'dim_employee', COUNT(*) FROM warehouse.dim_employee
UNION ALL SELECT 'dim_employee current rows', COUNT(*) FROM warehouse.dim_employee WHERE is_current = 1
UNION ALL SELECT 'dim_employee dq_noted (zero-length)', COUNT(*) FROM warehouse.dim_employee WHERE dq_note IS NOT NULL;
GO
