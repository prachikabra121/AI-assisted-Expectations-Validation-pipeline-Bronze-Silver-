# src/streamlit_app.py
import streamlit as st
import pandas as pd
import json
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from db_utils import _create_engine, SCHEMA_VALIDATION, SCHEMA_BRONZE, SCHEMA_SILVER, BRONZE_DB, read_table_from_schema, write_df_to_schema
from validator import apply_validations_and_promote
import time

# create engine bound to Bronze DB
engine = _create_engine()
url = engine.url.set(database=BRONZE_DB)
engine_db = create_engine(url, fast_executemany=True)

st.set_page_config(page_title="Expectations Review & Promote", layout="wide")
st.title("AI-generated Expectations — Review, Approve, Promote")

# -------------------------
# Data loading helpers
# -------------------------
@st.cache_data(ttl=10)
def load_control_expectations():
    try:
        return pd.read_sql(text(f"SELECT * FROM {SCHEMA_VALIDATION}.control_expectations ORDER BY table_name, column_name, generated_at"), engine_db)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=10)
def load_final_validations():
    try:
        return pd.read_sql(text(f"SELECT * FROM {SCHEMA_VALIDATION}.final_validations ORDER BY table_name, column_name, approved_at"), engine_db)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=10)
def list_bronze_tables():
    try:
        q = text(f"SELECT TABLE_NAME FROM [{BRONZE_DB}].INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = :s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME")
        rows = engine_db.execute(q, {"s": SCHEMA_BRONZE}).fetchall()
        return sorted({r[0] for r in rows})
    except Exception:
        return []

def save_final_validations(rows):
    df = pd.DataFrame(rows)
    if df.empty:
        return 0
    df.to_sql("final_validations", engine_db, schema=SCHEMA_VALIDATION, if_exists="append", index=False)
    load_final_validations.clear()
    load_control_expectations.clear()
    list_bronze_tables.clear()
    return len(df)

# -------------------------
# UI layout
# -------------------------
col_layout = st.columns([2, 1])
left_col, right_col = col_layout

with left_col:
    st.header("Control suggestions (AI generated)")
    control_df = load_control_expectations()
    if control_df.empty:
        st.info("No control expectations found. Run ingestion pipeline first.")
    else:
        tables = sorted(control_df["table_name"].unique())
        chosen_table = st.selectbox("Choose table to review suggestions for", options=tables)
        df_table = control_df[control_df["table_name"] == chosen_table].reset_index(drop=True)
        st.markdown(f"### Suggestions for table **{chosen_table}**")
        approvals = []
        for i, row in df_table.iterrows():
            st.subheader(f"Column: {row['column_name']}")
            # show json suggestion
            try:
                suggestion_obj = json.loads(row["suggested_expectation_json"]) if isinstance(row["suggested_expectation_json"], str) else row["suggested_expectation_json"]
                st.json(suggestion_obj)
            except Exception:
                st.write(row["suggested_expectation_json"])
            cols = st.columns([1, 4, 1])
            approve = cols[0].checkbox("Approve", key=f"apr_{row['table_name']}_{row['column_name']}_{i}")
            reject = cols[2].checkbox("Reject", key=f"rej_{row['table_name']}_{row['column_name']}_{i}")
            note = st.text_input("Note (optional)", key=f"note_{row['table_name']}_{row['column_name']}_{i}")
            approvals.append({
                "table": row['table_name'],
                "column": row['column_name'],
                "approve": approve,
                "reject": reject,
                "note": note,
                "suggestion": row["suggested_expectation_json"]
            })

        if st.button("Save approvals"):
            to_save = []
            for a in approvals:
                if a["approve"] and not a["reject"]:
                    to_save.append({
                        "table_name": a["table"],
                        "column_name": a["column"],
                        "expectation_json": a["suggestion"],
                        "approved_by": "streamlit_user",
                        "approved_at": pd.Timestamp.now().isoformat(),
                        "active": True,
                        "version": 1,
                        "note": a["note"]
                    })
            if to_save:
                n = save_final_validations(to_save)
                st.success(f"Saved {n} approvals to final_validations.")
            else:
                st.info("No approvals selected.")

with right_col:
    st.header("Final validations (approved)")
    final_df = load_final_validations()
    if final_df.empty:
        st.info("No final validations saved yet.")
    else:
        st.dataframe(final_df)

st.markdown("---")
st.header("Promote (move data from Bronze → Silver)")

# List tables for promotion: union of bronze tables and control/final suggestions
bronze_tables = list_bronze_tables()
suggested_tables = sorted(set(control_df["table_name"].tolist() if not control_df.empty else []))
available_tables = sorted(set(bronze_tables) | set(suggested_tables))
if not available_tables:
    st.info("No tables found in Bronze to promote. Run ingestion first.")
else:
    sel = st.multiselect("Choose table(s) to promote", options=available_tables, key="promote_tables")
    if sel:
        promote_results = []
        for t in sel:
            st.markdown(f"### Table: `{t}`")
            # check if there are approved validations for t
            approved_for_t = final_df[final_df["table_name"] == t] if not final_df.empty else pd.DataFrame()
            if not approved_for_t.empty:
                st.write(f"Approved validations: {len(approved_for_t)}")
                if st.button(f"Promote `{t}` with approved validations", key=f"promote_validate_{t}"):
                    with st.spinner(f"Running validations for {t}..."):
                        try:
                            summary = apply_validations_and_promote(t)
                            st.success(f"Promotion finished for {t}: {summary}")
                        except Exception as e:
                            st.error(f"Promotion failed for {t}: {e}")
            else:
                # No approved validations - allow user to promote without validations but require explicit confirmation
                st.warning("No approved validations found for this table.")
                st.write("You can still promote all rows to Silver **without** applying validations. This will move the data as-is.")
                confirm_key = f"confirm_promote_no_validations_{t}"
                confirm = st.checkbox("I understand — promote all rows to Silver without validations", key=confirm_key)
                if confirm:
                    if st.button(f"Promote `{t}` to Silver without validations", key=f"promote_no_validate_{t}"):
                        with st.spinner(f"Promoting {t} (no validations)..."):
                            try:
                                # read from Bronze (attempt to read using read_table_from_schema)
                                try:
                                    df = read_table_from_schema(SCHEMA_BRONZE, t, limit=None)
                                except Exception as e:
                                    st.error(f"Failed to read Bronze.{t}: {e}")
                                    df = None
                                if df is None or df.empty:
                                    st.warning(f"No data found in Bronze.{t} to promote.")
                                else:
                                    # write directly to Silver schema
                                    written_schema = write_df_to_schema(df, SCHEMA_SILVER, t, if_exists="append")
                                    st.success(f"Promoted {len(df)} rows from Bronze.{t} into Bronze.{written_schema}.{t}")
                            except Exception as e:
                                st.error(f"Promotion failed for {t}: {e}")

st.markdown("---")
st.header("View existing metadata / debug")

st.subheader("Control expectations (Bronze.validation.control_expectations)")
try:
    st.dataframe(control_df)
except Exception:
    st.write("Unable to load control expectations.")

st.subheader("Final validations (Bronze.validation.final_validations)")
try:
    st.dataframe(final_df)
except Exception:
    st.write("Unable to load final validations.")

st.markdown("**Tips**")
st.write("- You can approve suggestions in the left panel, then use 'Promote with approved validations'.")
st.write("- If you promote without validations, all rows will be moved as-is into `Bronze.silver.<table>`.")
st.write("- If you want the UI to refresh after saving approvals, click Refresh in your browser or the top-left Streamlit menu.")
