# src/ai_expectations.py
import os, json
from dotenv import load_dotenv
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
USE_OPENAI = bool(OPENAI_API_KEY)

# basic attempt to import modern OpenAI client if available (best-effort)
client = None
if USE_OPENAI:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        client = None
        USE_OPENAI = False

import pandas as pd
import numpy as np

def infer_schema(df: pd.DataFrame):
    res = []
    for col in df.columns:
        s = df[col]
        dtype = str(s.dtype)
        null_pct = float(s.isna().mean()) if len(s) else 0.0
        unique_count = int(s.nunique(dropna=True))
        try:
            sample_values_raw = s.dropna().unique().tolist()[:20]
            sample_values = []
            for v in sample_values_raw:
                if hasattr(v, "isoformat"):
                    sample_values.append(v.isoformat())
                elif isinstance(v, (np.integer,)):
                    sample_values.append(int(v))
                elif isinstance(v, (np.floating,)):
                    sample_values.append(float(v))
                else:
                    sample_values.append(str(v))
        except Exception:
            sample_values = [str(x) for x in s.head(10).tolist()]

        stats = {}
        if pd.api.types.is_numeric_dtype(s):
            try:
                stats['min'] = float(s.min())
                stats['max'] = float(s.max())
                stats['mean'] = float(s.mean())
            except Exception:
                pass
        col_meta = {
            'column': col,
            'dtype': dtype,
            'null_pct': null_pct,
            'unique_count': unique_count,
            'sample_values': sample_values,
            'stats': stats
        }
        res.append(col_meta)
    return res

def heuristic_expectation_from_meta(meta):
    e = {'dtype': meta['dtype']}
    e['nullable'] = meta['null_pct'] > 0.0
    e['unique'] = False
    if meta['unique_count'] == len(meta.get('sample_values', [])):
        e['unique'] = True
    if meta['unique_count'] <= 20:
        e['allowed_values'] = meta['sample_values'][:20]
    if 'stats' in meta and 'min' in meta['stats']:
        e['min'] = meta['stats']['min']
        e['max'] = meta['stats']['max']
    if meta['column'].lower() in ('email','email_address'):
        e['regex'] = r'^[\w\.-]+@[\w\.-]+\.[A-Za-z]{2,}$'
    e['confidence'] = 'medium'
    return e

def prompt_for_column_expectation_openai(table_name, column_meta):
    prompt = (
        f"You are a data-quality assistant. Given this column metadata for table {table_name}:\n"
        + json.dumps(column_meta, default=str)
        + "\nReturn only a JSON object with keys: dtype, nullable (true/false), unique (true/false), regex (optional), min (optional), max (optional), allowed_values (optional), confidence (low|medium|high)."
    )
    if not USE_OPENAI or client is None:
        return heuristic_expectation_from_meta(column_meta)
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":prompt}],
            max_tokens=300,
            temperature=0.0
        )
        content = None
        if hasattr(resp, "choices") and len(resp.choices) > 0:
            choice = resp.choices[0]
            content = getattr(choice, "message", None)
            if content:
                content = getattr(content, "content", None) or content
        if not content:
            content = getattr(resp, "text", None) or str(resp)
        import re
        m = re.search(r"\{.*\}", str(content), re.S)
        if m:
            return json.loads(m.group(0))
        return heuristic_expectation_from_meta(column_meta)
    except Exception:
        return heuristic_expectation_from_meta(column_meta)

def generate_expectations_for_df_or_heuristic(table_name, df):
    meta = infer_schema(df)
    res = []
    for col_meta in meta:
        if USE_OPENAI:
            suggestion = prompt_for_column_expectation_openai(table_name, col_meta)
        else:
            suggestion = heuristic_expectation_from_meta(col_meta)
        for k, v in list(suggestion.items()):
            if hasattr(v, "isoformat"):
                suggestion[k] = v.isoformat()
        res.append({'table_name': table_name, 'column_name': col_meta['column'], 'suggested_expectation': suggestion})
    return res
