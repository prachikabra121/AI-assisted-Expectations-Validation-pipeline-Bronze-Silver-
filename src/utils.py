import pandas as pd

def infer_schema(df: pd.DataFrame, sample_rows=100):
    info = []
    for col in df.columns:
        s = df[col]
        dtype = str(s.dtype)
        null_pct = float(s.isna().mean())
        unique_count = int(s.nunique(dropna=True))
        sample_values = s.dropna().unique()[:10].tolist()
        stats = {}
        if pd.api.types.is_numeric_dtype(s):
            try:
                stats['min'] = float(s.min())
                stats['max'] = float(s.max())
            except Exception:
                stats['min'] = None
                stats['max'] = None
        info.append({
            'column': col,
            'dtype': dtype,
            'null_pct': null_pct,
            'unique_count': unique_count,
            'sample_values': sample_values,
            'stats': stats,
        })
    return info
