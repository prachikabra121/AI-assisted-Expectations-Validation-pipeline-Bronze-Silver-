# src/validator.py
import os, json
import pandas as pd
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from db_utils import read_table_from_schema, write_df_to_schema, SCHEMA_BRONZE, SCHEMA_VALIDATION, SCHEMA_SILVER, BRONZE_DB

def apply_validations_and_promote(table_name):
    """
    Reads Bronze.<table_name>, loads final_validations from Bronze.validation.final_validations,
    runs validations, writes passing rows to Bronze.silver.<table_name>, writes failing rows
    to Bronze.validation.<table_name>_validation_failures with per-row __failed_expectations JSON.
    """
    try:
        df = read_table_from_schema(SCHEMA_BRONZE, table_name, limit=None)
    except Exception as e:
        print("Failed to read Bronze table:", e)
        return {"table": table_name, "rows_total": 0, "rows_passed": 0, "rows_failed": 0}

    # load final_validations
    engine = create_engine(getattr(__import__('db_utils'), 'get_conn_str')())
    url = engine.url.set(database=BRONZE_DB)
    engine_db = create_engine(url, fast_executemany=True)
    with engine_db.connect() as conn:
        rows = conn.execute(text(f"SELECT column_name, expectation_json FROM {SCHEMA_VALIDATION}.final_validations WHERE table_name = :t"), {"t": table_name}).fetchall()
    validations = []
    for col, j in rows:
        try:
            ej = json.loads(j) if isinstance(j, str) else j
        except Exception:
            ej = j
        validations.append({'column_name': col, 'expectation_json': ej})

    # run validations (ge_integration returns masks as third value)
    from ge_integration import run_ge_validations_on_df
    ge_results, pass_mask, masks = run_ge_validations_on_df(table_name, df, validations)

    passing_df = df[pass_mask].copy()
    failing_df = df[~pass_mask].copy()

    # annotate failing rows with per-row failure reasons & sample data
    if not failing_df.empty:
        # build per-row list of failed expectations
        # masks is list of Series aligned to df
        failed_meta_per_row = []
        n_valids = len(validations)
        # for each expectation i, if row fails (mask False), add reason/expectation info
        # prepare per-expectation metadata in a list to avoid re-parsing
        exp_meta = []
        for i, v in enumerate(validations):
            col = v.get("column_name")
            exp = v.get("expectation_json")
            res = ge_results["results"][i]
            reason = res.get("failure_reason")
            sample_vals = res.get("sample_failed_values", [])
            exp_meta.append({"column": col, "expectation": exp, "reason": reason, "sample_failed_values": sample_vals})

        # for each row in failing_df, collect failed exps
        records = []
        for idx, row in failing_df.iterrows():
            failed_list = []
            for i in range(n_valids):
                m = masks[i]
                # m is True if passes; row fails if m.loc[idx] is False
                try:
                    passed = bool(m.loc[idx])
                except KeyError:
                    passed = False
                if not passed:
                    failed_list.append(exp_meta[i])
            # attach JSON-serializable failed_list
            rec = row.to_dict()
            rec["__failed_expectations"] = json.dumps(failed_list, default=str, ensure_ascii=False)
            records.append(rec)

        # convert records back to DataFrame for writing
        try:
            df_fail_out = pd.DataFrame.from_records(records)
        except Exception:
            # fallback: simple output of failing_df with JSON column built separately
            df_fail_out = failing_df.copy()
            df_fail_out["__failed_expectations"] = [json.dumps([], default=str) for _ in range(len(df_fail_out))]

        # write failing rows into validation schema (table_name_validation_failures)
        write_df_to_schema(df_fail_out, SCHEMA_VALIDATION, f"{table_name}_validation_failures", if_exists="append")

    # write passing rows to silver schema
    if not passing_df.empty:
        write_df_to_schema(passing_df, SCHEMA_SILVER, table_name, if_exists="append")

    # write run log
    log = pd.DataFrame([{
        "table_name": table_name,
        "run_ts": pd.Timestamp.now().isoformat(),
        "rows_total": len(df),
        "rows_passed": len(passing_df),
        "rows_failed": len(failing_df),
        "ge_statistics": json.dumps(ge_results.get("statistics", {}))
    }])
    write_df_to_schema(log, SCHEMA_VALIDATION, "validation_run_log", if_exists="append")

    return {"table": table_name, "rows_total": len(df), "rows_passed": len(passing_df), "rows_failed": len(failing_df)}
