# Monitoring Sales pipeline. Destination: pipamas-v2.data.
# Input files are passed as arguments (never hardcoded here).
# BigQuery auth: explicit service account key. The key path is configured in
# ONE place — env var BQ_KEY_FILE (default: pipamas-v2-f9e3e0625182.json,
# looked up in the working directory, then next to the app root).

# ============================================================
# IMPORT LIBRARY
# ============================================================
import argparse
import re
import os
import tempfile
import polars as pl

from google.cloud import bigquery
from google.oauth2 import service_account


def _load_bq_credentials():
    # this pipeline uploads to pipamas-v2, so it authenticates with the v2 key
    key_file = os.environ.get("BQ_KEY_FILE", "pipamas-v2-f9e3e0625182.json")
    candidates = [key_file, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", key_file)]
    for candidate in candidates:
        if os.path.exists(candidate):
            return service_account.Credentials.from_service_account_file(candidate)
    raise FileNotFoundError(
        f"Service account key '{key_file}' tidak ditemukan. "
        "Upload file key JSON ke folder kerja atau set env BQ_KEY_FILE ke path-nya."
    )


BQ_CREDENTIALS = _load_bq_credentials()


# ============================================================
# DISPLAY SETTING
# ============================================================
pl.Config.set_tbl_cols(100)
pl.Config.set_tbl_width_chars(300)


# ============================================================
# CONFIG BIGQUERY
# ============================================================

BQ_DESTINATIONS = [
    {
        "project_id": os.environ.get("BQ_PROJECT_ID", "pipamas-v2"),
        "dataset_id": os.environ.get("BQ_DATASET_ID", "data"),
    },
]

TABLE_SALES_MONITORING = "sales_monitoring"
TABLE_SALES_CUSTOMER_MONITORING = "sales_customer_monitoring"


# ============================================================
# FILE INPUT
# ============================================================
_parser = argparse.ArgumentParser(description="Monitoring Sales")
_parser.add_argument("--so", required=True, help="SO Summary .xlsx")
_parser.add_argument("--invoice", required=True, help="Invoice Summary .xlsx")
_ARGS = _parser.parse_args()

SO_FILE = _ARGS.so
SI_FILE = _ARGS.invoice


# ============================================================
# BUSINESS CONFIG
# ============================================================

# Closed / Cancel / Declined langsung dibuang dari SO monitoring.
EXCLUDE_CLOSED_CANCELLED_DECLINED_SO = True


# ============================================================
# FUNCTION UPLOAD POLARS TO BIGQUERY
# ============================================================
def upload_polars_to_bigquery(df: pl.DataFrame, table_name: str, write_disposition="WRITE_TRUNCATE"):
    temp_parquet_path = os.path.join(tempfile.gettempdir(), f"_temp_{table_name}.parquet")

    df.write_parquet(temp_parquet_path)

    for dest in BQ_DESTINATIONS:
        project_id = dest["project_id"]
        dataset_id = dest["dataset_id"]

        table_full_id = f"{project_id}.{dataset_id}.{table_name}"

        client = bigquery.Client(project=project_id, credentials=BQ_CREDENTIALS)

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=write_disposition,
        )

        with open(temp_parquet_path, "rb") as file_obj:
            job = client.load_table_from_file(
                file_obj,
                table_full_id,
                job_config=job_config
            )

        job.result()

        print(f"Uploaded to BigQuery: {table_full_id}")
        print(f"Total rows uploaded: {df.height:,}")

    if os.path.exists(temp_parquet_path):
        os.remove(temp_parquet_path)


# ============================================================
# FUNCTION SALES LOGIC
# ============================================================
def sales_code_suffix(salesman):
    s = str(salesman or "").strip().upper()
    match = re.search(r"(\d+)$", s)

    if match:
        return int(match.group(1))

    return None


def assign_branch_from_salesman(salesman) -> str:
    s = str(salesman or "").strip().upper()
    suffix = sales_code_suffix(s)

    if s == "PISLP37":
        return "Dist Sumatera"

    if s == "PISLP38":
        return "Dist Kalimantan"

    if suffix is not None:
        if 30 <= suffix <= 39:
            return "Project"
        if 50 <= suffix <= 59:
            return "Agen"

    if s in ["ELCOS01", "PICOS01", "PICOS21", "PPCOS01"]:
        return "Bandung"

    if s in ["ELCOS06", "PICOS06", "PPCOS06", "SPV06"]:
        return "Cirebon"

    if s in ["ELCOS08", "ICCOS08", "PPCOS08", "ICSPV08", "PPSPV08"]:
        return "Bogor"

    if s in ["ICCOS07", "PPCOS07", "ELCOS07", "PICOS07"]:
        return "PCK"

    if suffix is None:
        return "Project"

    if suffix < 20:
        return "Bandung"

    if suffix < 30:
        return "PCK"

    if 40 <= suffix <= 49:
        return "Project"

    if 60 <= suffix < 70:
        return "Cirebon"

    if 70 <= suffix < 80:
        return "PCK"

    if 80 <= suffix < 90:
        return "Bogor"

    return "Project"


def join_list(values):
    if values is None:
        return ""

    clean_values = []

    for v in values:
        if v is None:
            continue

        v = str(v).strip()

        if v == "" or v.upper() in ["NONE", "NAN", "NULL"]:
            continue

        clean_values.append(v)

    clean_values = sorted(set(clean_values))

    return ", ".join(clean_values)


def combine_csv_values(values):
    if values is None:
        return ""

    all_codes = []

    for value in values:
        if value is None:
            continue

        value = str(value).strip()

        if value == "" or value.upper() in ["NONE", "NAN", "NULL"]:
            continue

        parts = [x.strip() for x in value.split(",") if x.strip() != ""]

        for part in parts:
            if part.upper() not in ["NONE", "NAN", "NULL"]:
                all_codes.append(part)

    unique_codes = sorted(set(all_codes))

    return ", ".join(unique_codes)


def require_columns(df: pl.DataFrame, required_columns: list, df_name: str):
    missing_cols = [col for col in required_columns if col not in df.columns]

    if missing_cols:
        raise ValueError(
            f"Kolom berikut tidak ditemukan di {df_name}: {missing_cols}\n"
            f"Kolom tersedia: {df.columns}"
        )


# ============================================================
# FUNCTION POLARS EXPRESSION
# ============================================================
def clean_text_expr(col_name: str, default_value="Unknown"):
    raw = (
        pl.col(col_name)
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
    )

    upper = raw.str.to_uppercase()

    return (
        pl.when(
            raw.is_null()
            | upper.is_in(["", "NONE", "NAN", "NULL"])
        )
        .then(pl.lit(default_value))
        .otherwise(raw)
        .alias(col_name)
    )


def clean_code_expr(col_name: str):
    raw = (
        pl.col(col_name)
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
    )

    upper = raw.str.to_uppercase()

    return (
        pl.when(
            raw.is_null()
            | upper.is_in(["", "NONE", "NAN", "NULL"])
        )
        .then(pl.lit(""))
        .otherwise(raw)
        .alias(col_name)
    )


def normalize_division_expr(col_name: str):
    raw = (
        pl.col(col_name)
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .str.to_uppercase()
    )

    return (
        pl.when(
            raw.is_null()
            | raw.is_in(["", "NONE", "NAN", "NULL"])
        )
        .then(pl.lit("Unknown"))
        .otherwise(raw)
        .alias(col_name)
    )


def numeric_expr(col_name: str):
    raw_text = (
        pl.col(col_name)
        .cast(pl.Utf8, strict=False)
        .str.replace_all(",", "")
        .str.strip_chars()
    )

    return (
        pl.coalesce([
            pl.col(col_name).cast(pl.Float64, strict=False),
            raw_text.cast(pl.Float64, strict=False),
        ])
        .fill_null(0)
        .alias(col_name)
    )


def normalize_date_expr(col_name: str):
    raw_text = (
        pl.col(col_name)
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
    )

    return (
        pl.coalesce([
            pl.col(col_name).cast(pl.Date, strict=False),
            pl.col(col_name).cast(pl.Datetime, strict=False).dt.date(),

            raw_text.str.strptime(pl.Date, "%Y-%m-%d", strict=False),
            raw_text.str.strptime(pl.Date, "%d/%m/%Y", strict=False),
            raw_text.str.strptime(pl.Date, "%m/%d/%Y", strict=False),

            raw_text.str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False).dt.date(),
            raw_text.str.strptime(pl.Datetime, "%d/%m/%Y %H:%M:%S", strict=False).dt.date(),
            raw_text.str.strptime(pl.Datetime, "%m/%d/%Y %H:%M:%S", strict=False).dt.date(),
        ])
        .alias(col_name)
    )


# ============================================================
# LOAD DATA
# ============================================================
print("[1/12] Membaca data...")

so = pl.read_excel(SO_FILE)
si = pl.read_excel(SI_FILE)

print(f"Rows SO Summary: {so.height:,}")
print(f"Rows SI: {si.height:,}")


# ============================================================
# VALIDASI KOLOM
# ============================================================
print("[2/12] Validasi kolom...")

SO_REQUIRED_COLUMNS = [
    "Order Date",
    "Status",
    "Salesman Code",
    "Sales Div.Code",
    "Customer Code",
    "Customer Name",
    "Code",
    "Net Price",
    "Net Price Delivery",
]

SI_REQUIRED_COLUMNS = [
    "Type",
    "Invoice Date",
    "Due Date",
    "Paid Date",
    "Salesman",
    "Sales Div.",
    "Customer Code",
    "Customer Name",
    "Code",
    "Net Price",
    "Payment",
    "Total Invoice Balance",
]

require_columns(so, SO_REQUIRED_COLUMNS, "SO Summary")
require_columns(si, SI_REQUIRED_COLUMNS, "Invoice Summary")

print("Validasi kolom selesai.")


# ============================================================
# CLEAN DATA SO SUMMARY
# ============================================================
print("[3/12] Cleaning data SO Summary...")

so = (
    so
    .with_columns([
        normalize_date_expr("Order Date"),

        clean_text_expr("Status"),
        clean_text_expr("Salesman Code"),
        normalize_division_expr("Sales Div.Code"),
        clean_text_expr("Customer Code"),
        clean_text_expr("Customer Name"),
        clean_code_expr("Code"),

        numeric_expr("Net Price"),
        numeric_expr("Net Price Delivery"),
    ])
    .filter(
        pl.col("Order Date").is_not_null()
        & (pl.col("Salesman Code") != "Unknown")
        & (pl.col("Customer Code") != "Unknown")
        & (pl.col("Code") != "")
    )
)

# ============================================================
# STATUS SO LOGIC
# Closed / Cancelled / Declined langsung di-exclude dari SO activity.
# value_so = active SO value, sudah exclude Draft, Cancelled, Closed, Declined.
# gross_so_value = semua SO yang tersisa setelah exclude Closed/Cancel/Declined.
# ============================================================

so = (
    so
    .with_columns([
        (
            pl.col("Status")
            .cast(pl.Utf8, strict=False)
            .fill_null("")
            .str.strip_chars()
            .str.to_uppercase()
            .alias("so_status_upper")
        )
    ])
    .with_columns([
        pl.col("so_status_upper").str.contains("DRAFT").alias("is_quotation_draft"),
        pl.col("so_status_upper").str.contains("CANCEL").alias("is_cancelled"),
        pl.col("so_status_upper").str.contains("CLOS").alias("is_closed"),
        pl.col("so_status_upper").str.contains("DECLIN").alias("is_declined"),
        pl.col("so_status_upper").str.contains("ON HOLD|HOLD").alias("is_onhold"),
    ])
)

if EXCLUDE_CLOSED_CANCELLED_DECLINED_SO:
    so_excluded = so.filter(
        pl.col("is_cancelled")
        | pl.col("is_closed")
        | pl.col("is_declined")
    )

    print("\nSO yang di-exclude dari monitoring:")
    print(
        so_excluded
        .group_by("Status")
        .agg([
            pl.col("Code").n_unique().alias("so_count"),
            pl.col("Net Price").sum().alias("excluded_so_value"),
        ])
        .sort("excluded_so_value", descending=True)
    )

    so = so.filter(
        ~(
            pl.col("is_cancelled")
            | pl.col("is_closed")
            | pl.col("is_declined")
        )
    )

so = (
    so
    .with_columns([
        (
            ~pl.col("is_quotation_draft")
            & ~pl.col("is_cancelled")
            & ~pl.col("is_closed")
            & ~pl.col("is_declined")
        ).alias("is_active_so")
    ])
    .with_columns([
        # Gross SO setelah exclude Closed/Cancelled/Declined.
        pl.col("Net Price").alias("gross_so_value_line"),

        # Active SO value. Ini yang dipakai sebagai value_so.
        pl.when(pl.col("is_active_so"))
        .then(pl.col("Net Price"))
        .otherwise(0)
        .alias("active_so_value_line"),

        # Draft tetap dipisahkan sebagai quotation.
        pl.when(pl.col("is_quotation_draft"))
        .then(pl.col("Net Price"))
        .otherwise(0)
        .alias("quotation_value_line"),

        # Kolom ini tetap dibuat supaya schema dashboard tidak rusak.
        # Karena Cancelled/Closed/Declined sudah di-exclude, nilainya akan 0.
        pl.when(pl.col("is_cancelled"))
        .then(pl.col("Net Price"))
        .otherwise(0)
        .alias("cancelled_so_value_line"),

        pl.when(pl.col("is_closed"))
        .then(pl.col("Net Price"))
        .otherwise(0)
        .alias("closed_so_value_line"),

        pl.when(pl.col("is_declined"))
        .then(pl.col("Net Price"))
        .otherwise(0)
        .alias("declined_so_value_line"),

        pl.col("Net Price Delivery").alias("gross_so_delivery_value_line"),

        pl.when(pl.col("is_active_so"))
        .then(pl.col("Net Price Delivery"))
        .otherwise(0)
        .alias("active_so_delivery_value_line"),

        pl.when(pl.col("is_quotation_draft"))
        .then(pl.lit("Quotation / Draft"))
        .when(pl.col("is_onhold"))
        .then(pl.lit("SO On Hold / Approval"))
        .otherwise(pl.lit("Sales Order Active"))
        .alias("so_status_group"),
    ])
)

print(f"\nRows SO setelah exclude Closed/Cancelled/Declined: {so.height:,}")

print("\nValidasi SO Status Group setelah exclude:")
print(
    so
    .group_by("so_status_group")
    .agg([
        pl.col("Code").n_unique().alias("gross_so_document_count"),
        pl.col("Code").filter(pl.col("is_active_so")).n_unique().alias("active_so_document_count"),
        pl.col("Code").filter(pl.col("is_quotation_draft")).n_unique().alias("draft_so_document_count"),

        pl.col("gross_so_value_line").sum().alias("gross_so_value"),
        pl.col("active_so_value_line").sum().alias("active_so_value"),
        pl.col("quotation_value_line").sum().alias("quotation_value"),
    ])
    .sort("gross_so_value", descending=True)
)


# ============================================================
# CLEAN DATA SI
# ============================================================
print("[4/12] Cleaning data Invoice Summary...")

si = (
    si
    .with_columns([
        (
            pl.col("Type")
            .cast(pl.Utf8, strict=False)
            .str.strip_chars()
            .str.to_uppercase()
            .alias("Type")
        ),

        normalize_date_expr("Invoice Date"),
        normalize_date_expr("Due Date"),
        normalize_date_expr("Paid Date"),

        clean_text_expr("Salesman"),
        normalize_division_expr("Sales Div."),
        clean_text_expr("Customer Code"),
        clean_text_expr("Customer Name"),
        clean_code_expr("Code"),

        numeric_expr("Net Price"),
        numeric_expr("Payment"),
        numeric_expr("Total Invoice Balance"),
    ])
)

si_sales_invoice = (
    si
    .filter(
        (pl.col("Type") == "SALES INVOICE")
        & (pl.col("Code") != "")
        & (pl.col("Salesman") != "Unknown")
        & (pl.col("Customer Code") != "Unknown")
    )
)

print(f"Rows SI SALES INVOICE setelah cleaning: {si_sales_invoice.height:,}")


# ============================================================
# REPORT DATE UNTUK PASS DUE
# ============================================================
max_invoice_date = si_sales_invoice.select(
    pl.col("Invoice Date").max()
).item()

max_order_date = so.select(
    pl.col("Order Date").max()
).item()

date_candidates = [d for d in [max_invoice_date, max_order_date] if d is not None]

if len(date_candidates) == 0:
    raise ValueError("Tidak bisa menentukan REPORT_DATE karena Order Date dan Invoice Date kosong.")

REPORT_DATE = max(date_candidates)

print(f"REPORT_DATE untuk Pass Due: {REPORT_DATE}")


# ============================================================
# 1. SO ACTIVITY
# Date = Order Date
# Activity Status = SO Baru
# ============================================================
print("[5/12] Membuat SO activity...")

so_activity = (
    so
    .group_by(
        [
            "Order Date",
            "Salesman Code",
            "Sales Div.Code",
            "Customer Code",
            "Customer Name",
        ],
        maintain_order=True,
    )
    .agg([
        pl.col("Code").unique().alias("code_list"),

        # Dokumen
        pl.col("Code").n_unique().alias("gross_so_document_count"),
        pl.col("Code").filter(pl.col("is_active_so")).n_unique().alias("so_document_count"),
        pl.col("Code").filter(pl.col("is_active_so")).n_unique().alias("active_so_document_count"),
        pl.col("Code").filter(pl.col("is_quotation_draft")).n_unique().alias("draft_so_document_count"),

        # Karena sudah di-exclude, ini akan 0. Tetap disediakan untuk schema compatibility.
        pl.col("Code").filter(pl.col("is_cancelled")).n_unique().alias("cancelled_so_document_count"),
        pl.col("Code").filter(pl.col("is_closed")).n_unique().alias("closed_so_document_count"),
        pl.col("Code").filter(pl.col("is_declined")).n_unique().alias("declined_so_document_count"),

        # VALUE UTAMA
        # value_so = active SO value
        pl.col("active_so_value_line").sum().alias("value_so"),
        pl.col("active_so_delivery_value_line").sum().alias("value_so_delivery"),

        # Gross setelah exclude Closed/Cancelled/Declined
        pl.col("gross_so_value_line").sum().alias("gross_so_value"),
        pl.col("gross_so_delivery_value_line").sum().alias("gross_so_delivery_value"),

        # Breakdown status
        pl.col("active_so_value_line").sum().alias("active_so_value"),
        pl.col("active_so_delivery_value_line").sum().alias("active_so_delivery_value"),
        pl.col("quotation_value_line").sum().alias("quotation_value"),
        pl.col("cancelled_so_value_line").sum().alias("cancelled_so_value"),
        pl.col("closed_so_value_line").sum().alias("closed_so_value"),
        pl.col("declined_so_value_line").sum().alias("declined_so_value"),

        pl.len().alias("total_so_line"),

        pl.col("so_status_group").unique().alias("so_status_group_list"),
        pl.col("Status").unique().alias("so_status_list"),
    ])
    .with_columns([
        pl.col("code_list")
        .map_elements(join_list, return_dtype=pl.Utf8)
        .alias("Code"),

        pl.col("so_status_group_list")
        .map_elements(join_list, return_dtype=pl.Utf8)
        .alias("so_status_group"),

        pl.col("so_status_list")
        .map_elements(join_list, return_dtype=pl.Utf8)
        .alias("so_status"),
    ])
    .drop(["code_list", "so_status_group_list", "so_status_list"])
    .rename({
        "Order Date": "date",
        "Salesman Code": "salesman",
        "Sales Div.Code": "division",
        "Customer Code": "customer_code",
        "Customer Name": "customer_name",
    })
    .with_columns([
        pl.lit("SO Baru").alias("activity_status"),
        pl.lit(1).alias("activity_so"),
        pl.lit(0).alias("activity_invoice"),
        pl.lit(0).alias("activity_payment"),
        pl.lit(0).alias("activity_due"),
        pl.lit(0).alias("activity_past_due"),
    ])
)

print(f"Rows SO activity: {so_activity.height:,}")


# ============================================================
# 2. INVOICE ACTIVITY
# ============================================================
print("[6/12] Membuat invoice activity...")

invoice_activity = (
    si_sales_invoice
    .filter(
        pl.col("Invoice Date").is_not_null()
    )
    .group_by(
        [
            "Invoice Date",
            "Salesman",
            "Sales Div.",
            "Customer Code",
            "Customer Name",
        ],
        maintain_order=True,
    )
    .agg([
        pl.col("Code").n_unique().alias("invoice_document_count"),
        pl.col("Code").unique().alias("code_list"),
        pl.col("Net Price").sum().alias("value_invoice"),
        pl.col("Total Invoice Balance").sum().alias("invoice_balance_on_activity"),

        # COHORT COLLECTION:
        # Setiap baris SI membawa Invoice Date DAN Payment untuk invoice yang sama,
        # jadi payment di sini otomatis "match" ke invoice induknya dan diatribusikan
        # ke TANGGAL INVOICE — walaupun uangnya diterima di tanggal lain. Ini dasar
        # KPI Persentase Pembayaran yang benar (bukan payment_pct lama yang grain-nya
        # terpisah antara baris Payment dan baris Invoice/Tagihan).
        pl.col("Net Price").sum().alias("invoice_value_on_invoice_date"),
        pl.col("Payment").abs().sum().alias("payment_matched_to_invoice_date"),
    ])
    .with_columns(
        pl.col("code_list")
        .map_elements(join_list, return_dtype=pl.Utf8)
        .alias("Code")
    )
    .drop("code_list")
    .rename({
        "Invoice Date": "date",
        "Salesman": "salesman",
        "Sales Div.": "division",
        "Customer Code": "customer_code",
        "Customer Name": "customer_name",
    })
    .with_columns([
        pl.lit("Invoice/Tagihan").alias("activity_status"),
        pl.lit(0).alias("activity_so"),
        pl.lit(1).alias("activity_invoice"),
        pl.lit(0).alias("activity_payment"),
        pl.lit(0).alias("activity_due"),
        pl.lit(0).alias("activity_past_due"),
    ])
)

print(f"Rows invoice activity: {invoice_activity.height:,}")


# ============================================================
# 3. PAYMENT ACTIVITY
# ============================================================
print("[7/12] Membuat payment activity...")

payment_activity = (
    si_sales_invoice
    .filter(
        pl.col("Paid Date").is_not_null()
        & (pl.col("Payment") != 0)
    )
    .with_columns(
        pl.col("Payment").abs().alias("payment_value")
    )
    .group_by(
        [
            "Paid Date",
            "Salesman",
            "Sales Div.",
            "Customer Code",
            "Customer Name",
        ],
        maintain_order=True,
    )
    .agg([
        pl.col("Code").n_unique().alias("paid_invoice_count"),
        pl.col("Code").unique().alias("code_list"),
        pl.col("payment_value").sum().alias("payment_value"),
    ])
    .with_columns(
        pl.col("code_list")
        .map_elements(join_list, return_dtype=pl.Utf8)
        .alias("Code")
    )
    .drop("code_list")
    .rename({
        "Paid Date": "date",
        "Salesman": "salesman",
        "Sales Div.": "division",
        "Customer Code": "customer_code",
        "Customer Name": "customer_name",
    })
    .with_columns([
        pl.lit("Payment").alias("activity_status"),
        pl.lit(0).alias("activity_so"),
        pl.lit(0).alias("activity_invoice"),
        pl.lit(1).alias("activity_payment"),
        pl.lit(0).alias("activity_due"),
        pl.lit(0).alias("activity_past_due"),
    ])
)

print(f"Rows payment activity: {payment_activity.height:,}")


# ============================================================
# 4. DUE ACTIVITY
# ============================================================
print("[8/12] Membuat due activity...")

due_activity = (
    si_sales_invoice
    .filter(
        pl.col("Due Date").is_not_null()
        & (pl.col("Total Invoice Balance") > 0)
    )
    .group_by(
        [
            "Due Date",
            "Salesman",
            "Sales Div.",
            "Customer Code",
            "Customer Name",
        ],
        maintain_order=True,
    )
    .agg([
        pl.col("Code").n_unique().alias("due_invoice_count"),
        pl.col("Code").unique().alias("code_list"),
        pl.col("Total Invoice Balance").sum().alias("due_invoice_value"),
    ])
    .with_columns(
        pl.col("code_list")
        .map_elements(join_list, return_dtype=pl.Utf8)
        .alias("Code")
    )
    .drop("code_list")
    .rename({
        "Due Date": "date",
        "Salesman": "salesman",
        "Sales Div.": "division",
        "Customer Code": "customer_code",
        "Customer Name": "customer_name",
    })
    .with_columns([
        pl.lit("Jatuh Tempo").alias("activity_status"),
        pl.lit(0).alias("activity_so"),
        pl.lit(0).alias("activity_invoice"),
        pl.lit(0).alias("activity_payment"),
        pl.lit(1).alias("activity_due"),
        pl.lit(0).alias("activity_past_due"),
    ])
)

print(f"Rows due activity: {due_activity.height:,}")


# ============================================================
# 5. PAST DUE ACTIVITY
# ============================================================
print("[9/12] Membuat past due activity...")

past_due_activity = (
    si_sales_invoice
    .filter(
        pl.col("Due Date").is_not_null()
        & (pl.col("Due Date") < pl.lit(REPORT_DATE))
        & (pl.col("Total Invoice Balance") > 0)
    )
    .group_by(
        [
            "Salesman",
            "Sales Div.",
            "Customer Code",
            "Customer Name",
        ],
        maintain_order=True,
    )
    .agg([
        pl.col("Code").n_unique().alias("past_due_invoice_count"),
        pl.col("Code").unique().alias("code_list"),
        pl.col("Net Price").sum().alias("past_due_invoice_value"),
        pl.col("Total Invoice Balance").sum().alias("past_due_balance_value"),
    ])
    .with_columns(
        pl.col("code_list")
        .map_elements(join_list, return_dtype=pl.Utf8)
        .alias("Code")
    )
    .drop("code_list")
    .rename({
        "Salesman": "salesman",
        "Sales Div.": "division",
        "Customer Code": "customer_code",
        "Customer Name": "customer_name",
    })
    .with_columns([
        pl.lit(REPORT_DATE).cast(pl.Date).alias("date"),
        pl.lit("Pass Due").alias("activity_status"),
        pl.lit(0).alias("activity_so"),
        pl.lit(0).alias("activity_invoice"),
        pl.lit(0).alias("activity_payment"),
        pl.lit(0).alias("activity_due"),
        pl.lit(1).alias("activity_past_due"),
    ])
)

print(f"Rows past due activity: {past_due_activity.height:,}")


# ============================================================
# COMBINE DAILY ACTIVITY
# ============================================================
print("[10/12] Menggabungkan daily activity...")

daily_activity = pl.concat(
    [
        so_activity,
        invoice_activity,
        payment_activity,
        due_activity,
        past_due_activity,
    ],
    how="diagonal_relaxed",
)

daily_activity = (
    daily_activity
    .with_columns(
        normalize_date_expr("date")
    )
    .with_columns([
        pl.col("activity_status").fill_null("No Activity"),
        pl.col("Code").fill_null(""),

        # SO aligned fields
        pl.col("gross_so_document_count").fill_null(0),
        pl.col("so_document_count").fill_null(0),
        pl.col("active_so_document_count").fill_null(0),
        pl.col("draft_so_document_count").fill_null(0),
        pl.col("cancelled_so_document_count").fill_null(0),
        pl.col("closed_so_document_count").fill_null(0),
        pl.col("declined_so_document_count").fill_null(0),

        pl.col("value_so").fill_null(0),
        pl.col("value_so_delivery").fill_null(0),
        pl.col("gross_so_value").fill_null(0),
        pl.col("gross_so_delivery_value").fill_null(0),
        pl.col("active_so_value").fill_null(0),
        pl.col("active_so_delivery_value").fill_null(0),
        pl.col("quotation_value").fill_null(0),
        pl.col("cancelled_so_value").fill_null(0),
        pl.col("closed_so_value").fill_null(0),
        pl.col("declined_so_value").fill_null(0),

        pl.col("total_so_line").fill_null(0),
        pl.col("activity_so").fill_null(0),
        pl.col("so_status_group").fill_null(""),
        pl.col("so_status").fill_null(""),

        # Invoice
        pl.col("invoice_document_count").fill_null(0),
        pl.col("value_invoice").fill_null(0),
        pl.col("invoice_balance_on_activity").fill_null(0),
        pl.col("activity_invoice").fill_null(0),
        pl.col("invoice_value_on_invoice_date").fill_null(0),
        pl.col("payment_matched_to_invoice_date").fill_null(0),

        # Payment
        pl.col("paid_invoice_count").fill_null(0),
        pl.col("payment_value").fill_null(0),
        pl.col("activity_payment").fill_null(0),

        # Due
        pl.col("due_invoice_count").fill_null(0),
        pl.col("due_invoice_value").fill_null(0),
        pl.col("activity_due").fill_null(0),

        # Past due
        pl.col("past_due_invoice_count").fill_null(0),
        pl.col("past_due_invoice_value").fill_null(0),
        pl.col("past_due_balance_value").fill_null(0),
        pl.col("activity_past_due").fill_null(0),
    ])
)

print(f"Rows daily activity: {daily_activity.height:,}")


# ============================================================
# TABLE 2: SALES CUSTOMER MONITORING
# Grain: Date + Branch + Division + Salesman + Customer + Activity Status
# ============================================================
print("[11/12] Membuat sales_customer_monitoring...")

sales_customer_monitoring = (
    daily_activity
    .group_by(
        [
            "date",
            "salesman",
            "division",
            "customer_code",
            "customer_name",
            "activity_status",
        ],
        maintain_order=True,
    )
    .agg([
        pl.col("Code").alias("code_list"),

        # SO aligned fields
        pl.col("gross_so_document_count").sum().alias("gross_so_document_count"),
        pl.col("so_document_count").sum().alias("so_document_count"),
        pl.col("active_so_document_count").sum().alias("active_so_document_count"),
        pl.col("draft_so_document_count").sum().alias("draft_so_document_count"),
        pl.col("cancelled_so_document_count").sum().alias("cancelled_so_document_count"),
        pl.col("closed_so_document_count").sum().alias("closed_so_document_count"),
        pl.col("declined_so_document_count").sum().alias("declined_so_document_count"),

        # value_so = active SO value
        pl.col("value_so").sum().alias("value_so"),
        pl.col("value_so_delivery").sum().alias("value_so_delivery"),

        # gross setelah exclude Closed/Cancelled/Declined
        pl.col("gross_so_value").sum().alias("gross_so_value"),
        pl.col("gross_so_delivery_value").sum().alias("gross_so_delivery_value"),

        pl.col("active_so_value").sum().alias("active_so_value"),
        pl.col("active_so_delivery_value").sum().alias("active_so_delivery_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("cancelled_so_value").sum().alias("cancelled_so_value"),
        pl.col("closed_so_value").sum().alias("closed_so_value"),
        pl.col("declined_so_value").sum().alias("declined_so_value"),

        pl.col("total_so_line").sum().alias("total_so_line"),

        pl.col("so_status_group").alias("so_status_group_list"),
        pl.col("so_status").alias("so_status_list"),

        # Invoice
        pl.col("invoice_document_count").sum().alias("invoice_document_count"),
        pl.col("value_invoice").sum().alias("value_invoice"),
        pl.col("invoice_balance_on_activity").sum().alias("invoice_balance_on_activity"),

        # Cohort collection (basis tanggal invoice)
        pl.col("invoice_value_on_invoice_date").sum().alias("invoice_value_on_invoice_date"),
        pl.col("payment_matched_to_invoice_date").sum().alias("payment_matched_to_invoice_date"),

        # Payment
        pl.col("paid_invoice_count").sum().alias("paid_invoice_count"),
        pl.col("payment_value").sum().alias("payment_value"),

        # Due
        pl.col("due_invoice_count").sum().alias("due_invoice_count"),
        pl.col("due_invoice_value").sum().alias("due_invoice_value"),

        # Pass due
        pl.col("past_due_invoice_count").sum().alias("past_due_invoice_count"),
        pl.col("past_due_invoice_value").sum().alias("past_due_invoice_value"),
        pl.col("past_due_balance_value").sum().alias("past_due_balance_value"),

        # Activity flags
        pl.col("activity_so").max().alias("has_so"),
        pl.col("activity_invoice").max().alias("has_invoice"),
        pl.col("activity_payment").max().alias("has_payment"),
        pl.col("activity_due").max().alias("has_due"),
        pl.col("activity_past_due").max().alias("has_past_due"),
    ])
    .with_columns([
        pl.col("code_list")
        .map_elements(combine_csv_values, return_dtype=pl.Utf8)
        .alias("Code"),

        pl.col("so_status_group_list")
        .map_elements(combine_csv_values, return_dtype=pl.Utf8)
        .alias("so_status_group"),

        pl.col("so_status_list")
        .map_elements(combine_csv_values, return_dtype=pl.Utf8)
        .alias("so_status"),
    ])
    .drop(["code_list", "so_status_group_list", "so_status_list"])
    .with_columns([
        pl.col("salesman")
        .map_elements(assign_branch_from_salesman, return_dtype=pl.Utf8)
        .alias("branch"),

        (
            pl.col("has_so")
            + pl.col("has_invoice")
            + pl.col("has_payment")
            + pl.col("has_due")
            + pl.col("has_past_due")
        ).alias("activity_count"),

        (
            pl.when(pl.col("value_so") != 0)
            .then((pl.col("value_invoice") / pl.col("value_so")) * 100)
            .otherwise(0)
            .alias("invoice_vs_so_value_pct")
        ),

        (
            pl.when(pl.col("gross_so_value") != 0)
            .then((pl.col("value_invoice") / pl.col("gross_so_value")) * 100)
            .otherwise(0)
            .alias("invoice_vs_gross_so_value_pct")
        ),

        (
            pl.when(pl.col("value_invoice") != 0)
            .then((pl.col("payment_value") / pl.col("value_invoice")) * 100)
            .otherwise(0)
            .alias("payment_vs_invoice_pct")
        ),

        # Collection rate per cohort tanggal invoice (persen). NULL (bukan 0/100)
        # saat tidak ada invoice terbit di cohort ini — di BI tampil sebagai "-"/N/A.
        (
            pl.when(pl.col("invoice_value_on_invoice_date") != 0)
            .then((pl.col("payment_matched_to_invoice_date") / pl.col("invoice_value_on_invoice_date")) * 100)
            .otherwise(None)
            .alias("collection_rate_cohort")
        ),

        (
            pl.col("value_so") - pl.col("value_so_delivery")
        ).alias("undelivered_so_value"),

        (
            pl.col("gross_so_value") - pl.col("gross_so_delivery_value")
        ).alias("undelivered_gross_so_value"),

        (
            pl.col("value_invoice") - pl.col("payment_value")
        ).alias("unpaid_invoice_on_activity"),
    ])
    .with_columns([
        pl.col("gross_so_document_count").cast(pl.Int64),
        pl.col("so_document_count").cast(pl.Int64),
        pl.col("active_so_document_count").cast(pl.Int64),
        pl.col("draft_so_document_count").cast(pl.Int64),
        pl.col("cancelled_so_document_count").cast(pl.Int64),
        pl.col("closed_so_document_count").cast(pl.Int64),
        pl.col("declined_so_document_count").cast(pl.Int64),
        pl.col("total_so_line").cast(pl.Int64),

        pl.col("invoice_document_count").cast(pl.Int64),
        pl.col("paid_invoice_count").cast(pl.Int64),
        pl.col("due_invoice_count").cast(pl.Int64),
        pl.col("past_due_invoice_count").cast(pl.Int64),

        pl.col("has_so").cast(pl.Int64),
        pl.col("has_invoice").cast(pl.Int64),
        pl.col("has_payment").cast(pl.Int64),
        pl.col("has_due").cast(pl.Int64),
        pl.col("has_past_due").cast(pl.Int64),
        pl.col("activity_count").cast(pl.Int64),
    ])
    .select([
        "date",
        "branch",
        "division",
        "salesman",
        "customer_code",
        "customer_name",
        "activity_status",
        "activity_count",
        "Code",

        # SO status info
        "so_status_group",
        "so_status",

        # Activity flags
        "has_so",
        "has_invoice",
        "has_payment",
        "has_due",
        "has_past_due",

        # SO utama
        "so_document_count",
        "value_so",
        "value_so_delivery",
        "undelivered_so_value",

        # SO gross setelah exclude Closed/Cancelled/Declined
        "gross_so_document_count",
        "gross_so_value",
        "gross_so_delivery_value",
        "undelivered_gross_so_value",

        # SO breakdown
        "active_so_document_count",
        "draft_so_document_count",
        "cancelled_so_document_count",
        "closed_so_document_count",
        "declined_so_document_count",

        "active_so_value",
        "active_so_delivery_value",
        "quotation_value",
        "cancelled_so_value",
        "closed_so_value",
        "declined_so_value",
        "total_so_line",

        # Invoice
        "invoice_document_count",
        "value_invoice",
        "invoice_balance_on_activity",

        # Cohort collection (basis tanggal invoice)
        "invoice_value_on_invoice_date",
        "payment_matched_to_invoice_date",
        "collection_rate_cohort",

        # Payment
        "paid_invoice_count",
        "payment_value",

        # Due
        "due_invoice_count",
        "due_invoice_value",

        # Past Due
        "past_due_invoice_count",
        "past_due_invoice_value",
        "past_due_balance_value",

        # Ratios
        "invoice_vs_so_value_pct",
        "invoice_vs_gross_so_value_pct",
        "payment_vs_invoice_pct",
        "unpaid_invoice_on_activity",
    ])
    .sort([
        "date",
        "branch",
        "division",
        "salesman",
        "customer_code",
        "customer_name",
        "activity_status",
    ])
)

print(f"Rows sales_customer_monitoring: {sales_customer_monitoring.height:,}")


# ============================================================
# TABLE 1: SALES MONITORING
# Grain: Date + Branch + Division + Salesman + Activity Status
# ============================================================
print("[12/12] Membuat sales_monitoring simple + activity_status + due/pass due...")

sales_monitoring = (
    sales_customer_monitoring
    .group_by(
        [
            "date",
            "branch",
            "division",
            "salesman",
            "activity_status",
        ],
        maintain_order=True,
    )
    .agg([
        pl.col("Code").alias("code_list"),

        # SO utama
        pl.col("so_document_count").sum().alias("total_so"),
        pl.col("value_so").sum().alias("value_so"),
        pl.col("value_so_delivery").sum().alias("value_so_delivery"),
        pl.col("undelivered_so_value").sum().alias("undelivered_so_value"),

        # SO gross setelah exclude Closed/Cancelled/Declined
        pl.col("gross_so_document_count").sum().alias("gross_total_so"),
        pl.col("gross_so_value").sum().alias("gross_so_value"),
        pl.col("gross_so_delivery_value").sum().alias("gross_so_delivery_value"),
        pl.col("undelivered_gross_so_value").sum().alias("undelivered_gross_so_value"),

        # SO breakdown
        pl.col("active_so_document_count").sum().alias("active_so_document_count"),
        pl.col("draft_so_document_count").sum().alias("draft_so_document_count"),
        pl.col("cancelled_so_document_count").sum().alias("cancelled_so_document_count"),
        pl.col("closed_so_document_count").sum().alias("closed_so_document_count"),
        pl.col("declined_so_document_count").sum().alias("declined_so_document_count"),

        pl.col("active_so_value").sum().alias("active_so_value"),
        pl.col("active_so_delivery_value").sum().alias("active_so_delivery_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("cancelled_so_value").sum().alias("cancelled_so_value"),
        pl.col("closed_so_value").sum().alias("closed_so_value"),
        pl.col("declined_so_value").sum().alias("declined_so_value"),

        pl.col("so_status_group").alias("so_status_group_list"),
        pl.col("so_status").alias("so_status_list"),

        # Invoice
        pl.col("invoice_document_count").sum().alias("total_si"),
        pl.col("value_invoice").sum().alias("value_si"),

        # Cohort collection (basis tanggal invoice)
        pl.col("invoice_value_on_invoice_date").sum().alias("invoice_value_on_invoice_date"),
        pl.col("payment_matched_to_invoice_date").sum().alias("payment_matched_to_invoice_date"),

        # Payment & Balance
        pl.col("payment_value").sum().alias("total_payment"),
        pl.col("invoice_balance_on_activity").sum().alias("total_sales_balance"),

        # Due
        pl.col("due_invoice_count").sum().alias("due_invoice_count"),
        pl.col("due_invoice_value").sum().alias("due_invoice_value"),

        # Pass Due
        pl.col("past_due_invoice_count").sum().alias("past_due_invoice_count"),
        pl.col("past_due_invoice_value").sum().alias("past_due_invoice_value"),
        pl.col("past_due_balance_value").sum().alias("past_due_balance_value"),

        # Activity flags
        pl.col("has_so").max().alias("has_so"),
        pl.col("has_invoice").max().alias("has_invoice"),
        pl.col("has_payment").max().alias("has_payment"),
        pl.col("has_due").max().alias("has_due"),
        pl.col("has_past_due").max().alias("has_past_due"),
    ])
    .with_columns([
        pl.col("code_list")
        .map_elements(combine_csv_values, return_dtype=pl.Utf8)
        .alias("Code"),

        pl.col("so_status_group_list")
        .map_elements(combine_csv_values, return_dtype=pl.Utf8)
        .alias("so_status_group"),

        pl.col("so_status_list")
        .map_elements(combine_csv_values, return_dtype=pl.Utf8)
        .alias("so_status"),
    ])
    .drop(["code_list", "so_status_group_list", "so_status_list"])
    .with_columns([
        (
            pl.col("has_so")
            + pl.col("has_invoice")
            + pl.col("has_payment")
            + pl.col("has_due")
            + pl.col("has_past_due")
        ).alias("activity_count"),

        (
            pl.when(pl.col("value_so") != 0)
            .then((pl.col("value_si") / pl.col("value_so")) * 100)
            .otherwise(0)
            .alias("invoice_conversion_value_pct")
        ),

        (
            pl.when(pl.col("gross_so_value") != 0)
            .then((pl.col("value_si") / pl.col("gross_so_value")) * 100)
            .otherwise(0)
            .alias("invoice_conversion_gross_so_value_pct")
        ),

        (
            pl.when(pl.col("total_so") != 0)
            .then((pl.col("total_si") / pl.col("total_so")) * 100)
            .otherwise(0)
            .alias("invoice_conversion_count_pct")
        ),

        (
            pl.when(pl.col("value_si") != 0)
            .then((pl.col("total_payment") / pl.col("value_si")) * 100)
            .otherwise(0)
            .alias("payment_pct")
        ),

        (
            pl.when(pl.col("value_si") != 0)
            .then((pl.col("total_sales_balance") / pl.col("value_si")) * 100)
            .otherwise(0)
            .alias("outstanding_pct")
        ),

        # Collection rate per cohort tanggal invoice (persen) — dihitung ulang dari
        # SUM di grain ini, bukan rata-rata rasio. NULL saat cohort tanpa invoice,
        # supaya BI menampilkan "-"/N/A alih-alih 100% palsu.
        (
            pl.when(pl.col("invoice_value_on_invoice_date") != 0)
            .then((pl.col("payment_matched_to_invoice_date") / pl.col("invoice_value_on_invoice_date")) * 100)
            .otherwise(None)
            .alias("collection_rate_cohort")
        ),

        (
            pl.col("value_so") - pl.col("value_si")
        ).alias("outstanding_so_value"),

        (
            pl.col("gross_so_value") - pl.col("value_si")
        ).alias("outstanding_gross_so_value"),
    ])
    .with_columns([
        pl.col("total_so").cast(pl.Int64),
        pl.col("gross_total_so").cast(pl.Int64),
        pl.col("total_si").cast(pl.Int64),

        pl.col("active_so_document_count").cast(pl.Int64),
        pl.col("draft_so_document_count").cast(pl.Int64),
        pl.col("cancelled_so_document_count").cast(pl.Int64),
        pl.col("closed_so_document_count").cast(pl.Int64),
        pl.col("declined_so_document_count").cast(pl.Int64),

        pl.col("due_invoice_count").cast(pl.Int64),
        pl.col("past_due_invoice_count").cast(pl.Int64),

        pl.col("has_so").cast(pl.Int64),
        pl.col("has_invoice").cast(pl.Int64),
        pl.col("has_payment").cast(pl.Int64),
        pl.col("has_due").cast(pl.Int64),
        pl.col("has_past_due").cast(pl.Int64),
        pl.col("activity_count").cast(pl.Int64),
    ])
    .select([
        pl.col("date").alias("Date"),
        pl.col("branch"),
        pl.col("division"),
        pl.col("salesman").alias("Salesman"),
        pl.col("activity_status"),
        pl.col("activity_count"),
        pl.col("Code"),

        # SO status info
        pl.col("so_status_group"),
        pl.col("so_status"),

        # Flags untuk filter aman
        pl.col("has_so"),
        pl.col("has_invoice"),
        pl.col("has_payment"),
        pl.col("has_due"),
        pl.col("has_past_due"),

        # Field utama
        pl.col("total_so"),
        pl.col("value_so"),
        pl.col("value_so_delivery"),
        pl.col("undelivered_so_value"),

        # Gross SO setelah exclude closed/cancel/declined
        pl.col("gross_total_so"),
        pl.col("gross_so_value"),
        pl.col("gross_so_delivery_value"),
        pl.col("undelivered_gross_so_value"),

        # Breakdown SO
        pl.col("active_so_document_count"),
        pl.col("draft_so_document_count"),
        pl.col("cancelled_so_document_count"),
        pl.col("closed_so_document_count"),
        pl.col("declined_so_document_count"),

        pl.col("active_so_value"),
        pl.col("active_so_delivery_value"),
        pl.col("quotation_value"),
        pl.col("cancelled_so_value"),
        pl.col("closed_so_value"),
        pl.col("declined_so_value"),

        # Invoice
        pl.col("total_si"),
        pl.col("value_si"),

        # Cohort collection (basis tanggal invoice) — dasar KPI Persentase Pembayaran
        pl.col("invoice_value_on_invoice_date"),
        pl.col("payment_matched_to_invoice_date"),
        pl.col("collection_rate_cohort"),

        # Payment & Balance
        pl.col("total_payment"),
        pl.col("total_sales_balance"),

        # Due
        pl.col("due_invoice_count"),
        pl.col("due_invoice_value"),

        # Pass Due
        pl.col("past_due_invoice_count"),
        pl.col("past_due_invoice_value"),
        pl.col("past_due_balance_value"),

        # KPI / ratio
        pl.col("invoice_conversion_value_pct"),
        pl.col("invoice_conversion_gross_so_value_pct"),
        pl.col("invoice_conversion_count_pct"),
        pl.col("payment_pct"),
        pl.col("outstanding_pct"),
        pl.col("outstanding_so_value"),
        pl.col("outstanding_gross_so_value"),
    ])
    .sort([
        "Date",
        "branch",
        "division",
        "Salesman",
        "activity_status",
    ])
)

print(f"Rows sales_monitoring: {sales_monitoring.height:,}")


# ============================================================
# VALIDASI ACTIVITY STATUS CATEGORY
# ============================================================
print("\nValidasi activity_status sales_monitoring:")
print(
    sales_monitoring
    .select(pl.col("activity_status").unique().sort())
)

print("\nValidasi activity_status sales_customer_monitoring:")
print(
    sales_customer_monitoring
    .select(pl.col("activity_status").unique().sort())
)


# ============================================================
# VALIDASI SO STATUS GROUP
# ============================================================
print("\nValidasi so_status_group sales_monitoring:")
print(
    sales_monitoring
    .filter(pl.col("activity_status") == "SO Baru")
    .group_by("so_status_group")
    .agg([
        pl.len().alias("rows"),

        pl.col("gross_total_so").sum().alias("gross_total_so"),
        pl.col("total_so").sum().alias("active_total_so"),

        pl.col("gross_so_value").sum().alias("gross_so_value_after_exclude"),
        pl.col("value_so").sum().alias("active_so_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("cancelled_so_value").sum().alias("cancelled_so_value_should_be_zero"),
        pl.col("closed_so_value").sum().alias("closed_so_value_should_be_zero"),
        pl.col("declined_so_value").sum().alias("declined_so_value_should_be_zero"),
    ])
    .sort("gross_so_value_after_exclude", descending=True)
)


# ============================================================
# VALIDASI REKONSILIASI SO
# ============================================================
print("\nValidasi rekonsiliasi SO value setelah exclude Closed/Cancelled/Declined:")
print(
    sales_monitoring
    .filter(pl.col("activity_status") == "SO Baru")
    .select([
        pl.col("gross_so_value").sum().alias("gross_so_value_after_exclude"),
        pl.col("value_so").sum().alias("active_so_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("cancelled_so_value").sum().alias("cancelled_so_value_should_be_zero"),
        pl.col("closed_so_value").sum().alias("closed_so_value_should_be_zero"),
        pl.col("declined_so_value").sum().alias("declined_so_value_should_be_zero"),
    ])
    .with_columns([
        (
            pl.col("active_so_value")
            + pl.col("quotation_value")
        ).alias("reconciled_so_value"),

        (
            pl.col("gross_so_value_after_exclude")
            - (
                pl.col("active_so_value")
                + pl.col("quotation_value")
            )
        ).alias("difference")
    ])
)


# ============================================================
# VALIDASI CODE PER ACTIVITY STATUS
# ============================================================
print("\nValidasi Code di sales_customer_monitoring:")
print(
    sales_customer_monitoring
    .group_by("activity_status")
    .agg([
        pl.len().alias("rows"),
        (pl.col("Code") != "").sum().alias("rows_with_Code"),
    ])
    .sort("activity_status")
)


# ============================================================
# VALIDASI COLLECTION RATE COHORT (Tracking Payment)
# ============================================================
print("\nValidasi collection rate per cohort tanggal invoice (7 hari aktivitas invoice/payment terakhir):")
print(
    sales_monitoring
    .group_by("Date")
    .agg([
        pl.col("value_si").sum().alias("nilai_sales_invoice"),
        pl.col("total_sales_balance").sum().alias("sisa_tagihan"),
        pl.col("total_payment").sum().alias("total_pembayaran_diterima"),
        pl.col("invoice_value_on_invoice_date").sum().alias("invoice_cohort"),
        pl.col("payment_matched_to_invoice_date").sum().alias("payment_matched"),
    ])
    # hanya hari dengan aktivitas invoice atau payment (baris Jatuh Tempo/Pass Due
    # memakai tanggal due di masa depan dan tidak relevan untuk KPI ini)
    .filter((pl.col("invoice_cohort") != 0) | (pl.col("total_pembayaran_diterima") != 0))
    .with_columns([
        # formula lama di BI (menyesatkan saat filter sempit) — hanya pembanding
        pl.when((pl.col("total_pembayaran_diterima") + pl.col("sisa_tagihan")) != 0)
        .then(pl.col("total_pembayaran_diterima") / (pl.col("total_pembayaran_diterima") + pl.col("sisa_tagihan")) * 100)
        .otherwise(None)
        .round(2)
        .alias("pct_formula_lama"),
        # metrik baru: pelunasan invoice yang benar-benar terbit di tanggal tsb
        pl.when(pl.col("invoice_cohort") != 0)
        .then(pl.col("payment_matched") / pl.col("invoice_cohort") * 100)
        .otherwise(None)
        .round(2)
        .alias("collection_rate_cohort"),
    ])
    .sort("Date", descending=True)
    .head(7)
)

# No local output file: the only persistent output is the BigQuery upload —
# everything else is shown through the run log.


# ============================================================
# UPLOAD TO BIGQUERY
# ============================================================

upload_polars_to_bigquery(
    df=sales_monitoring,
    table_name=TABLE_SALES_MONITORING,
    write_disposition="WRITE_TRUNCATE"
)

upload_polars_to_bigquery(
    df=sales_customer_monitoring,
    table_name=TABLE_SALES_CUSTOMER_MONITORING,
    write_disposition="WRITE_TRUNCATE"
)


# ============================================================
# PREVIEW
# ============================================================
print("Preview sales_monitoring:")
print(sales_monitoring.head())

print("Preview sales_customer_monitoring:")
print(sales_customer_monitoring.head())

print("Preview so_activity:")
print(so_activity.head())

print("Preview past_due_activity:")
print(past_due_activity.head())
