# src/run_etl.py
import os
import json
import subprocess
from dotenv import load_dotenv
load_dotenv()

from db_utils import ensure_database_and_schemas, read_table_from_schema, write_df_to_schema, SCHEMA_VALIDATION, SCHEMA_BRONZE, BRONZE_DB
from ingest_once import ingest_all_files
from ai_expectations import generate_expectations_for_df_or_heuristic
import pandas as pd
import time

def _safe_json(obj):
    import json, datetime
    def _conv(o):
        if hasattr(o,"isoformat"):
            return o.isoformat()
        try:
            import numpy as np
            if isinstance(o, np.generic):
                return o.item()
        except Exception:
            pass
        return str(o)
    return json.dumps(obj, default=_conv, ensure_ascii=False)

def write_control_expectations(suggestions):
    rows=[]
    for s in suggestions:
        rows.append({
            "table_name": s["table_name"],
            "column_name": s["column_name"],
            "suggested_expectation_json": _safe_json(s["suggested_expectation"]),
            "generated_at": pd.Timestamp.now().isoformat()
        })
    if rows:
        write_df_to_schema(pd.DataFrame(rows), SCHEMA_VALIDATION, "control_expectations", if_exists="append")

def main(launch_ui=True):
    print("Ensuring Bronze DB and schemas exist...")
    ensure_database_and_schemas()

    print("Ingesting files into Bronze.bronze schema...")
    ingested = ingest_all_files()
    if not ingested:
        print("No ingested tables. Exiting.")
        return

    all_suggestions=[]
    for t in ingested:
        print("Sampling", t)
        df_sample = read_table_from_schema(SCHEMA_BRONZE, t, limit=1000)
        suggestions = generate_expectations_for_df_or_heuristic(t, df_sample)
        all_suggestions.extend(suggestions)

    print("Writing control expectations to Bronze.validation.control_expectations")
    write_control_expectations(all_suggestions)

    if launch_ui:
        print("Launching Streamlit UI for review & promotion...")
        # Try to launch streamlit in a separate process (user must have streamlit installed)
        try:
            # Use Popen so this process doesn't block: user interacts with Streamlit in new window/tab.
            subprocess.Popen(["streamlit", "run", "src/streamlit_app.py"], shell=False)
            print("Streamlit launched (open http://localhost:8501).")
        except Exception as e:
            print("Failed to launch Streamlit automatically:", e)
            print("You can start it manually with: streamlit run src/streamlit_app.py")
        # keep the orchestrator alive briefly to make console output readable
        time.sleep(1)
    else:
        print("UI launch disabled. Run `streamlit run src/streamlit_app.py` to review and approve expectations.")

if __name__ == "__main__":
    # by default we auto-launch the UI after generation
    main(launch_ui=True)
