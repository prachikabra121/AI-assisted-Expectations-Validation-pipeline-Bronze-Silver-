"""Quick test to verify SQL Server connection using SQLAlchemy and your SQLSERVER_CONN from .env"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv()
conn_str = os.getenv('SQLSERVER_CONN')
if not conn_str:
    raise SystemExit('Set SQLSERVER_CONN in .env (see .env.example)')
print('Using connection string:', conn_str)
engine = create_engine(conn_str, fast_executemany=True)
with engine.connect() as conn:
    r = conn.execute(text('SELECT name FROM sys.databases;'))
    dbs = [row[0] for row in r]
print('Databases on server:', dbs)
