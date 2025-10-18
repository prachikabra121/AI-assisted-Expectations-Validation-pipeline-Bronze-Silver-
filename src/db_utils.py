# src/db_utils.py
import os
import urllib.parse
from dotenv import load_dotenv
load_dotenv()
import pandas as pd
from sqlalchemy import create_engine, text

# Configuration: DB and schemas (all inside a single DB)
BRONZE_DB = os.getenv("BRONZE_DB", "Bronze")
SCHEMA_BRONZE = os.getenv("SCHEMA_BRONZE", "bronze")
SCHEMA_VALIDATION = os.getenv("SCHEMA_VALIDATION", "validation")
SCHEMA_SILVER = os.getenv("SCHEMA_SILVER", "silver")

def _build_odbc_connect(driver="ODBC Driver 17 for SQL Server", server="PRACHI\\SQLEXPRESS"):
    odbc = f"DRIVER={{{driver}}};SERVER={server};Trusted_Connection=yes;"
    return "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc)

def get_conn_str():
    conn = os.getenv("SQLSERVER_CONN")
    if conn and conn.strip():
        return conn.strip()
    server = os.getenv("SQLSERVER_HOST") or os.getenv("SQLSERVER_INSTANCE") or "PRACHI\\SQLEXPRESS"
    driver = os.getenv("ODBC_DRIVER") or "ODBC Driver 17 for SQL Server"
    return _build_odbc_connect(driver=driver, server=server)

def _create_engine():
    return create_engine(get_conn_str(), fast_executemany=True)

def ensure_database_and_schemas():
    """Ensure the Bronze database exists and the three schemas exist inside it."""
    engine = _create_engine()
    # create database if missing
    with engine.connect() as conn:
        conn.execute(text(f"IF DB_ID('{BRONZE_DB}') IS NULL CREATE DATABASE [{BRONZE_DB}];"))
        conn.commit()

    # whitelist and validate schema names
    schemas = (SCHEMA_BRONZE, SCHEMA_VALIDATION, SCHEMA_SILVER)
    allowed = set(("bronze", "validation", "silver"))
    for s in schemas:
        if s.lower() not in allowed:
            raise ValueError(f"Refusing to create unsafe schema name: {s!r}")

    # create schemas inside Bronze DB using safe literal SQL
    engine_db = create_engine(_create_engine().url.set(database=BRONZE_DB), fast_executemany=True)
    with engine_db.connect() as conn:
        for schema in schemas:
            sql = f"""
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'{schema}')
BEGIN
    EXEC('CREATE SCHEMA [{schema}]');
END
"""
            conn.execute(text(sql))
        conn.commit()

def _engine_for_bronze():
    engine_base = _create_engine()
    url = engine_base.url.set(database=BRONZE_DB)
    return create_engine(url, fast_executemany=True)

# --- robust write/read helpers ---

def write_df_to_schema(df: pd.DataFrame, schema: str, table_name: str, if_exists='append'):
    """
    Force-write df into [BRONZE_DB].[schema].[table_name] using an engine explicitly
    bound to BRONZE_DB. If a table with the same name exists elsewhere and is found,
    read from source and write into Bronze using the Bronze-bound engine.

    Returns the schema where the final table resides.
    """
    # 1) engine bound to Bronze DB (explicit)
    engine_base = _create_engine()
    engine_bronze = create_engine(engine_base.url.set(database=BRONZE_DB), fast_executemany=True)

    # 2) ensure schema exists in Bronze (on Bronze-bound connection)
    try:
        with engine_bronze.connect() as conn:
            conn.execute(text(f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'{schema}') EXEC('CREATE SCHEMA [{schema}]')"))
            conn.commit()
    except Exception as e:
        # permission issue may show up here
        raise RuntimeError(f"Failed to ensure schema [{schema}] exists in database [{BRONZE_DB}]: {e}")

    # 3) Try writing using the Bronze-bound engine (this should place table in Bronze)
    try:
        df.to_sql(table_name, engine_bronze, schema=schema, if_exists=if_exists, index=False, chunksize=1000, method='multi')
    except Exception as write_exc:
        # If writing fails, provide a helpful error
        raise RuntimeError(f"Failed to write DataFrame into {BRONZE_DB}.{schema}.{table_name} using Bronze-bound engine: {write_exc}")

    # 4) Verify the table exists using the Bronze-bound engine and two-part name [schema].[table]
    try:
        with engine_bronze.connect() as conn:
            cnt = conn.execute(text(f"SELECT COUNT(*) FROM [{schema}].[{table_name}]")).scalar()
    except Exception as verify_exc:
        # If verify fails, try to list schemas/tables to give debug info
        try:
            with engine_bronze.connect() as conn:
                rows = conn.execute(text("SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = :t"), {"t": table_name}).fetchall()
                found = [(r[0], r[1]) for r in rows]
        except Exception:
            found = None
        raise RuntimeError(f"Write appears to have succeeded but verification query failed on Bronze-bound engine. "
                           f"Verify error: {verify_exc}. Tables found in Bronze for name '{table_name}': {found}")

    # If verification succeeded, return the schema name
    if cnt is not None:
        print(f"Verified: wrote {BRONZE_DB}.{schema}.{table_name} ({int(cnt)} rows).")
        return schema

    # unreachable fallback
    raise RuntimeError(f"Unknown error: wrote table but verification returned no count for {BRONZE_DB}.{schema}.{table_name}.")

def read_table_from_schema(schema: str, table_name: str, limit: int = None):
    """
    Read table from BronzeDB.schema.table_name. If not found, search all DBs for the table name
    and read from the first match (prints note).
    """
    engine_db = _engine_for_bronze()
    q = f"SELECT * FROM [{BRONZE_DB}].{schema}.[{table_name}]" if not limit else f"SELECT TOP ({limit}) * FROM [{BRONZE_DB}].{schema}.[{table_name}]"
    try:
        return pd.read_sql(q, engine_db)
    except Exception as exc:
        engine_base = _create_engine()
        found = []
        with engine_base.connect() as conn:
            dbs = conn.execute(text("SELECT name FROM sys.databases WHERE state = 0")).fetchall()
            for (dbname,) in dbs:
                try:
                    rows = conn.execute(text(f"SELECT TABLE_SCHEMA FROM [{dbname}].INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = :t"), {"t": table_name}).fetchall()
                    for r in rows:
                        found.append((dbname, r[0]))
                except Exception:
                    pass

        if not found:
            raise RuntimeError(f"Could not find table {table_name} in {BRONZE_DB}.{schema} and no other DB/schema contains it. Original error: {exc}") from exc

        src_db, src_schema = found[0]
        print(f"Note: requested {BRONZE_DB}.{schema}.{table_name} but reading from actual location {src_db}.{src_schema}.{table_name}")
        src_engine = create_engine(engine_base.url.set(database=src_db))
        q2 = f"SELECT * FROM [{src_db}].{src_schema}.[{table_name}]" if not limit else f"SELECT TOP ({limit}) * FROM [{src_db}].{src_schema}.[{table_name}]"
        return pd.read_sql(q2, src_engine)
