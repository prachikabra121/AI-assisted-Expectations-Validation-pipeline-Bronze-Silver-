"""Ingest CSV/XLSX files from folder into Bronze DB."""
import os
import time
import pandas as pd
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from db_utils import ensure_databases, write_df_to_table
from dotenv import load_dotenv

load_dotenv()
WATCH_FOLDER = os.getenv('FILE_WATCH_FOLDER', './data/incoming')
BRONZE_DB = os.getenv('BRONZE_DB', 'Bronze')

class IngestHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if path.lower().endswith(('.csv', '.xlsx')):
            print('Detected file:', path)
            ingest_file(path)

def ingest_file(path):
    df = None
    if path.lower().endswith('.csv'):
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)
    df['__ingested_at'] = pd.Timestamp.now()
    df['__source_file'] = os.path.basename(path)
    table_name = os.path.splitext(os.path.basename(path))[0]
    write_df_to_table(df, BRONZE_DB, table_name, if_exists='append')
    print(f'Ingested {path} into {BRONZE_DB}.{table_name}')

if __name__ == '__main__':
    ensure_databases()
    os.makedirs(WATCH_FOLDER, exist_ok=True)
    observer = Observer()
    handler = IngestHandler()
    observer.schedule(handler, WATCH_FOLDER, recursive=False)
    observer.start()
    print('Watching', WATCH_FOLDER)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
