# Business Flow (order-to-cash) pipeline.
# Input files are passed as arguments (never hardcoded here).
# BigQuery auth: explicit service account key. The key path is configured in
# ONE place — env var BQ_KEY_FILE (default: pipamas-v3-f08db75e6c67.json,
# looked up in the working directory, then next to the app root).

# ============================================================
# IMPORT LIBRARY
# ============================================================
import argparse
import os
import re
import tempfile
import datetime as dt

import polars as pl

from google.cloud import bigquery
from google.oauth2 import service_account
from google.api_core.exceptions import NotFound


def _load_bq_credentials():
    key_file = os.environ.get("BQ_KEY_FILE", "pipamas-v3-f08db75e6c67.json")
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
pl.Config.set_tbl_cols(120)
pl.Config.set_tbl_width_chars(320)


# ============================================================
# BIGQUERY CONFIG
# ============================================================
PROJECT_ID = os.environ.get("BQ_PROJECT_ID", "pipamas-v3")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "data")

BQ_LOCATION = os.environ.get("BQ_LOCATION") or None
WRITE_DISPOSITION = "WRITE_TRUNCATE"
TABLE_PREFIX = "o2c_"


# ============================================================
# FILE INPUT
# ============================================================

_parser = argparse.ArgumentParser(description="Business Flow")
_parser.add_argument("--so", required=True, help="SO Summary .xlsx")
_parser.add_argument("--packing", required=True, help="Packing Summary .xlsx")
_parser.add_argument("--invoice", required=True, help="Invoice Summary .xlsx")
_ARGS = _parser.parse_args()

SO_FILE = _ARGS.so
PACKING_FILE = _ARGS.packing
INVOICE_FILE = _ARGS.invoice


# ============================================================
# LOAD DATA USING POLARS
# ============================================================

print("[1/14] Membaca file Excel dengan Polars...")

so = pl.read_excel(SO_FILE)
ps = pl.read_excel(PACKING_FILE)
si = pl.read_excel(INVOICE_FILE)

print(f"Rows SO           : {so.height:,}")
print(f"Rows Packing Slip : {ps.height:,}")
print(f"Rows Invoice      : {si.height:,}")


# ============================================================
# BUSINESS CONFIG
# ============================================================

QUOTATION_STATUS_KEYWORD = "DRAFT"

# Return document dikeluarkan.
EXCLUDE_RETURN_DOCS = True

# SO Cancelled / Closed / Declined dikeluarkan dari flow sejak awal.
EXCLUDE_CLOSED_CANCELLED_DECLINED_SO = True

# Jika ingin mengunci tanggal report manual, isi di sini.
# Contoh:
# REPORT_AS_OF_DATE_OVERRIDE = dt.date(2026, 7, 6)
REPORT_AS_OF_DATE_OVERRIDE = None

PACKING_TOLERANCE = 0.98
INVOICE_TOLERANCE = 0.98
PAYMENT_TOLERANCE = 0.98

# Karena Cancelled / Closed / Declined sudah di-exclude dari awal,
# closed stage aktif hanya Paid / Completed.
CLOSED_STAGES = [
    "Paid / Completed",
    "Excluded / Closed",
]

SLA_BY_STAGE = {
    "Quotation / Draft": 7,
    "SO On Hold / Approval": 2,
    "SO Pending Packing": 3,
    "Partial Packing": 3,
    "Invoice Exists, Packing Slip Missing": 1,
    "Packed Not Invoiced": 1,
    "Partially Invoiced": 1,
    "Invoiced Waiting Payment": 999,
    "Invoice Past Due": 1,
    "Paid / Completed": 0,
    "Excluded / Closed": 0,
    "Needs Review": 1,
}


# ============================================================
# COLUMN MAPPING - SALES ORDER SUMMARY
# ============================================================

SO_CODE = "Code"
SO_STATUS = "Status"
SO_TYPE = "Type"
SO_CREATED = "Created"
SO_UPDATED = "Updated"
SO_TERMINATE_DATE = "Terminate Date"
SO_CONFIRM_DRAFT_DATE = "Confirm Draft Date"
SO_CONFIRM_ONHOLD_DATE = "Confirm On hold Date"
SO_ORDER_DATE = "Order Date"
SO_SITE = "Site Code"
SO_DIV = "Sales Div.Code"
SO_SALESMAN = "Salesman Code"
SO_CUSTOMER_CODE = "Customer Code"
SO_CUSTOMER_NAME = "Customer Name"
SO_ORDER_SOURCE = "Order Source"
SO_PAYMENT_METHOD = "Payment Method"
SO_REFERENCE = "Reference"
SO_LEGACY_CODE = "Legacy Code"
SO_DELIVERY_ADDRESS = "Delivery Address"
SO_INVOICE_ADDRESS = "Invoice Address"
SO_TOP = "ToP"
SO_REMAINING_LIMIT = "Remaining Limit"
SO_SUB_TOTAL = "Sub Total"
SO_TOTAL_PRICE = "Total Price"
SO_DISCOUNT_TOTAL = "Discount Total"
SO_DPP = "DPP"
SO_TAX = "Tax"
SO_NET_PRICE = "Net Price"
SO_NET_PRICE_DELIVERY = "Net Price Delivery"
SO_CANCEL_REASON = "Cancel Reason"
SO_CANCEL_BY_PACKING_BO = "Cancel by Packing BO"
SO_ON_HOLD_APPROVAL = "On Hold Approval"
SO_PROCESSED_DATE = "Processed Date (Export)"

SO_APPROVAL_DATE_COLS = [
    "Approved Date Limit",
    "Approved Date Pass Due",
    "Approved Date Price",
    "Approved Date Discount",
    "Approved Date Payment Method",
]

SO_APPROVAL_REASON_MAP = {
    "Approved Date Limit": "Credit Limit",
    "Approved Date Pass Due": "Pass Due",
    "Approved Date Price": "Price",
    "Approved Date Discount": "Discount",
    "Approved Date Payment Method": "Payment Method",
}


# ============================================================
# COLUMN MAPPING - PACKING SUMMARY
# ============================================================

PS_CODE = "Code"
PS_STATUS = "Status"
PS_TYPE = "Type"
PS_CREATED = "Created"
PS_UPDATED = "Updated"
PS_PACKING_LEGACY_CODE = "Packing Legacy Code"
PS_NOTE_GENERAL = "Note (General)"
PS_COMP_CODE = "Comp. Code"
PS_COMP_NAME = "Comp. Name"
PS_SITE = "Site Code"
PS_SITE_NAME = "Site Name"
PS_DIV = "Division Code"
PS_DIV_NAME = "Division Name"
PS_CUSTOMER_CODE = "Customer Code"
PS_CUSTOMER_NAME = "Customer Name"
PS_ORDER_DATE = "Order Date"
PS_PRINTED_DATE = "Printed Date"
PS_REFERENCE = "Reference"
PS_SO_CODE = "Sales Order Code"
PS_PURCHASE_RETURN_CODE = "Purchase Return Code"
PS_DPP = "DPP"
PS_NET_PRICE = "Net Price"
PS_CANCEL_REASON = "Cancel Reason"
PS_PROMO = "Promo"
PS_SALESMAN_VERSUNI = "Salesman Versuni"
PS_ORDER_SOURCE = "Order Source"
PS_PROCESSED_DATE = "Processed Date (Export)"


# ============================================================
# COLUMN MAPPING - INVOICE SUMMARY
# ============================================================

SI_CODE = "Code"
SI_STATUS = "Status"
SI_TYPE = "Type"
SI_CREATED = "Created"
SI_UPDATED = "Updated"
SI_SO_CODE = "Sales Order/Return Code"
SI_SO_DATE = "Sales Order Date"
SI_PACKING_SLIP_CODE = "Packing Slip"
SI_INVOICE_DATE = "Invoice Date"
SI_PRINTED_DATE = "Sales Invoice Printed Date"
SI_PAID_DATE = "Paid Date"
SI_DUE_DATE = "Due Date"
SI_SITE = "Site"
SI_DIV = "Sales Div."
SI_SALESMAN = "Salesman"
SI_CUSTOMER_CODE = "Customer Code"
SI_CUSTOMER_NAME = "Customer Name"
SI_QTY = "Qty"
SI_NET_PRICE = "Net Price"
SI_PAYMENT = "Payment"
SI_TOTAL_INVOICE_BALANCE = "Total Invoice Balance"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def print_shape(name: str, df: pl.DataFrame):
    print(f"{name:<48} {df.height:>12,} rows | {len(df.columns):>3} cols")


def existing_cols(df: pl.DataFrame, cols: list[str]) -> list[str]:
    return [col for col in cols if col in df.columns]


def require_columns(df: pl.DataFrame, required_columns: list[str], df_name: str):
    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        raise ValueError(
            f"Kolom wajib tidak ditemukan di {df_name}: {missing}\n"
            f"Kolom tersedia: {df.columns}"
        )


def ensure_column(df: pl.DataFrame, col_name: str, dtype=pl.Utf8, default=None) -> pl.DataFrame:
    if col_name in df.columns:
        return df

    return df.with_columns(
        pl.lit(default).cast(dtype).alias(col_name)
    )


def ensure_columns(df: pl.DataFrame, schema: dict) -> pl.DataFrame:
    for col_name, dtype_default in schema.items():
        dtype = dtype_default[0]
        default = dtype_default[1]
        df = ensure_column(df, col_name, dtype=dtype, default=default)

    return df


def apply_existing_exprs(df: pl.DataFrame, cols: list[str], expr_func):
    cols = existing_cols(df, cols)

    if not cols:
        return df

    return df.with_columns([
        expr_func(col)
        for col in cols
    ])


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
        .then(pl.lit(None))
        .otherwise(raw)
        .alias(col_name)
    )


def clean_text_expr(col_name: str, default_value=None):
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


def first_non_null_expr(col_name: str):
    return pl.col(col_name).drop_nulls().first()


def unique_list_expr(col_name: str):
    return pl.col(col_name).drop_nulls().cast(pl.Utf8).unique().sort()


def join_list(values, max_items=None):
    if values is None:
        return None

    try:
        values = list(values)
    except Exception:
        values = [values]

    clean_values = []

    for value in values:
        if value is None:
            continue

        text = str(value).strip()

        if text == "" or text.upper() in ["NONE", "NAN", "NULL"]:
            continue

        clean_values.append(text)

    clean_values = sorted(set(clean_values))

    if max_items is not None:
        clean_values = clean_values[:max_items]

    return " | ".join(clean_values) if clean_values else None


def max_col_date(df: pl.DataFrame, col_name: str):
    if col_name not in df.columns or df.height == 0:
        return None

    value = df.select(pl.col(col_name).max()).item()

    if isinstance(value, dt.datetime):
        return value.date()

    return value


def sum_col(df: pl.DataFrame, col_name: str):
    if col_name not in df.columns or df.height == 0:
        return 0

    value = df.select(pl.col(col_name).sum()).item()

    return 0 if value is None else value


def count_distinct_col(df: pl.DataFrame, col_name: str):
    if col_name not in df.columns or df.height == 0:
        return 0

    value = df.select(pl.col(col_name).n_unique()).item()

    return 0 if value is None else value


def day_diff_expr(end_date_expr, start_date_expr):
    return (end_date_expr - start_date_expr).dt.total_days()


def safe_divide_expr(numerator_expr, denominator_expr):
    return (
        pl.when(denominator_expr != 0)
        .then(numerator_expr / denominator_expr)
        .otherwise(None)
    )


def clean_bq_column_name(col):
    col = str(col).strip().lower()
    col = re.sub(r"[^a-zA-Z0-9_]", "_", col)
    col = re.sub(r"_+", "_", col).strip("_")

    if col == "":
        col = "column"

    if re.match(r"^[0-9]", col):
        col = f"col_{col}"

    return col


def make_bq_safe_columns(df: pl.DataFrame) -> pl.DataFrame:
    new_cols = []
    seen = {}

    for col in df.columns:
        base = clean_bq_column_name(col)

        if base not in seen:
            seen[base] = 1
            new_cols.append(base)
        else:
            seen[base] += 1
            new_cols.append(f"{base}_{seen[base]}")

    rename_map = {
        old: new
        for old, new in zip(df.columns, new_cols)
        if old != new
    }

    return df.rename(rename_map)


def ensure_bigquery_dataset(client, project_id, dataset_id, location=None):
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")

    try:
        client.get_dataset(dataset_ref)
        print(f"[OK] Dataset exists: {project_id}.{dataset_id}")
    except NotFound:
        if location:
            dataset_ref.location = location

        client.create_dataset(dataset_ref)
        print(f"[OK] Dataset created: {project_id}.{dataset_id}")


def load_polars_to_bigquery(
    client,
    df: pl.DataFrame,
    table_id: str,
    write_disposition="WRITE_TRUNCATE"
):
    df_bq = make_bq_safe_columns(df)

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        temp_parquet_path = tmp.name

    try:
        df_bq.write_parquet(temp_parquet_path)

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=write_disposition,
        )

        with open(temp_parquet_path, "rb") as file_obj:
            job = client.load_table_from_file(
                file_obj,
                table_id,
                job_config=job_config,
                location=BQ_LOCATION,
            )

        job.result()

        table = client.get_table(table_id)
        print(f"[OK] Loaded {table.num_rows:,} rows to {table_id}")

    finally:
        if os.path.exists(temp_parquet_path):
            os.remove(temp_parquet_path)


# ============================================================
# VALIDATE MINIMUM COLUMNS
# ============================================================

print("\n[2/14] Validasi kolom minimum...")

SO_REQUIRED = [
    SO_CODE,
    SO_STATUS,
    SO_ORDER_DATE,
    SO_SITE,
    SO_DIV,
    SO_SALESMAN,
    SO_CUSTOMER_CODE,
    SO_CUSTOMER_NAME,
    SO_NET_PRICE,
    SO_NET_PRICE_DELIVERY,
]

PS_REQUIRED = [
    PS_CODE,
    PS_STATUS,
    PS_TYPE,
    PS_SITE,
    PS_DIV,
    PS_CUSTOMER_CODE,
    PS_CUSTOMER_NAME,
    PS_PRINTED_DATE,
    PS_SO_CODE,
    PS_NET_PRICE,
]

SI_REQUIRED = [
    SI_CODE,
    SI_SO_CODE,
    SI_INVOICE_DATE,
    SI_DUE_DATE,
    SI_PAID_DATE,
    SI_NET_PRICE,
]

require_columns(so, SO_REQUIRED, "SO Summary")
require_columns(ps, PS_REQUIRED, "Packing Summary")
require_columns(si, SI_REQUIRED, "Invoice Summary")

print("Validasi kolom minimum selesai.")


# ============================================================
# ADD OPTIONAL MISSING COLUMNS
# ============================================================

print("\n[3/14] Menambahkan optional missing columns...")

so_optional_schema = {
    SO_TYPE: (pl.Utf8, None),
    SO_CREATED: (pl.Date, None),
    SO_UPDATED: (pl.Date, None),
    SO_TERMINATE_DATE: (pl.Date, None),
    SO_CONFIRM_DRAFT_DATE: (pl.Date, None),
    SO_CONFIRM_ONHOLD_DATE: (pl.Date, None),
    SO_ORDER_SOURCE: (pl.Utf8, None),
    SO_PAYMENT_METHOD: (pl.Utf8, None),
    SO_REFERENCE: (pl.Utf8, None),
    SO_LEGACY_CODE: (pl.Utf8, None),
    SO_DELIVERY_ADDRESS: (pl.Utf8, None),
    SO_INVOICE_ADDRESS: (pl.Utf8, None),
    SO_TOP: (pl.Utf8, None),
    SO_REMAINING_LIMIT: (pl.Float64, 0),
    SO_SUB_TOTAL: (pl.Float64, 0),
    SO_TOTAL_PRICE: (pl.Float64, 0),
    SO_DISCOUNT_TOTAL: (pl.Float64, 0),
    SO_DPP: (pl.Float64, 0),
    SO_TAX: (pl.Float64, 0),
    SO_CANCEL_REASON: (pl.Utf8, None),
    SO_CANCEL_BY_PACKING_BO: (pl.Utf8, None),
    SO_ON_HOLD_APPROVAL: (pl.Utf8, None),
    SO_PROCESSED_DATE: (pl.Date, None),
}

for col in SO_APPROVAL_DATE_COLS:
    so_optional_schema[col] = (pl.Date, None)

ps_optional_schema = {
    PS_CREATED: (pl.Date, None),
    PS_UPDATED: (pl.Date, None),
    PS_PACKING_LEGACY_CODE: (pl.Utf8, None),
    PS_NOTE_GENERAL: (pl.Utf8, None),
    PS_COMP_CODE: (pl.Utf8, None),
    PS_COMP_NAME: (pl.Utf8, None),
    PS_SITE_NAME: (pl.Utf8, None),
    PS_DIV_NAME: (pl.Utf8, None),
    PS_ORDER_DATE: (pl.Date, None),
    PS_REFERENCE: (pl.Utf8, None),
    PS_PURCHASE_RETURN_CODE: (pl.Utf8, None),
    PS_DPP: (pl.Float64, 0),
    PS_CANCEL_REASON: (pl.Utf8, None),
    PS_PROMO: (pl.Utf8, None),
    PS_SALESMAN_VERSUNI: (pl.Utf8, None),
    PS_ORDER_SOURCE: (pl.Utf8, None),
    PS_PROCESSED_DATE: (pl.Date, None),
}

si_optional_schema = {
    SI_STATUS: (pl.Utf8, None),
    SI_TYPE: (pl.Utf8, None),
    SI_CREATED: (pl.Date, None),
    SI_UPDATED: (pl.Date, None),
    SI_SO_DATE: (pl.Date, None),
    SI_PACKING_SLIP_CODE: (pl.Utf8, None),
    SI_PRINTED_DATE: (pl.Date, None),
    SI_SITE: (pl.Utf8, None),
    SI_DIV: (pl.Utf8, None),
    SI_SALESMAN: (pl.Utf8, None),
    SI_CUSTOMER_CODE: (pl.Utf8, None),
    SI_CUSTOMER_NAME: (pl.Utf8, None),
    SI_QTY: (pl.Float64, 0),
    SI_PAYMENT: (pl.Float64, 0),
    SI_TOTAL_INVOICE_BALANCE: (pl.Float64, 0),
}

so = ensure_columns(so, so_optional_schema)
ps = ensure_columns(ps, ps_optional_schema)
si = ensure_columns(si, si_optional_schema)

print("Optional columns selesai.")


# ============================================================
# BASIC CLEANING
# ============================================================

print("\n[4/14] Cleaning data...")

date_cols_so = [
    SO_CREATED,
    SO_UPDATED,
    SO_TERMINATE_DATE,
    SO_CONFIRM_DRAFT_DATE,
    SO_CONFIRM_ONHOLD_DATE,
    SO_ORDER_DATE,
    SO_PROCESSED_DATE,
] + SO_APPROVAL_DATE_COLS

date_cols_ps = [
    PS_CREATED,
    PS_UPDATED,
    PS_ORDER_DATE,
    PS_PRINTED_DATE,
    PS_PROCESSED_DATE,
]

date_cols_si = [
    SI_CREATED,
    SI_UPDATED,
    SI_SO_DATE,
    SI_INVOICE_DATE,
    SI_PRINTED_DATE,
    SI_PAID_DATE,
    SI_DUE_DATE,
]

num_cols_so = [
    SO_REMAINING_LIMIT,
    SO_SUB_TOTAL,
    SO_TOTAL_PRICE,
    SO_DISCOUNT_TOTAL,
    SO_DPP,
    SO_TAX,
    SO_NET_PRICE,
    SO_NET_PRICE_DELIVERY,
]

num_cols_ps = [
    PS_DPP,
    PS_NET_PRICE,
]

num_cols_si = [
    SI_QTY,
    SI_NET_PRICE,
    SI_PAYMENT,
    SI_TOTAL_INVOICE_BALANCE,
]

text_cols_so = [
    SO_CODE,
    SO_STATUS,
    SO_TYPE,
    SO_SITE,
    SO_DIV,
    SO_SALESMAN,
    SO_CUSTOMER_CODE,
    SO_CUSTOMER_NAME,
    SO_ORDER_SOURCE,
    SO_PAYMENT_METHOD,
    SO_REFERENCE,
    SO_LEGACY_CODE,
    SO_DELIVERY_ADDRESS,
    SO_INVOICE_ADDRESS,
    SO_TOP,
    SO_CANCEL_REASON,
    SO_CANCEL_BY_PACKING_BO,
    SO_ON_HOLD_APPROVAL,
]

text_cols_ps = [
    PS_CODE,
    PS_STATUS,
    PS_TYPE,
    PS_PACKING_LEGACY_CODE,
    PS_NOTE_GENERAL,
    PS_COMP_CODE,
    PS_COMP_NAME,
    PS_SITE,
    PS_SITE_NAME,
    PS_DIV,
    PS_DIV_NAME,
    PS_CUSTOMER_CODE,
    PS_CUSTOMER_NAME,
    PS_REFERENCE,
    PS_SO_CODE,
    PS_PURCHASE_RETURN_CODE,
    PS_CANCEL_REASON,
    PS_PROMO,
    PS_SALESMAN_VERSUNI,
    PS_ORDER_SOURCE,
]

text_cols_si = [
    SI_CODE,
    SI_STATUS,
    SI_TYPE,
    SI_SO_CODE,
    SI_PACKING_SLIP_CODE,
    SI_SITE,
    SI_DIV,
    SI_SALESMAN,
    SI_CUSTOMER_CODE,
    SI_CUSTOMER_NAME,
]

so = apply_existing_exprs(so, date_cols_so, normalize_date_expr)
ps = apply_existing_exprs(ps, date_cols_ps, normalize_date_expr)
si = apply_existing_exprs(si, date_cols_si, normalize_date_expr)

so = apply_existing_exprs(so, num_cols_so, numeric_expr)
ps = apply_existing_exprs(ps, num_cols_ps, numeric_expr)
si = apply_existing_exprs(si, num_cols_si, numeric_expr)

so = apply_existing_exprs(so, text_cols_so, clean_text_expr)
ps = apply_existing_exprs(ps, text_cols_ps, clean_text_expr)
si = apply_existing_exprs(si, text_cols_si, clean_text_expr)

so = so.with_columns([
    clean_code_expr(SO_CODE).alias("_so_code")
])

ps = ps.with_columns([
    clean_code_expr(PS_SO_CODE).alias("_so_code"),
    clean_code_expr(PS_CODE).alias("_packing_slip_code"),
])

si = si.with_columns([
    clean_code_expr(SI_SO_CODE).alias("_so_code"),
    clean_code_expr(SI_CODE).alias("_invoice_code"),
    clean_code_expr(SI_PACKING_SLIP_CODE).alias("_packing_slip_code"),
])


# ============================================================
# EXCLUDE RETURN DOCUMENTS
# ============================================================

if EXCLUDE_RETURN_DOCS:
    so = so.filter(
        ~pl.col(SO_TYPE)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.to_uppercase()
        .str.contains("RETURN")
    )

    si = si.filter(
        ~pl.col(SI_TYPE)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.to_uppercase()
        .str.contains("RETURN")
    )

    ps = ps.filter(
        ~pl.col(PS_TYPE)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.to_uppercase()
        .str.contains("RETURN")
    )


# ============================================================
# EXCLUDE SO CANCELLED / CLOSED / DECLINED
# ============================================================

so = so.filter(pl.col("_so_code").is_not_null())

so = so.with_columns([
    (
        pl.col(SO_STATUS)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.strip_chars()
        .str.to_uppercase()
        .alias("_so_status_upper")
    )
])

so = so.with_columns([
    pl.col("_so_status_upper").str.contains("CANCEL").alias("_is_cancelled_so"),
    pl.col("_so_status_upper").str.contains("CLOS").alias("_is_closed_so"),
    pl.col("_so_status_upper").str.contains("DECLIN").alias("_is_declined_so"),
])

excluded_so_codes = pl.Series("_so_code", [], dtype=pl.Utf8)
so_excluded = so.filter(pl.lit(False))

if EXCLUDE_CLOSED_CANCELLED_DECLINED_SO:
    so_excluded = so.filter(
        pl.col("_is_cancelled_so")
        | pl.col("_is_closed_so")
        | pl.col("_is_declined_so")
    )

    excluded_so_codes = so_excluded.select("_so_code").unique().to_series()

    print("\nSO Cancelled / Closed / Declined yang di-exclude dari Business Flow:")
    if so_excluded.height > 0:
        print(
            so_excluded
            .group_by(SO_STATUS)
            .agg([
                pl.col("_so_code").n_unique().alias("so_count"),
                pl.col(SO_NET_PRICE).sum().alias("excluded_so_value"),
            ])
            .sort("excluded_so_value", descending=True)
        )
    else:
        print("Tidak ada SO Cancelled / Closed / Declined yang di-exclude.")

    so = so.filter(
        ~(
            pl.col("_is_cancelled_so")
            | pl.col("_is_closed_so")
            | pl.col("_is_declined_so")
        )
    )

print_shape("SO after cleaning and exclude closed/cancelled/declined", so)
print_shape("Packing Slip after cleaning", ps)
print_shape("Invoice after cleaning", si)


# ============================================================
# AS OF DATE
# ============================================================

print("\n[5/14] Menentukan AS_OF_DATE...")

if REPORT_AS_OF_DATE_OVERRIDE is not None:
    AS_OF_DATE = REPORT_AS_OF_DATE_OVERRIDE

    if isinstance(AS_OF_DATE, dt.datetime):
        AS_OF_DATE = AS_OF_DATE.date()

    print("[INFO] AS_OF_DATE memakai manual override.")
else:
    date_candidates = []

    for df_, cols_ in [
        (so, [SO_PROCESSED_DATE, SO_UPDATED, SO_ORDER_DATE]),
        (ps, [PS_PROCESSED_DATE, PS_UPDATED, PS_PRINTED_DATE]),

        # PENTING:
        # SI_DUE_DATE sengaja TIDAK dipakai untuk AS_OF_DATE,
        # karena Due Date bisa tanggal masa depan dan membuat aging salah.
        (si, [SI_UPDATED, SI_INVOICE_DATE, SI_PRINTED_DATE, SI_PAID_DATE]),
    ]:
        for col in cols_:
            max_value = max_col_date(df_, col)

            if max_value is not None:
                date_candidates.append(max_value)

    if len(date_candidates) == 0:
        AS_OF_DATE = dt.date.today()
    else:
        AS_OF_DATE = max(date_candidates)

        if isinstance(AS_OF_DATE, dt.datetime):
            AS_OF_DATE = AS_OF_DATE.date()

print(f"AS_OF_DATE: {AS_OF_DATE}")


# ============================================================
# BUILD SALES ORDER DOCUMENT LEVEL
# ============================================================

print("\n[6/14] Membuat Sales Order document level...")

approval_date_cols_existing = existing_cols(so, SO_APPROVAL_DATE_COLS)

if approval_date_cols_existing:
    so = so.with_columns([
        pl.min_horizontal([
            pl.col(col)
            for col in approval_date_cols_existing
        ]).alias("_approved_date")
    ])

    def approval_reason_mapper(row):
        reasons = []

        for col, label in SO_APPROVAL_REASON_MAP.items():
            if col in row and row[col] is not None:
                reasons.append(label)

        return ", ".join(reasons) if reasons else None

    so = so.with_columns([
        pl.struct(approval_date_cols_existing)
        .map_elements(approval_reason_mapper, return_dtype=pl.Utf8)
        .alias("_approval_reason_line")
    ])

else:
    so = so.with_columns([
        pl.lit(None).cast(pl.Date).alias("_approved_date"),
        pl.lit(None).cast(pl.Utf8).alias("_approval_reason_line"),
    ])

so_doc = (
    so
    .group_by("_so_code")
    .agg([
        first_non_null_expr(SO_STATUS).alias("so_status"),
        first_non_null_expr(SO_TYPE).alias("so_type"),

        pl.col(SO_CREATED).min().alias("so_created_date"),
        pl.col(SO_UPDATED).max().alias("so_updated_date"),
        pl.col(SO_ORDER_DATE).min().alias("so_order_date"),
        pl.col(SO_TERMINATE_DATE).max().alias("so_terminate_date"),
        pl.col(SO_CONFIRM_DRAFT_DATE).min().alias("confirm_draft_date"),
        pl.col(SO_CONFIRM_ONHOLD_DATE).min().alias("confirm_onhold_date"),
        pl.col("_approved_date").min().alias("approved_date"),

        first_non_null_expr(SO_SITE).alias("site"),
        first_non_null_expr(SO_DIV).alias("sales_division"),
        first_non_null_expr(SO_SALESMAN).alias("salesman"),
        first_non_null_expr(SO_CUSTOMER_CODE).alias("customer_code"),
        first_non_null_expr(SO_CUSTOMER_NAME).alias("customer_name"),

        first_non_null_expr(SO_ORDER_SOURCE).alias("order_source"),
        first_non_null_expr(SO_PAYMENT_METHOD).alias("payment_method"),
        first_non_null_expr(SO_REFERENCE).alias("reference"),
        first_non_null_expr(SO_LEGACY_CODE).alias("legacy_code"),
        first_non_null_expr(SO_DELIVERY_ADDRESS).alias("delivery_address"),
        first_non_null_expr(SO_INVOICE_ADDRESS).alias("invoice_address"),
        first_non_null_expr(SO_TOP).alias("top"),

        pl.col(SO_REMAINING_LIMIT).sum().alias("remaining_limit"),
        pl.col(SO_SUB_TOTAL).sum().alias("so_sub_total"),
        pl.col(SO_TOTAL_PRICE).sum().alias("so_total_price"),
        pl.col(SO_DISCOUNT_TOTAL).sum().alias("so_discount_total"),
        pl.col(SO_DPP).sum().alias("so_dpp"),
        pl.col(SO_TAX).sum().alias("so_tax"),

        pl.col(SO_NET_PRICE).sum().alias("so_value"),
        pl.col(SO_NET_PRICE_DELIVERY).sum().alias("so_packing_value_from_so"),

        pl.len().alias("so_line_count"),

        unique_list_expr(SO_CANCEL_REASON).alias("cancel_reason_list"),
        unique_list_expr(SO_CANCEL_BY_PACKING_BO).alias("cancel_by_packing_bo_list"),
        unique_list_expr(SO_ON_HOLD_APPROVAL).alias("on_hold_approval_list"),
        unique_list_expr("_approval_reason_line").alias("approval_reason_list"),
    ])
    .rename({"_so_code": "so_code"})
    .with_columns([
        pl.col("cancel_reason_list")
        .map_elements(lambda x: join_list(x, max_items=3), return_dtype=pl.Utf8)
        .alias("cancel_reason"),

        pl.col("cancel_by_packing_bo_list")
        .map_elements(lambda x: join_list(x, max_items=3), return_dtype=pl.Utf8)
        .alias("cancel_by_packing_bo"),

        pl.col("on_hold_approval_list")
        .map_elements(lambda x: join_list(x, max_items=5), return_dtype=pl.Utf8)
        .alias("on_hold_approval"),

        pl.col("approval_reason_list")
        .map_elements(lambda x: join_list(x, max_items=5), return_dtype=pl.Utf8)
        .alias("approval_reason"),
    ])
    .drop([
        "cancel_reason_list",
        "cancel_by_packing_bo_list",
        "on_hold_approval_list",
        "approval_reason_list",
    ])
)

print_shape("SO Document", so_doc)


# ============================================================
# BUILD PACKING SLIP DOCUMENT LEVEL
# ============================================================

print("\n[7/14] Membuat Packing Slip document level...")

flow_so_codes = so_doc.select("so_code").to_series()

ps_with_so_code = ps.filter(pl.col("_so_code").is_not_null())

ps_valid = ps_with_so_code.filter(
    pl.col("_so_code").is_in(flow_so_codes)
)

packing_slip_doc = (
    ps_valid
    .group_by("_so_code")
    .agg([
        pl.col("_packing_slip_code").n_unique().alias("packing_slip_count"),
        first_non_null_expr(PS_STATUS).alias("packing_slip_status_sample"),

        pl.col(PS_PRINTED_DATE).min().alias("first_packing_slip_date"),
        pl.col(PS_PRINTED_DATE).max().alias("last_packing_slip_date"),

        pl.lit(None).cast(pl.Date).alias("first_loaded_date"),
        pl.lit(None).cast(pl.Date).alias("last_loaded_date"),

        pl.col(PS_ORDER_DATE).min().alias("first_packing_order_date"),
        pl.col(PS_ORDER_DATE).max().alias("last_packing_order_date"),

        pl.col(PS_NET_PRICE).sum().alias("packing_slip_value"),
        pl.col(PS_DPP).sum().alias("packing_slip_dpp"),

        first_non_null_expr(PS_SITE).alias("packing_site"),
        first_non_null_expr(PS_SITE_NAME).alias("packing_site_name"),
        first_non_null_expr(PS_DIV).alias("packing_division_code"),
        first_non_null_expr(PS_DIV_NAME).alias("packing_division_name"),
        first_non_null_expr(PS_CUSTOMER_CODE).alias("packing_customer_code"),
        first_non_null_expr(PS_CUSTOMER_NAME).alias("packing_customer_name"),

        unique_list_expr(PS_TYPE).alias("packing_type_list"),
        unique_list_expr(PS_REFERENCE).alias("packing_reference_list"),
        unique_list_expr(PS_ORDER_SOURCE).alias("packing_order_source_list"),
        unique_list_expr(PS_PURCHASE_RETURN_CODE).alias("purchase_return_code_list"),
        unique_list_expr(PS_CANCEL_REASON).alias("packing_cancel_reason_list"),
    ])
    .rename({"_so_code": "so_code"})
    .with_columns([
        pl.col("packing_type_list")
        .map_elements(lambda x: join_list(x, max_items=5), return_dtype=pl.Utf8)
        .alias("packing_type"),

        pl.col("packing_reference_list")
        .map_elements(lambda x: join_list(x, max_items=5), return_dtype=pl.Utf8)
        .alias("packing_reference"),

        pl.col("packing_order_source_list")
        .map_elements(lambda x: join_list(x, max_items=5), return_dtype=pl.Utf8)
        .alias("packing_order_source"),

        pl.col("purchase_return_code_list")
        .map_elements(lambda x: join_list(x, max_items=5), return_dtype=pl.Utf8)
        .alias("purchase_return_code"),

        pl.col("packing_cancel_reason_list")
        .map_elements(lambda x: join_list(x, max_items=5), return_dtype=pl.Utf8)
        .alias("packing_cancel_reason"),
    ])
    .drop([
        "packing_type_list",
        "packing_reference_list",
        "packing_order_source_list",
        "purchase_return_code_list",
        "packing_cancel_reason_list",
    ])
)

print_shape("Packing Slip by SO", packing_slip_doc)


# ============================================================
# BUILD SALES INVOICE DOCUMENT LEVEL
# ============================================================

print("\n[8/14] Membuat Sales Invoice document level...")

si_with_so_code = si.filter(pl.col("_so_code").is_not_null())

si_valid = (
    si_with_so_code
    .filter(pl.col("_so_code").is_in(flow_so_codes))
    .with_columns([
        pl.when(pl.col(SI_PAYMENT).abs() > 0)
        .then(pl.col(SI_PAYMENT).abs())
        .when(pl.col(SI_PAID_DATE).is_not_null())
        .then(pl.col(SI_NET_PRICE))
        .otherwise(0)
        .alias("_paid_value_line"),

        pl.when(pl.col(SI_TOTAL_INVOICE_BALANCE) > 0)
        .then(pl.col(SI_TOTAL_INVOICE_BALANCE))
        .when(pl.col(SI_PAID_DATE).is_null())
        .then(pl.col(SI_NET_PRICE))
        .otherwise(0)
        .alias("_unpaid_value_line"),
    ])
    .with_columns([
        pl.when(
            (pl.col("_unpaid_value_line") > 0)
            & pl.col(SI_DUE_DATE).is_not_null()
            & (pl.col(SI_DUE_DATE) < pl.lit(AS_OF_DATE).cast(pl.Date))
        )
        .then(pl.col("_unpaid_value_line"))
        .otherwise(0)
        .alias("_overdue_value_line"),

        pl.when(pl.col("_unpaid_value_line") > 0)
        .then(pl.col(SI_DUE_DATE))
        .otherwise(None)
        .alias("_unpaid_due_date"),
    ])
)

si_doc = (
    si_valid
    .group_by("_so_code")
    .agg([
        pl.col("_invoice_code").n_unique().alias("invoice_count"),
        first_non_null_expr(SI_STATUS).alias("invoice_status_sample"),
        unique_list_expr(SI_STATUS).alias("invoice_status_list_raw"),
        pl.col("_packing_slip_code").n_unique().alias("linked_packing_slip_count"),

        pl.col(SI_INVOICE_DATE).min().alias("first_invoice_date"),
        pl.col(SI_INVOICE_DATE).max().alias("last_invoice_date"),

        pl.col(SI_PRINTED_DATE).min().alias("first_printed_date"),
        pl.col(SI_PRINTED_DATE).max().alias("last_printed_date"),

        pl.col(SI_DUE_DATE).min().alias("first_due_date"),
        pl.col(SI_DUE_DATE).max().alias("last_due_date"),
        pl.col("_unpaid_due_date").min().alias("next_due_date"),

        pl.col(SI_PAID_DATE).min().alias("first_paid_date"),
        pl.col(SI_PAID_DATE).max().alias("last_paid_date"),

        pl.col(SI_QTY).sum().alias("invoice_qty"),
        pl.col(SI_NET_PRICE).sum().alias("invoice_value"),

        pl.col("_paid_value_line").sum().alias("paid_value"),
        pl.col("_unpaid_value_line").sum().alias("unpaid_value"),
        pl.col("_overdue_value_line").sum().alias("overdue_value"),
    ])
    .rename({"_so_code": "so_code"})
    .with_columns([
        pl.col("invoice_status_list_raw")
        .map_elements(lambda x: join_list(x, max_items=10), return_dtype=pl.Utf8)
        .alias("invoice_status_list")
    ])
    .drop("invoice_status_list_raw")
)

print_shape("Invoice by SO", si_doc)


# ============================================================
# MERGE FLOW MASTER
# ============================================================

print("\n[9/14] Merge flow master...")

flow = (
    so_doc
    .join(packing_slip_doc, on="so_code", how="left")
    .join(si_doc, on="so_code", how="left")
)

numeric_fill_zero = [
    "packing_slip_count",
    "packing_slip_value",
    "packing_slip_dpp",
    "invoice_count",
    "linked_packing_slip_count",
    "invoice_qty",
    "invoice_value",
    "paid_value",
    "unpaid_value",
    "overdue_value",
]

flow = flow.with_columns([
    pl.col(col).fill_null(0).alias(col)
    for col in numeric_fill_zero
    if col in flow.columns
])

flow = flow.with_columns([
    pl.lit(AS_OF_DATE).cast(pl.Date).alias("as_of_date")
])


# ============================================================
# STATUS CLASSIFICATION
# ============================================================

print("\n[10/14] Membuat status classification...")

status_upper = (
    pl.col("so_status")
    .cast(pl.Utf8, strict=False)
    .fill_null("")
    .str.to_uppercase()
)

invoice_status_upper = (
    pl.coalesce([
        pl.col("invoice_status_list").cast(pl.Utf8, strict=False),
        pl.col("invoice_status_sample").cast(pl.Utf8, strict=False),
        pl.lit("")
    ])
    .fill_null("")
    .str.to_uppercase()
)

flow = flow.with_columns([
    status_upper.str.contains(QUOTATION_STATUS_KEYWORD).alias("is_quotation_draft"),
    status_upper.str.contains("CANCEL").alias("is_cancelled"),
    status_upper.str.contains("CLOS").alias("is_closed"),
    status_upper.str.contains("DECLIN").alias("is_declined"),
    status_upper.str.contains("ON HOLD|HOLD").alias("is_onhold"),

    # Tambahan status completion
    status_upper.str.contains("DONE").alias("is_so_done"),
    status_upper.str.contains("DONE\\s*[-/]?\\s*PARTIAL").alias("is_so_done_partial"),
    invoice_status_upper.str.contains("DONE").alias("is_invoice_done"),
])

flow = flow.with_columns([
    (
        ~pl.col("is_quotation_draft")
        & ~pl.col("is_cancelled")
        & ~pl.col("is_closed")
        & ~pl.col("is_declined")
    ).alias("is_active_so")
])

flow = flow.with_columns([
    pl.when(pl.col("is_quotation_draft"))
    .then(pl.col("so_value"))
    .otherwise(0)
    .alias("quotation_value"),

    pl.when(pl.col("is_active_so"))
    .then(pl.col("so_value"))
    .otherwise(0)
    .alias("sales_order_value"),

    pl.when(pl.col("is_cancelled"))
    .then(pl.col("so_value"))
    .otherwise(0)
    .alias("cancelled_value"),

    pl.when(pl.col("is_closed"))
    .then(pl.col("so_value"))
    .otherwise(0)
    .alias("closed_value"),

    pl.when(pl.col("is_declined"))
    .then(pl.col("so_value"))
    .otherwise(0)
    .alias("declined_value"),
])

flow = flow.with_columns([
    (pl.col("packing_slip_value").abs() > 0).alias("has_packing_slip"),
    (pl.col("invoice_value").abs() > 0).alias("has_invoice"),
])

flow = flow.with_columns([
    pl.when(pl.col("sales_order_value") > 0)
    .then(pl.col("packing_slip_value") >= pl.col("sales_order_value") * PACKING_TOLERANCE)
    .otherwise(False)
    .alias("is_fully_packed"),

    # Revisi:
    # Jika SO sudah Done / Done-Partial dan Invoice status Done,
    # proses invoice dianggap selesai secara sistem, walaupun value tidak full.
    pl.when(
        pl.col("has_invoice")
        & pl.col("is_invoice_done")
        & (
            pl.col("is_so_done")
            | pl.col("is_so_done_partial")
        )
    )
    .then(True)
    .when(pl.col("packing_slip_value") > 0)
    .then(pl.col("invoice_value") >= pl.col("packing_slip_value") * INVOICE_TOLERANCE)
    .otherwise(False)
    .alias("is_fully_invoiced"),

    pl.when(pl.col("invoice_value") > 0)
    .then(pl.col("paid_value") >= pl.col("invoice_value") * PAYMENT_TOLERANCE)
    .otherwise(False)
    .alias("is_fully_paid"),
])

flow = flow.with_columns([
    (
        pl.when(pl.col("is_cancelled") | pl.col("is_closed") | pl.col("is_declined"))
        .then(pl.lit("Excluded / Closed"))

        .when(pl.col("is_quotation_draft"))
        .then(pl.lit("Quotation / Draft"))

        .when(pl.col("is_onhold"))
        .then(pl.lit("SO On Hold / Approval"))

        # ====================================================
        # KHUSUS: SO Done / Done-Partial + Invoice Done
        # Flow langsung masuk ke tahap payment.
        # ====================================================
        .when(
            pl.col("is_active_so")
            & pl.col("has_invoice")
            & pl.col("is_invoice_done")
            & (
                pl.col("is_so_done")
                | pl.col("is_so_done_partial")
            )
            & pl.col("is_fully_paid")
        )
        .then(pl.lit("Paid / Completed"))

        .when(
            pl.col("is_active_so")
            & pl.col("has_invoice")
            & pl.col("is_invoice_done")
            & (
                pl.col("is_so_done")
                | pl.col("is_so_done_partial")
            )
            & (~pl.col("is_fully_paid"))
            & (pl.col("next_due_date") < pl.col("as_of_date"))
        )
        .then(pl.lit("Invoice Past Due"))

        .when(
            pl.col("is_active_so")
            & pl.col("has_invoice")
            & pl.col("is_invoice_done")
            & (
                pl.col("is_so_done")
                | pl.col("is_so_done_partial")
            )
            & (~pl.col("is_fully_paid"))
        )
        .then(pl.lit("Invoiced Waiting Payment"))

        .when(pl.col("is_active_so") & (~pl.col("has_packing_slip")) & pl.col("has_invoice"))
        .then(pl.lit("Invoice Exists, Packing Slip Missing"))

        .when(pl.col("is_active_so") & (~pl.col("has_packing_slip")) & (~pl.col("has_invoice")))
        .then(pl.lit("SO Pending Packing"))

        .when(pl.col("is_active_so") & pl.col("has_packing_slip") & (~pl.col("is_fully_packed")))
        .then(pl.lit("Partial Packing"))

        .when(pl.col("is_active_so") & pl.col("has_packing_slip") & (~pl.col("has_invoice")))
        .then(pl.lit("Packed Not Invoiced"))

        .when(pl.col("is_active_so") & pl.col("has_packing_slip") & pl.col("has_invoice") & (~pl.col("is_fully_invoiced")))
        .then(pl.lit("Partially Invoiced"))

        .when(pl.col("is_active_so") & pl.col("has_invoice") & pl.col("is_fully_paid"))
        .then(pl.lit("Paid / Completed"))

        .when(
            pl.col("is_active_so")
            & pl.col("has_invoice")
            & (~pl.col("is_fully_paid"))
            & (pl.col("next_due_date") < pl.col("as_of_date"))
        )
        .then(pl.lit("Invoice Past Due"))

        .when(pl.col("is_active_so") & pl.col("has_invoice") & (~pl.col("is_fully_paid")))
        .then(pl.lit("Invoiced Waiting Payment"))

        .otherwise(pl.lit("Needs Review"))
        .alias("current_stage")
    )
])

flow = flow.with_columns([
    (
        pl.when(pl.col("current_stage") == "Quotation / Draft")
        .then(pl.lit("Quotation Follow Up"))

        .when(pl.col("current_stage") == "SO On Hold / Approval")
        .then(pl.lit("Approval / Credit Control"))

        .when(pl.col("current_stage").is_in(["SO Pending Packing", "Partial Packing"]))
        .then(pl.lit("SO to Packing"))

        .when(pl.col("current_stage") == "Invoice Exists, Packing Slip Missing")
        .then(pl.lit("Data Mapping / Missing Packing Slip"))

        .when(pl.col("current_stage").is_in(["Packed Not Invoiced", "Partially Invoiced"]))
        .then(pl.lit("Packing to Invoice"))

        .when(pl.col("current_stage").is_in(["Invoice Past Due", "Invoiced Waiting Payment"]))
        .then(pl.lit("Invoice to Payment"))

        .when(pl.col("current_stage") == "Paid / Completed")
        .then(pl.lit("Completed"))

        .when(pl.col("current_stage") == "Excluded / Closed")
        .then(pl.lit("Closed"))

        .otherwise(pl.lit("Needs Review"))
        .alias("bottleneck_stage")
    )
])


# ============================================================
# STUCK VALUE
# ============================================================

flow = flow.with_columns([
    (pl.col("sales_order_value") - pl.col("packing_slip_value"))
    .clip(lower_bound=0)
    .alias("packing_gap_value"),

    (pl.col("packing_slip_value") - pl.col("invoice_value"))
    .clip(lower_bound=0)
    .alias("invoice_gap_value"),

    (pl.col("invoice_value") - pl.col("paid_value"))
    .clip(lower_bound=0)
    .alias("payment_gap_value"),
])

flow = flow.with_columns([
    (
        pl.when(pl.col("current_stage") == "Quotation / Draft")
        .then(pl.col("quotation_value"))

        .when(pl.col("current_stage") == "SO On Hold / Approval")
        .then(pl.col("sales_order_value"))

        .when(pl.col("current_stage").is_in([
            "SO Pending Packing",
            "Partial Packing",
            "Invoice Exists, Packing Slip Missing",
        ]))
        .then(pl.col("packing_gap_value"))

        .when(pl.col("current_stage").is_in([
            "Packed Not Invoiced",
            "Partially Invoiced",
        ]))
        .then(pl.col("invoice_gap_value"))

        .when(pl.col("current_stage").is_in([
            "Invoice Past Due",
            "Invoiced Waiting Payment",
        ]))
        .then(pl.col("payment_gap_value"))

        .otherwise(0)
        .fill_null(0)
        .clip(lower_bound=0)
        .alias("stuck_value")
    )
])


# ============================================================
# LEAD TIME & AGING
# ============================================================

flow = flow.with_columns([
    (
        pl.when(pl.col("current_stage") == "Quotation / Draft")
        .then(pl.coalesce([
            pl.col("confirm_draft_date"),
            pl.col("so_order_date"),
            pl.col("so_created_date"),
        ]))

        .when(pl.col("current_stage") == "SO On Hold / Approval")
        .then(pl.coalesce([
            pl.col("confirm_onhold_date"),
            pl.col("approved_date"),
            pl.col("so_order_date"),
        ]))

        .when(pl.col("current_stage").is_in(["SO Pending Packing", "Partial Packing"]))
        .then(pl.coalesce([
            pl.col("approved_date"),
            pl.col("so_order_date"),
            pl.col("so_created_date"),
        ]))

        .when(pl.col("current_stage") == "Invoice Exists, Packing Slip Missing")
        .then(pl.coalesce([
            pl.col("first_invoice_date"),
            pl.col("so_order_date"),
        ]))

        .when(pl.col("current_stage").is_in(["Packed Not Invoiced", "Partially Invoiced"]))
        .then(pl.coalesce([
            pl.col("last_packing_slip_date"),
            pl.col("first_packing_slip_date"),
        ]))

        .when(pl.col("current_stage") == "Invoice Past Due")
        .then(pl.coalesce([
            pl.col("next_due_date"),
            pl.col("last_invoice_date"),
        ]))

        .when(pl.col("current_stage") == "Invoiced Waiting Payment")
        .then(pl.coalesce([
            pl.col("last_invoice_date"),
            pl.col("first_invoice_date"),
        ]))

        .when(pl.col("current_stage") == "Paid / Completed")
        .then(pl.coalesce([
            pl.col("last_paid_date"),
            pl.col("last_invoice_date"),
        ]))

        .otherwise(pl.lit(None).cast(pl.Date))
        .alias("stage_start_date")
    )
])

flow = flow.with_columns([
    day_diff_expr(
        pl.col("as_of_date"),
        pl.col("stage_start_date")
    )
    .fill_null(0)
    .clip(lower_bound=0)
    .alias("aging_days")
])

flow = flow.with_columns([
    pl.when(pl.col("current_stage").is_in(CLOSED_STAGES))
    .then(0)
    .otherwise(pl.col("aging_days"))
    .alias("aging_days")
])

flow = flow.with_columns([
    day_diff_expr(pl.col("first_packing_slip_date"), pl.col("so_order_date"))
    .alias("lead_order_to_first_packing_days"),

    day_diff_expr(pl.col("first_invoice_date"), pl.col("first_packing_slip_date"))
    .alias("lead_packing_to_invoice_days"),

    day_diff_expr(pl.col("first_paid_date"), pl.col("first_invoice_date"))
    .alias("lead_invoice_to_paid_days"),

    day_diff_expr(pl.col("first_invoice_date"), pl.col("so_order_date"))
    .alias("cycle_order_to_invoice_days"),

    day_diff_expr(pl.col("first_paid_date"), pl.col("so_order_date"))
    .alias("cycle_order_to_paid_days"),
])


# ============================================================
# SLA, RISK STATUS, PRIORITY SCORE
# ============================================================

sla_df = pl.DataFrame({
    "current_stage": list(SLA_BY_STAGE.keys()),
    "sla_days": list(SLA_BY_STAGE.values()),
})

flow = (
    flow
    .join(sla_df, on="current_stage", how="left")
    .with_columns([
        pl.col("sla_days").fill_null(1)
    ])
)

flow = flow.with_columns([
    (
        pl.when(pl.col("current_stage").is_in(CLOSED_STAGES))
        .then(pl.lit("Closed / Completed"))

        .when(pl.col("current_stage") == "Invoice Past Due")
        .then(pl.lit("Critical"))

        .when(
            (pl.col("current_stage") == "Invoiced Waiting Payment")
            & (pl.col("next_due_date") >= pl.col("as_of_date"))
        )
        .then(pl.lit("On Time"))

        .when(pl.col("current_stage") == "Invoiced Waiting Payment")
        .then(pl.lit("Warning"))

        .when(pl.col("aging_days") <= pl.col("sla_days"))
        .then(pl.lit("On Time"))

        .when(pl.col("aging_days") <= pl.col("sla_days") * 2)
        .then(pl.lit("Warning"))

        .otherwise(pl.lit("Critical"))
        .alias("risk_status")
    )
])

max_stuck = flow.select(pl.col("stuck_value").max()).item()

if max_stuck is None:
    max_stuck = 0

sla_denominator = (
    pl.when(pl.col("sla_days") == 0)
    .then(None)
    .otherwise(pl.col("sla_days"))
    .cast(pl.Float64)
)

flow = flow.with_columns([
    pl.when(pl.lit(max_stuck) > 0)
    .then((pl.col("stuck_value").clip(lower_bound=0).log1p() / pl.lit(max_stuck).log1p()) * 100)
    .otherwise(0)
    .alias("value_score"),

    ((pl.col("aging_days").fill_null(0) / sla_denominator) * 50)
    .clip(upper_bound=100)
    .fill_null(0)
    .alias("aging_score"),

    pl.col("sales_order_value")
    .sum()
    .over("customer_code")
    .alias("customer_total_so_value"),
])

flow = flow.with_columns([
    (
        (pl.col("customer_total_so_value").rank(method="average") / pl.len()) * 100
    )
    .fill_null(0)
    .alias("customer_importance_score")
])

flow = flow.with_columns([
    (
        0.50 * pl.col("value_score")
        + 0.30 * pl.col("aging_score")
        + 0.20 * pl.col("customer_importance_score")
    )
    .round(2)
    .alias("priority_score")
])

flow = flow.with_columns([
    pl.when(pl.col("current_stage").is_in(CLOSED_STAGES))
    .then(0)
    .otherwise(pl.col("priority_score"))
    .alias("priority_score")
])


# ============================================================
# RECOMMENDED ACTION + SORT FIELDS
# ============================================================

flow = flow.with_columns([
    (
        pl.when(pl.col("current_stage") == "Quotation / Draft")
        .then(pl.lit("Follow up quotation ke customer atau sales owner. Prioritaskan value besar dan aging tinggi."))

        .when(pl.col("current_stage") == "SO On Hold / Approval")
        .then(pl.lit("Cek approval, credit limit, pass due, price, discount, atau payment method."))

        .when(pl.col("current_stage") == "SO Pending Packing")
        .then(pl.lit("Koordinasi sales, warehouse, dan inventory. Cek ketersediaan stock dan jadwal packing."))

        .when(pl.col("current_stage") == "Partial Packing")
        .then(pl.lit("Cek sisa order yang belum dipacking. Pastikan partial packing memiliki rencana proses berikutnya."))

        .when(pl.col("current_stage") == "Invoice Exists, Packing Slip Missing")
        .then(pl.lit("Cek mapping dokumen. Invoice sudah ada tetapi Packing Slip tidak terhubung ke SO."))

        .when(pl.col("current_stage") == "Packed Not Invoiced")
        .then(pl.lit("Segera proses invoice. Barang sudah masuk tahap packing/shipping tetapi belum menjadi tagihan."))

        .when(pl.col("current_stage") == "Partially Invoiced")
        .then(pl.lit("Cek Packing Slip yang belum ter-invoice. Pastikan tidak ada dokumen tercecer."))

        .when(pl.col("current_stage") == "Invoice Past Due")
        .then(pl.lit("Prioritaskan collection. Invoice sudah melewati due date."))

        .when(pl.col("current_stage") == "Invoiced Waiting Payment")
        .then(pl.lit("Monitor pembayaran sampai due date. Pastikan reminder collection berjalan."))

        .when(pl.col("current_stage") == "Paid / Completed")
        .then(pl.lit("Transaksi selesai. Tidak perlu action lanjutan."))

        .otherwise(pl.lit("Review data mapping, status dokumen, dan kelengkapan transaksi."))
        .alias("recommended_action")
    )
])

stage_order_df = pl.DataFrame({
    "current_stage": [
        "Quotation / Draft",
        "SO On Hold / Approval",
        "SO Pending Packing",
        "Partial Packing",
        "Invoice Exists, Packing Slip Missing",
        "Packed Not Invoiced",
        "Partially Invoiced",
        "Invoiced Waiting Payment",
        "Invoice Past Due",
        "Paid / Completed",
        "Excluded / Closed",
        "Needs Review",
    ],
    "stage_order": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 98, 100],
})

risk_order_df = pl.DataFrame({
    "risk_status": [
        "Critical",
        "Warning",
        "On Time",
        "Closed / Completed",
        "Need Check",
    ],
    "risk_order": [1, 2, 3, 4, 5],
})

flow = (
    flow
    .join(stage_order_df, on="current_stage", how="left")
    .join(risk_order_df, on="risk_status", how="left")
    .with_columns([
        pl.col("stage_order").fill_null(100).cast(pl.Int64),
        pl.col("risk_order").fill_null(99).cast(pl.Int64),

        pl.col("so_order_date").dt.strftime("%Y-%m").alias("order_month"),
        pl.col("first_invoice_date").dt.strftime("%Y-%m").alias("invoice_month"),
        pl.col("first_packing_slip_date").dt.strftime("%Y-%m").alias("packing_month"),

        (pl.col("so_value") - pl.col("sales_order_value")).alias("excluded_so_value"),
    ])
)

flow = flow.with_columns([
    safe_divide_expr(pl.col("packing_slip_value"), pl.col("sales_order_value"))
    .alias("packing_rate_vs_so"),

    safe_divide_expr(pl.col("invoice_value"), pl.col("packing_slip_value"))
    .alias("invoice_rate_vs_packing"),

    safe_divide_expr(pl.col("invoice_value"), pl.col("sales_order_value"))
    .alias("invoice_rate_vs_so"),

    safe_divide_expr(pl.col("paid_value"), pl.col("invoice_value"))
    .alias("payment_rate_vs_invoice"),
])


# ============================================================
# VALIDASI FINAL CURRENT STAGE
# ============================================================

print("\nValidasi current_stage setelah exclude dan status Done-Partial:")
print(
    flow
    .group_by("current_stage")
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("so_value").sum().alias("so_value"),
        pl.col("stuck_value").sum().alias("stuck_value"),
        pl.col("aging_days").max().alias("max_aging_days"),
    ])
    .sort("so_value", descending=True)
)

print("\nValidasi nilai Cancelled / Closed / Declined di flow:")
print(
    flow
    .select([
        pl.col("cancelled_value").sum().alias("cancelled_value_should_be_0"),
        pl.col("closed_value").sum().alias("closed_value_should_be_0"),
        pl.col("declined_value").sum().alias("declined_value_should_be_0"),
    ])
)

print("\nValidasi AS_OF_DATE:")
print(
    flow
    .select([
        pl.col("as_of_date").min().alias("min_as_of_date"),
        pl.col("as_of_date").max().alias("max_as_of_date"),
        pl.col("so_order_date").max().alias("max_so_order_date"),
        pl.col("first_invoice_date").max().alias("max_first_invoice_date"),
        pl.col("next_due_date").max().alias("max_next_due_date_not_used_for_as_of"),
    ])
)

print("\nValidasi khusus SO Done-Partial + Invoice Done:")
print(
    flow
    .filter(
        pl.col("is_so_done_partial")
        & pl.col("is_invoice_done")
    )
    .group_by("current_stage")
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("so_value").sum().alias("so_value"),
        pl.col("invoice_value").sum().alias("invoice_value"),
        pl.col("paid_value").sum().alias("paid_value"),
        pl.col("stuck_value").sum().alias("stuck_value"),
    ])
    .sort("so_value", descending=True)
)


# ============================================================
# SUMMARY TABLES
# ============================================================

print("\n[11/14] Membuat summary tables...")

funnel_summary = pl.DataFrame({
    "flow_stage": [
        "Gross SO After Exclude",
        "Quotation / Draft",
        "Sales Order Active",
        "Packing Slip",
        "Invoice",
        "Paid",
    ],
    "stage_order": [0, 1, 2, 3, 4, 5],
    "value": [
        sum_col(flow, "so_value"),
        sum_col(flow, "quotation_value"),
        sum_col(flow, "sales_order_value"),
        sum_col(flow, "packing_slip_value"),
        sum_col(flow, "invoice_value"),
        sum_col(flow, "paid_value"),
    ],
    "document_count": [
        count_distinct_col(flow.filter(pl.col("so_value") != 0), "so_code"),
        count_distinct_col(flow.filter(pl.col("quotation_value") != 0), "so_code"),
        count_distinct_col(flow.filter(pl.col("sales_order_value") != 0), "so_code"),
        count_distinct_col(flow.filter(pl.col("packing_slip_value") != 0), "so_code"),
        count_distinct_col(flow.filter(pl.col("invoice_value") != 0), "so_code"),
        count_distinct_col(flow.filter(pl.col("paid_value") != 0), "so_code"),
    ],
})

stage_summary = (
    flow
    .group_by(["stage_order", "current_stage", "bottleneck_stage", "risk_status"])
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("so_value").sum().alias("gross_so_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("sales_order_value").sum().alias("sales_order_value"),
        pl.col("packing_slip_value").sum().alias("packing_slip_value"),
        pl.col("invoice_value").sum().alias("invoice_value"),
        pl.col("paid_value").sum().alias("paid_value"),
        pl.col("cancelled_value").sum().alias("cancelled_value"),
        pl.col("closed_value").sum().alias("closed_value"),
        pl.col("declined_value").sum().alias("declined_value"),
        pl.col("excluded_so_value").sum().alias("excluded_so_value"),
        pl.col("stuck_value").sum().alias("stuck_value"),
        pl.col("aging_days").mean().alias("avg_aging_days"),
        pl.col("aging_days").max().alias("max_aging_days"),
        pl.col("priority_score").mean().alias("avg_priority_score"),
    ])
    .sort(["stage_order", "risk_status"])
)

bottleneck_summary = (
    flow
    .group_by(["bottleneck_stage", "risk_status"])
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("stuck_value").sum().alias("stuck_value"),
        pl.col("aging_days").mean().alias("avg_aging_days"),
        pl.col("aging_days").max().alias("max_aging_days"),
        pl.col("priority_score").mean().alias("avg_priority_score"),
    ])
    .sort(["stuck_value", "avg_aging_days"], descending=[True, True])
)

monthly_flow_summary = (
    flow
    .group_by(["order_month", "site", "sales_division"])
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("so_value").sum().alias("gross_so_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("sales_order_value").sum().alias("sales_order_value"),
        pl.col("packing_slip_value").sum().alias("packing_slip_value"),
        pl.col("invoice_value").sum().alias("invoice_value"),
        pl.col("paid_value").sum().alias("paid_value"),
        pl.col("stuck_value").sum().alias("stuck_value"),
        pl.col("cycle_order_to_invoice_days").mean().alias("avg_cycle_order_to_invoice_days"),
        pl.col("cycle_order_to_paid_days").mean().alias("avg_cycle_order_to_paid_days"),
    ])
)

salesman_summary = (
    flow
    .group_by(["salesman", "site", "sales_division"])
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("customer_code").n_unique().alias("customer_count"),
        pl.col("so_value").sum().alias("gross_so_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("sales_order_value").sum().alias("sales_order_value"),
        pl.col("packing_slip_value").sum().alias("packing_slip_value"),
        pl.col("invoice_value").sum().alias("invoice_value"),
        pl.col("paid_value").sum().alias("paid_value"),
        pl.col("stuck_value").sum().alias("stuck_value"),
        (pl.col("risk_status") == "Critical").sum().alias("critical_count"),
        pl.col("aging_days").mean().alias("avg_aging_days"),
        pl.col("priority_score").mean().alias("avg_priority_score"),
    ])
    .sort("stuck_value", descending=True)
)

customer_summary = (
    flow
    .group_by(["customer_code", "customer_name", "site", "sales_division"])
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("so_value").sum().alias("gross_so_value"),
        pl.col("quotation_value").sum().alias("quotation_value"),
        pl.col("sales_order_value").sum().alias("sales_order_value"),
        pl.col("packing_slip_value").sum().alias("packing_slip_value"),
        pl.col("invoice_value").sum().alias("invoice_value"),
        pl.col("paid_value").sum().alias("paid_value"),
        pl.col("stuck_value").sum().alias("stuck_value"),
        (pl.col("risk_status") == "Critical").sum().alias("critical_count"),
        pl.col("aging_days").mean().alias("avg_aging_days"),
        pl.col("priority_score").mean().alias("avg_priority_score"),
    ])
    .sort("stuck_value", descending=True)
)

action_list = (
    flow
    .filter(
        (~pl.col("current_stage").is_in(CLOSED_STAGES))
        & (
            (pl.col("stuck_value") > 0)
            | (pl.col("risk_status").is_in(["Critical", "Warning"]))
        )
    )
    .sort(
        ["risk_order", "priority_score", "stuck_value"],
        descending=[False, True, True]
    )
)

action_columns = [
    "so_code",
    "so_status",
    "invoice_status_sample",
    "invoice_status_list",
    "current_stage",
    "bottleneck_stage",
    "risk_status",
    "priority_score",
    "stuck_value",
    "aging_days",
    "sla_days",
    "as_of_date",
    "site",
    "sales_division",
    "salesman",
    "customer_code",
    "customer_name",
    "so_order_date",
    "stage_start_date",
    "approved_date",
    "first_packing_slip_date",
    "last_packing_slip_date",
    "first_invoice_date",
    "last_invoice_date",
    "next_due_date",
    "last_paid_date",
    "so_value",
    "quotation_value",
    "sales_order_value",
    "packing_slip_value",
    "invoice_value",
    "paid_value",
    "unpaid_value",
    "packing_gap_value",
    "invoice_gap_value",
    "payment_gap_value",
    "is_so_done",
    "is_so_done_partial",
    "is_invoice_done",
    "is_fully_invoiced",
    "is_fully_paid",
    "approval_reason",
    "on_hold_approval",
    "cancel_reason",
    "recommended_action",
]

action_columns = [
    col for col in action_columns
    if col in action_list.columns
]

action_list = action_list.select(action_columns)


# ============================================================
# PRODUCT BOTTLENECK
# ============================================================

product_bottleneck = pl.DataFrame(
    schema={
        "product_code": pl.Utf8,
        "product_name": pl.Utf8,
        "brand": pl.Utf8,
        "current_stage": pl.Utf8,
        "bottleneck_stage": pl.Utf8,
        "risk_status": pl.Utf8,
        "so_count": pl.Int64,
        "line_count": pl.Int64,
        "allocated_stuck_value": pl.Float64,
        "gross_line_value": pl.Float64,
        "qty": pl.Float64,
    }
)


# ============================================================
# DATA QUALITY CHECK
# ============================================================

print("\n[12/14] Membuat data quality summary...")

flow_so_codes = flow.select("so_code").to_series()

orphan_ps = ps_with_so_code.filter(
    (~pl.col("_so_code").is_in(flow_so_codes))
    & (~pl.col("_so_code").is_in(excluded_so_codes))
)

orphan_si = si_with_so_code.filter(
    (~pl.col("_so_code").is_in(flow_so_codes))
    & (~pl.col("_so_code").is_in(excluded_so_codes))
)

so_active_without_ps = flow.filter(
    (pl.col("sales_order_value") > 0)
    & (pl.col("packing_slip_value") == 0)
)

invoice_exists_ps_missing = flow.filter(
    pl.col("current_stage") == "Invoice Exists, Packing Slip Missing"
)

packed_not_invoiced = flow.filter(
    pl.col("current_stage") == "Packed Not Invoiced"
)

invoice_past_due = flow.filter(
    pl.col("current_stage") == "Invoice Past Due"
)

so_done_partial_invoice_done = flow.filter(
    pl.col("is_so_done_partial")
    & pl.col("is_invoice_done")
)

data_quality_summary = pl.DataFrame([
    {
        "check_name": "SO excluded Cancelled / Closed / Declined",
        "row_count": count_distinct_col(so_excluded, "_so_code"),
        "value": sum_col(so_excluded, SO_NET_PRICE),
        "notes": "SO dengan status Cancelled, Closed, atau Declined dikeluarkan dari Business Flow.",
    },
    {
        "check_name": "SO Done-Partial with Invoice Done",
        "row_count": so_done_partial_invoice_done.height,
        "value": sum_col(so_done_partial_invoice_done, "invoice_value"),
        "notes": "SO Done-Partial dengan Invoice Done diarahkan ke tahap payment, bukan lagi partial invoice/packing.",
    },
    {
        "check_name": "SO active without Packing Slip",
        "row_count": so_active_without_ps.height,
        "value": sum_col(so_active_without_ps, "sales_order_value"),
        "notes": "Sales order aktif tetapi belum ada Packing Slip.",
    },
    {
        "check_name": "Packing Slip without matching active SO",
        "row_count": orphan_ps.height,
        "value": sum_col(orphan_ps, PS_NET_PRICE),
        "notes": "Packing Slip memiliki Sales Order Code, tetapi tidak ditemukan di SO aktif Business Flow. SO excluded tidak dihitung orphan.",
    },
    {
        "check_name": "Invoice without matching active SO",
        "row_count": orphan_si.height,
        "value": sum_col(orphan_si, SI_NET_PRICE),
        "notes": "Invoice memiliki Sales Order/Return Code, tetapi tidak ditemukan di SO aktif Business Flow. SO excluded tidak dihitung orphan.",
    },
    {
        "check_name": "Invoice exists but Packing Slip missing",
        "row_count": invoice_exists_ps_missing.height,
        "value": sum_col(invoice_exists_ps_missing, "invoice_value"),
        "notes": "Invoice sudah ada tetapi Packing Slip tidak terdeteksi. Perlu cek mapping dokumen.",
    },
    {
        "check_name": "Packed not invoiced",
        "row_count": packed_not_invoiced.height,
        "value": sum_col(packed_not_invoiced, "stuck_value"),
        "notes": "Barang sudah masuk tahap Packing Slip tetapi invoice belum terbentuk.",
    },
    {
        "check_name": "Invoice past due",
        "row_count": invoice_past_due.height,
        "value": sum_col(invoice_past_due, "stuck_value"),
        "notes": "Invoice belum paid dan sudah melewati due date.",
    },
])


# ============================================================
# COLLECT OUTPUTS
# ============================================================

outputs = {
    f"{TABLE_PREFIX}flow_master": flow,
    f"{TABLE_PREFIX}funnel_summary": funnel_summary,
    f"{TABLE_PREFIX}stage_summary": stage_summary,
    f"{TABLE_PREFIX}bottleneck_summary": bottleneck_summary,
    f"{TABLE_PREFIX}monthly_flow": monthly_flow_summary,
    f"{TABLE_PREFIX}salesman_summary": salesman_summary,
    f"{TABLE_PREFIX}customer_summary": customer_summary,
    f"{TABLE_PREFIX}action_list": action_list,
    f"{TABLE_PREFIX}product_bottleneck": product_bottleneck,
    f"{TABLE_PREFIX}data_quality": data_quality_summary,
}

print("\n[13/14] Output tables")
for name, df_out in outputs.items():
    print_shape(name, df_out)


# ============================================================
# LOAD TO BIGQUERY
# ============================================================

print("\n[14/14] Load output tables to BigQuery...")

client = bigquery.Client(project=PROJECT_ID, credentials=BQ_CREDENTIALS)

ensure_bigquery_dataset(
    client=client,
    project_id=PROJECT_ID,
    dataset_id=DATASET_ID,
    location=BQ_LOCATION,
)

for table_name, df_out in outputs.items():
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"

    print(f"\nLoading table: {table_id}")

    load_polars_to_bigquery(
        client=client,
        df=df_out,
        table_id=table_id,
        write_disposition=WRITE_DISPOSITION,
    )


# ============================================================
# BUSINESS RECAP
# ============================================================

print("\nBUSINESS FLOW RECAP")
print("=" * 90)
print(f"AS_OF_DATE                                   : {AS_OF_DATE}")
print(f"Excluded Cancelled/Closed/Declined SO Value : {sum_col(so_excluded, SO_NET_PRICE):,.0f}")
print(f"Gross SO Value After Exclude                : {sum_col(flow, 'so_value'):,.0f}")
print(f"Quotation / Draft Value                     : {sum_col(flow, 'quotation_value'):,.0f}")
print(f"Active Sales Order Value                    : {sum_col(flow, 'sales_order_value'):,.0f}")
print(f"Cancelled Value In Flow                     : {sum_col(flow, 'cancelled_value'):,.0f}")
print(f"Closed Value In Flow                        : {sum_col(flow, 'closed_value'):,.0f}")
print(f"Declined Value In Flow                      : {sum_col(flow, 'declined_value'):,.0f}")
print(f"Packing Slip Value                          : {sum_col(flow, 'packing_slip_value'):,.0f}")
print(f"Invoice Value                               : {sum_col(flow, 'invoice_value'):,.0f}")
print(f"Paid Value                                  : {sum_col(flow, 'paid_value'):,.0f}")
print(f"Total Stuck Value                           : {sum_col(flow, 'stuck_value'):,.0f}")
print("=" * 90)

print("\nValidasi final: current_stage tidak boleh berisi Cancelled / Closed / Declined")
print(
    flow
    .group_by("current_stage")
    .agg([
        pl.col("so_code").n_unique().alias("so_count"),
        pl.col("so_value").sum().alias("so_value"),
        pl.col("stuck_value").sum().alias("stuck_value"),
        pl.col("aging_days").max().alias("max_aging_days"),
    ])
    .sort("so_value", descending=True)
)

print("\nValidasi SO Done-Partial + Invoice Done:")
print(
    flow
    .filter(
        pl.col("is_so_done_partial")
        & pl.col("is_invoice_done")
    )
    .select([
        "so_code",
        "so_status",
        "invoice_status_list",
        "current_stage",
        "risk_status",
        "so_order_date",
        "stage_start_date",
        "as_of_date",
        "aging_days",
        "so_value",
        "packing_slip_value",
        "invoice_value",
        "paid_value",
        "unpaid_value",
        "stuck_value",
        "is_fully_invoiced",
        "is_fully_paid",
    ])
    .head(30)
)

print("\nTop bottleneck by stuck value:")
print(
    bottleneck_summary
    .sort("stuck_value", descending=True)
    .head(10)
    .select([
        "bottleneck_stage",
        "risk_status",
        "so_count",
        "stuck_value",
        "avg_aging_days",
    ])
)

print("\nBigQuery tables for Looker Studio:")
print("=" * 90)

for table_name in outputs.keys():
    print(f"{PROJECT_ID}.{DATASET_ID}.{table_name}")

print("=" * 90)
print(f"Main table: {PROJECT_ID}.{DATASET_ID}.{TABLE_PREFIX}flow_master")