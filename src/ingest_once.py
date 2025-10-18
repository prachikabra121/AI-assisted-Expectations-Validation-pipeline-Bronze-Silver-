# src/ingest_once.py
import os
import glob
import pandas as pd
from dotenv import load_dotenv
load_dotenv()
from db_utils import write_df_to_schema, SCHEMA_BRONZE, BRONZE_DB

INBOX = os.getenv("FILE_WATCH_FOLDER", "./data/incoming")

def ingest_all_files():
    os.makedirs(INBOX, exist_ok=True)
    files = glob.glob(os.path.join(INBOX, "*.csv")) + glob.glob(os.path.join(INBOX, "*.xlsx"))
    ingested = []
    if not files:
        print("No files in", INBOX)
        return ingested
    for f in files:
        print("Processing file:", f)
        try:
            if f.lower().endswith(".csv"):
                df = pd.read_csv(f)
            else:
                df = pd.read_excel(f)
        except Exception as e:
            print("Read failed:", e)
            continue
        df["__ingested_at"] = pd.Timestamp.now()
        df["__source_file"] = os.path.basename(f)
        table_name = os.path.splitext(os.path.basename(f))[0]
        try:
            used_schema = write_df_to_schema(df, SCHEMA_BRONZE, table_name, if_exists="replace")
            print(f"Wrote {len(df)} rows to {BRONZE_DB}.{used_schema}.{table_name}")
            ingested.append(table_name)
        except Exception as e:
            print("Write failed:", e)
    return ingested

if __name__ == "__main__":
    print("Ingest run. Ingested:", ingest_all_files())
