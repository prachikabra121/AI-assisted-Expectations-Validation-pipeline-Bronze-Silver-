# Bronze-to-Silver Great Expectations MVP (SQL Server + Streamlit)

## 📘 Overview

This project implements an **end-to-end data quality pipeline** on **SQL Server**, enabling AI-assisted data validation using **Great Expectations-style rules**, a **Streamlit human approval UI**, and promotion from **Bronze → Silver** layers.

### 🚀 Key Features

- **File Ingestion**: Automatically or manually ingest CSV/Excel files from a local folder into the Bronze layer.
- **AI-Assisted Expectations**: Automatically generate column-level data quality expectations (dtype, nullable, unique, range, allowed\_values).
- **Human-in-the-Loop Approval**: Streamlit UI for reviewing and approving/rejecting expectations before applying them.
- **Validation and Promotion**: Run validations against Bronze data and promote clean rows to Silver, logging failed rows and reasons.
- **Failure Auditing**: Detailed failure reasons stored as JSON (`__failed_expectations`) with sample values.
- **Local SQL Server Integration**: Uses Windows Authentication and creates Bronze DB automatically.



## 🧩 Folder Structure

```
project-root/
├── .env                          # environment variables
├── requirements.txt              # dependencies
├── data/
│   ├── incoming/                 # folder to drop raw CSVs
│   └── samples/                  # optional sample CSVs
├── src/
│   ├── run_etl.py                # main orchestrator
│   ├── ingest_once.py            # one-time file ingestion
│   ├── db_utils.py               # db helpers
│   ├── ai_expectations.py        # AI/heuristic expectation generator
│   ├── ge_integration.py         # expectation validation logic
│   ├── validator.py              # applies validations and promotes data
│   ├── streamlit_app.py          # Streamlit UI for approvals and promotion
│   └── test_conn.py              # test SQL connection utility
└── tools/
    └── relax_validations.py      # fixes overly strict AI rules
```

---

## ⚙️ Environment Setup

### 1️⃣ Prerequisites

- Python 3.10+
- SQL Server (Express or Standard)
- ODBC Driver 17 for SQL Server
- Windows Authentication enabled (default)

### 2️⃣ Create Virtual Environment

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3️⃣ Configure `.env`

```bash
SQLSERVER_CONN=mssql+pyodbc://@PRACHI\\SQLEXPRESS/?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes
BRONZE_DB=Bronze
SCHEMA_BRONZE=bronze
SCHEMA_VALIDATION=validation
SCHEMA_SILVER=silver
FILE_WATCH_FOLDER=./data/incoming
```

---

## 🧮 Running the Pipeline

### Step 1: Ingest Data

Place your CSV files inside `data/incoming` and run:

```bash
python src/run_etl.py
```

✅ Creates Bronze DB and schemas if not present. ✅ Ingests data from CSV → Bronze.bronze. ✅ Generates control expectations automatically.

---

### Step 2: Review Expectations (Streamlit UI)

```bash
streamlit run src/streamlit_app.py
```

- Navigate to [http://localhost:8501](http://localhost:8501)
- View AI-generated expectations
- Approve or reject each rule
- After approval, click **“Promote to Silver”**

If rejected, you can still promote data manually — only validated columns will be applied.

---

### Step 3: Promotion & Validation

- Applies approved validations to Bronze data.
- Writes passing rows → `Bronze.silver.<table>`
- Writes failing rows → `Bronze.validation.<table>_validation_failures`
- Logs run summary → `Bronze.validation.validation_run_log`

---

## 📊 Database Layout

| Schema         | Purpose             | Example Table                                                                                   |
| -------------- | ------------------- | ----------------------------------------------------------------------------------------------- |
| **bronze**     | Raw ingested data   | `bronze.orders`                                                                                 |
| **validation** | Control & logs      | `control_expectations`, `final_validations`, `orders_validation_failures`, `validation_run_log` |
| **silver**     | Clean promoted data | `silver.orders`                                                                                 |

---

## 🧠 AI Expectation Generator (Heuristics)

If OpenAI API key not provided, generator falls back to local rules:

- `unique` only if all rows unique and sample small
- `allowed_values` if unique values ≤ 20
- Skips `__` metadata columns (no unique/allowed\_values)

Each expectation JSON looks like:

```json
{
  "dtype": "int64",
  "nullable": false,
  "unique": false,
  "min": 1001,
  "max": 1010,
  "confidence": "medium"
}
```

---

## 🔍 Validation Output Example

**Bronze.validation.orders\_validation\_failures**

| order\_id | status  | \_\_failed\_expectations                               |
| --------- | ------- | ------------------------------------------------------ |
| 1005      | Shipped | `[ {"column":"status","reason":"value_not_allowed"} ]` |

---

## 🛠 Troubleshooting

| Issue                          | Cause                         | Fix                                                      |
| ------------------------------ | ----------------------------- | -------------------------------------------------------- |
| Tables created in `master` DB  | Engine not bound to Bronze DB | Ensure `engine = create_engine(..., database=BRONZE_DB)` |
| `experimental_rerun` error     | Streamlit version mismatch    | Replace with `st.rerun()`                                |
| Duplicates flagged incorrectly | Over-strict expectations      | Run `python tools/relax_validations.py`                  |

---

## 🧾 License

This project is provided under the MIT License.

---

## 👩‍💻 Author

**Prachi Kabra**\
LinkedIn: [https://www.linkedin.com/in/prachi-kabra-77622a16b/](https://www.linkedin.com/in/prachi-kabra-77622a16b/)

---

## 🏁 Future Enhancements

- Add versioning for approved validations
- Integrate DBT or Airflow orchestration
- Extend to AWS S3/Snowflake pipeline
- Add email notifications for failed validations

