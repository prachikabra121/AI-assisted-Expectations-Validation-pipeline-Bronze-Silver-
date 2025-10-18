import pandas as pd
from src.utils import infer_schema

def test_infer_schema():
    df = pd.DataFrame({'a':[1,2,None], 'b':['x','y','x']})
    info = infer_schema(df)
    assert any(col['column']=='a' for col in info)
    assert any(col['column']=='b' for col in info)
