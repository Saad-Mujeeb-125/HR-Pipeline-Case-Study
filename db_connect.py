"""SQL Server connection helper for the IndusWeaveHR pipeline.

How to use it:
  Self-test (proves the DB connection works):
      python pipeline/db_connect.py
  In your own scripts (run them from inside pipeline/):
      from db_connect import get_connection   # raw pyodbc cursor work
      from db_connect import get_engine       # pandas.read_sql / SQLAlchemy

Connection facts:
- Server is the local SQL Server 2025 Express instance: localhost\\SQLEXPRESS.
- Authentication is Windows Authentication (your Windows login) — no password.
- Python talks to SQL Server through pyodbc + "ODBC Driver 18 for SQL Server".
- Encrypt/TrustServerCertificate: Express uses a self-signed certificate;
  encrypting and trusting it on a local machine is the standard safe pattern.

For JDBC tools only (Java-based GUIs like DBeaver — SSMS itself does NOT use JDBC):
  jdbc:sqlserver://localhost\\SQLEXPRESS;databaseName=IndusWeaveHR;
      integratedSecurity=true;encrypt=true;trustServerCertificate=true
"""
import pyodbc
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

SERVER = r"localhost\SQLEXPRESS"   # named instance of SQL Server Express
DEFAULT_DB = "IndusWeaveHR"

PYODBC_CONN_STR = (
    "DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={SERVER};"
    "DATABASE={db};"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


def get_connection(db: str = DEFAULT_DB) -> pyodbc.Connection:
    """Return a pyodbc connection. Use .cursor()/.execute() on it directly."""
    return pyodbc.connect(PYODBC_CONN_STR.format(db=db))


def get_engine(db: str = DEFAULT_DB):
    """Return a SQLAlchemy engine, e.g. for pandas.read_sql(engine=...)."""
    url = URL.create(
        "mssql+pyodbc",
        host=SERVER,
        database=db,
        query={
            "driver": "ODBC Driver 18 for SQL Server",
            "trusted_connection": "yes",
            "encrypt": "yes",
            "TrustServerCertificate": "yes",
        },
    )
    return create_engine(url)


if __name__ == "__main__":
    with get_connection() as cn:  # the "with" block closes the connection for us
        cur = cn.cursor()
        print("server   :", cur.execute("SELECT @@SERVERNAME").fetchval())
        print("database :", cur.execute("SELECT DB_NAME()").fetchval())
        rows = cur.execute(
            "SELECT s.name + '.' + t.name AS tbl FROM sys.tables t "
            "JOIN sys.schemas s ON s.schema_id = t.schema_id ORDER BY tbl"
        ).fetchall()
        print(f"tables   : {len(rows)}")
        for (tbl,) in rows:
            cnt = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchval()
            print(f"  {tbl:<45} {cnt:>10,} rows")
    print("connection OK")
