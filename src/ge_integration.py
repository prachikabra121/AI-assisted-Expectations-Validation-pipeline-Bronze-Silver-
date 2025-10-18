# src/ge_integration.py
from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np
import json

def _to_serializable(v):
    # convert common pandas/numpy types to python primitives
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode(errors="ignore")
    return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)

def _apply_single_expectation(df: pd.DataFrame, col: str, exp: Dict[str, Any]) -> pd.Series:
    """Return boolean mask where expectation PASSES (True = row passes)."""
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    series = df[col]
    mask = pd.Series([True] * len(df), index=df.index)

    # nullable: False means fail if NA
    if exp.get("nullable") is False:
        mask &= series.notna()

    # unique: True means duplicates are failing
    if exp.get("unique"):
        dup_mask = ~series.duplicated(keep=False)
        dup_mask = dup_mask & series.notna()
        mask &= dup_mask

    # regex match
    if exp.get("regex"):
        try:
            pattern = exp.get("regex")
            m = series.astype(str).str.match(pattern).fillna(False)
        except Exception:
            m = pd.Series([False]*len(series), index=series.index)
        mask &= m

    # numeric min/max
    if "min" in exp:
        m = pd.to_numeric(series, errors="coerce") >= float(exp.get("min"))
        mask &= m.fillna(False)

    if "max" in exp:
        m = pd.to_numeric(series, errors="coerce") <= float(exp.get("max"))
        mask &= m.fillna(False)

    # allowed values
    if exp.get("allowed_values"):
        allowed = set(exp.get("allowed_values"))
        try:
            m = series.isin(allowed)
        except Exception:
            m = series.astype(str).isin({str(x) for x in allowed})
        mask &= m

    return mask

def _reason_and_samples_for_expectation(df: pd.DataFrame, col: str, exp: Dict[str, Any], mask: pd.Series) -> Dict[str, Any]:
    """
    Given the mask (True = passes), return a dict with failure_reason (str)
    and sample_failed_values (list) for rows that failed this expectation.
    """
    reasons = []
    series = df[col] if col in df.columns else pd.Series([None]*len(df))
    failed_idx = (~mask)
    if failed_idx.sum() == 0:
        return {"failure_reason": None, "sample_failed_values": []}

    # check nullable
    if exp.get("nullable") is False:
        if series.isna().any():
            # presence of any nulls among failing rows
            if series[series.isna()].index.intersection(df[failed_idx].index).any():
                reasons.append("contains_nulls")

    # unique check
    if exp.get("unique"):
        # if there are duplicates among the column
        dup_idx = series[series.duplicated(keep=False)]
        if dup_idx.any():
            if dup_idx.index.intersection(df[failed_idx].index).any():
                reasons.append("duplicates")

    # regex
    if exp.get("regex"):
        try:
            patt = exp.get("regex")
            match_mask = series.astype(str).str.match(patt).fillna(False)
            # failing rows due to regex will be where match_mask is False
            if (~match_mask & failed_idx).any():
                reasons.append("regex_mismatch")
        except Exception:
            reasons.append("regex_error")

    # min/max
    if "min" in exp or "max" in exp:
        num = pd.to_numeric(series, errors="coerce")
        out_of_range = pd.Series([False]*len(df), index=df.index)
        if "min" in exp:
            out_of_range |= num < float(exp.get("min"))
        if "max" in exp:
            out_of_range |= num > float(exp.get("max"))
        if (out_of_range & failed_idx).any():
            reasons.append("out_of_range")

    # allowed_values
    if exp.get("allowed_values"):
        allowed = set(exp.get("allowed_values"))
        try:
            not_allowed = ~series.isin(allowed)
        except Exception:
            not_allowed = ~series.astype(str).isin({str(x) for x in allowed})
        if (not_allowed & failed_idx).any():
            reasons.append("value_not_allowed")

    # type mismatch heuristic: numeric exp but many non-numeric values
    if ('min' in exp or 'max' in exp) and series.dtype == object:
        # if conversion yields many NaNs among failed rows, mark type_mismatch
        conv = pd.to_numeric(series, errors="coerce")
        if conv[failed_idx].isna().all():
            reasons.append("type_mismatch")

    if not reasons:
        # fallback reason
        reasons.append("unspecified_failure")

    # sample some failing values
    sample_values = []
    try:
        vals = series[failed_idx].head(5).tolist()
        sample_values = [_to_serializable(v) for v in vals]
    except Exception:
        sample_values = []

    return {"failure_reason": ";".join(reasons), "sample_failed_values": sample_values}

def run_ge_validations_on_df(table_name: str, df: pd.DataFrame, validations: List[Dict[str, Any]]):
    """
    Runs simple GE-like validations on df.

    Returns:
      - results: dict containing 'statistics' and 'results' (each result includes failure_reason & sample_failed_values)
      - overall_mask: boolean Series (True means row passed ALL expectations)
      - masks: list of boolean Series for each expectation (True = row passes that expectation)
    """
    if df is None:
        df = pd.DataFrame()
    n = len(df)
    overall_mask = pd.Series([True]*n, index=df.index) if n>0 else pd.Series(dtype=bool)
    results = []
    masks = []
    evaluated = 0; success = 0

    for v in validations:
        col = v.get("column_name")
        exp = v.get("expectation_json") or v.get("expectation") or {}
        evaluated += 1
        mask = _apply_single_expectation(df, col, exp)
        masks.append(mask)
        rows_satisfied = int(mask.sum()) if n>0 else 0
        rows_failed = int(n - rows_satisfied) if n>0 else 0
        ok = (rows_failed == 0) if n>0 else True
        if ok:
            success += 1

        # compute failure reason & sample values for this expectation
        meta = _reason_and_samples_for_expectation(df, col, exp, mask)

        results.append({
            "expectation_config": {"column": col, "expectation": exp},
            "result": {"success": ok, "evaluated_rows": n, "rows_satisfied": rows_satisfied, "rows_failed": rows_failed},
            "failure_reason": meta["failure_reason"],
            "sample_failed_values": meta["sample_failed_values"]
        })

        if n>0:
            overall_mask &= mask

    stats = {"evaluated_expectations": evaluated, "successful_expectations": success, "unsuccessful_expectations": evaluated - success}
    return {"statistics": stats, "results": results}, overall_mask, masks
