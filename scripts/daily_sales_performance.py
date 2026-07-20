# Daily Sales Performance pipeline. Destination: pipamas-v2.data.
# Input files are passed as arguments (never hardcoded here).
# BigQuery auth: explicit service account key. The key path is configured in
# ONE place — env var BQ_KEY_FILE (default: pipamas-v2-f9e3e0625182.json,
# looked up in the working directory, then next to the app root).

import argparse
import os
import re
import numpy as np
import pandas as pd
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account
from google.api_core.exceptions import NotFound


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


# =============================================================================
# 1. CONFIGURATION
# =============================================================================

LOCATION = os.environ.get("BQ_LOCATION", "asia-southeast2")

BQ_DESTINATIONS = [
    {
        "project_id": os.environ.get("BQ_PROJECT_ID", "pipamas-v2"),
        "dataset_id": os.environ.get("BQ_DATASET_ID", "data"),
    },
]

_parser = argparse.ArgumentParser(description="Daily Sales Performance")
_parser.add_argument("--invoice", required=True, help="Invoice export .xlsx")
_parser.add_argument("--target", required=True, help="Target workbook .xlsx")
_parser.add_argument("--brand", required=True, help="Active brand list .xlsx")
_ARGS = _parser.parse_args()

NEW_FILE_XLSX = _ARGS.invoice
PRODUCT_PIPAMAS = _ARGS.target
PRODUCT_LAINNYA = _ARGS.brand

TABLE_SALES_INVOICE = "sales_invoice"
TABLE_SALES_INVOICE_DASHBOARD = "sales_invoice_dashboard"
TABLE_TARGET_2026 = "target_2026"
TABLE_TARGET_2026_AO = "target_2026_ao"
TABLE_SALES_INVOICE_AO_FLAG = "sales_invoice_ao_flag"
TABLE_SALES_VS_TARGET_MONTHLY_DASHBOARD = "sales_vs_target_monthly_dashboard"
TABLE_INCENTIVE_DASHBOARD = "incentive_dashboard"

TABLE_DAILY_SALES = "daily_sales"
TABLE_MONTHLY_SALES = "monthly_sales"
TABLE_BRANCH_DAILY_SALES = "branch_daily_sales"
TABLE_SALESMAN_DAILY_SALES = "salesman_daily_sales"
TABLE_SKU_MONTHLY_SALES = "sku_monthly_sales"

ELMOD_SALESMEN = {"ELMOD01", "ELMOD02"}

MONTH_MAP = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

MONTH_TO_NUM = {
    "January": "01",
    "February": "02",
    "March": "03",
    "April": "04",
    "May": "05",
    "June": "06",
    "July": "07",
    "August": "08",
    "September": "09",
    "October": "10",
    "November": "11",
    "December": "12",
}


# =============================================================================
# 2. BASIC HELPERS
# =============================================================================

def norm_key(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def is_cat_sku(value) -> bool:
    return norm_key(value) == "cat"


def is_warnamu_sku(value) -> bool:
    return norm_key(value) == "warnamu"


def clean_colnames(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.replace(" ", "_", regex=False)
        .str.replace("/", "_", regex=False)
        .str.replace(".", "", regex=False)
    )
    return df


def clean_text_series(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
        .str.strip()
        .replace({"nan": "", "None": "", "NaT": ""})
    )


def first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df is None or df.empty:
        return None

    exact = {str(c).strip(): c for c in df.columns}
    for cand in candidates:
        if cand in exact:
            return exact[cand]

    norm = {norm_key(c): c for c in df.columns}
    for cand in candidates:
        hit = norm.get(norm_key(cand))
        if hit is not None:
            return hit

    return None


def get_series(df: pd.DataFrame, candidates: list[str], default=None):
    col = first_existing_col(df, candidates)
    if col is None:
        return pd.Series([default] * len(df), index=df.index)
    return df[col]


def safe_numeric(series, default=0.0):
    return pd.to_numeric(series, errors="coerce").fillna(default)


def safe_datetime(series):
    return pd.to_datetime(series, errors="coerce")


def month_invoice_from_date(date_series: pd.Series) -> pd.Series:
    return pd.to_datetime(date_series, errors="coerce").dt.strftime("%m-%Y")


def normalize_salesman(series: pd.Series) -> pd.Series:
    rename_map = {
        "ICSLM80": "ICCOS08",
    }

    return (
        series.astype(str)
        .str.strip()
        .str.upper()
        .replace(rename_map)
    )


def sales_code_suffix(salesman) -> int | None:
    s = str(salesman or "").strip().upper()
    m = re.search(r"(\d{2})$", s)
    if not m:
        return None

    try:
        return int(m.group(1))
    except Exception:
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
        return "Tasik"

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
        return "Tasik"
    if 80 <= suffix < 90:
        return "Bogor"

    return "Project"


def normalize_div(value) -> str:
    raw = str(value or "").strip()
    key = raw.upper().replace(".", "").replace(" ", "")

    if key in {"EL", "ELEKTRIK", "ELECTRIK"}:
        return "EL"
    if key in {"IC", "ICI"}:
        return "ICI"
    if key in {"PI", "PIPAMAS", "PIPA"}:
        return "PI"
    if key in {"PP", "POMPA", "PIPAPOMPA"}:
        return "PP"
    if key in {"LM"}:
        return "LM"

    return raw.upper() if raw else ""


def normalize_branch_upper(value) -> str:
    return str(value or "").strip().upper()


def is_excluded_actual_target_branch(value) -> bool:
    return normalize_branch_upper(value) in {
        "PROJECT",
        "DIST KALIMANTAN",
        "DIST SUMATERA",
        "AGEN",
    }


def is_excluded_target_branch(value) -> bool:
    return normalize_branch_upper(value) in {
        "PROJECT",
        "DIST KALIMANTAN",
        "DIST SUMATERA",
    }


def unpivot_target(df: pd.DataFrame, id_cols: list[str]) -> pd.DataFrame:
    month_cols = [c for c in df.columns if str(c).startswith("Mo ")]

    df_melt = df.melt(
        id_vars=id_cols,
        value_vars=month_cols,
        var_name="Month_Label",
        value_name="Target",
    )

    df_melt["Month_Num"] = df_melt["Month_Label"].str.extract(r"(\d+)$").astype(int)
    df_melt["Month"] = df_melt["Month_Num"].map(MONTH_MAP)
    df_melt = df_melt.drop(columns=["Month_Label", "Month_Num"])
    df_melt = df_melt.dropna(subset=["Target"])
    df_melt = df_melt[df_melt["Target"] != 0].copy()

    return df_melt


# =============================================================================
# 3. PRODUCT REFERENCES
# =============================================================================

PIPAMAS_BRANDS = {"mtn", "pipamas", "tangit"}


# =============================================================================
# CUSTOM CATEGORY MAPPING (port dari Power Query)
# - Cirebon: Panasonic Ex Fan -> Panasonic Fan, Sekai Ex Fan -> Sekai (selalu, Div tidak relevan)
# - Bandung/Tasik/Bogor: Panasonic Ex Fan -> Panasonic Fan, Sekai Ex Fan -> Sekai
#   HANYA jika Div = "EL" (kalau Div = "PP", nama asli tetap dipakai)
# - Maspion Ex Fan: nama asli HANYA dipakai jika Branch in {Bandung, Tasik} dan Div = "PP"
#   Selain kombinasi itu (branch/div lain), di-rename jadi "Maspion"
# =============================================================================

def apply_custom_category_mapping(product_category: str, branch: str, sales_div: str) -> str:
    cat_upper = str(product_category or "").strip().upper()
    branch_clean = str(branch or "").strip()
    div_upper = str(sales_div or "").strip().upper()

    is_maspion_ex_fan = cat_upper == "MASPION EX FAN"
    is_panasonic_ex_fan = cat_upper == "PANASONIC EX FAN"
    is_sekai_ex_fan = cat_upper == "SEKAI EX FAN"

    if is_maspion_ex_fan:
        keep_maspion_ex_fan = branch_clean in {"Bandung", "Tasik"} and div_upper == "PP"
        return product_category if keep_maspion_ex_fan else "Maspion"

    if branch_clean == "Cirebon":
        if is_panasonic_ex_fan:
            return "Panasonic Fan"
        if is_sekai_ex_fan:
            return "Sekai"
        return product_category

    if branch_clean in {"Bandung", "Tasik", "Bogor"} and div_upper == "EL":
        if is_panasonic_ex_fan:
            return "Panasonic Fan"
        if is_sekai_ex_fan:
            return "Sekai"
        return product_category

    return product_category


def load_product_references():
    print("\n[1/10] Membaca product reference...")

    product_pipamas = pd.read_excel(PRODUCT_PIPAMAS, sheet_name="BREAKDOWN", header=1)
    product_pipamas.columns = [str(c).strip() for c in product_pipamas.columns]

    pp_eigen = first_existing_col(product_pipamas, ["Eigen Code", "eigen code", "Code"])
    pp_grup = first_existing_col(product_pipamas, ["Grup SKU", "GRUP SKU", "grup sku"])
    pp_grup_bogor = first_existing_col(product_pipamas, ["GRUP SKU BOGOR", "Grup SKU Bogor", "grup sku bogor"])

    pp = pd.DataFrame()
    pp["Prod_Code"] = clean_text_series(product_pipamas[pp_eigen]) if pp_eigen else ""
    pp["grup_sku"] = clean_text_series(product_pipamas[pp_grup]) if pp_grup else ""
    pp["grup_sku_bogor"] = clean_text_series(product_pipamas[pp_grup_bogor]) if pp_grup_bogor else ""
    pp = pp.dropna(subset=["Prod_Code"]).drop_duplicates("Prod_Code")

    product_lainnya = pd.read_excel(PRODUCT_LAINNYA, sheet_name="Report")
    product_lainnya.columns = [str(c).strip() for c in product_lainnya.columns]

    pl_code = first_existing_col(product_lainnya, ["Code"])
    pl_cat = first_existing_col(product_lainnya, ["Product Category", "Product_Category"])

    pl = pd.DataFrame()
    pl["Prod_Code"] = clean_text_series(product_lainnya[pl_code]) if pl_code else ""
    pl["Product_Category"] = clean_text_series(product_lainnya[pl_cat]) if pl_cat else ""
    pl = pl.dropna(subset=["Prod_Code"]).drop_duplicates("Prod_Code")

    print(f"[OK] Product Pipamas: {len(pp):,} rows")
    print(f"[OK] Product Lainnya: {len(pl):,} rows")

    return pp, pl


def assign_sku_from_row(row) -> str:
    brand = str(row.get("Brand_Name", "") or "").strip()
    product_category = str(row.get("Product_Category", "") or "").strip()
    grup_sku = str(row.get("grup_sku", "") or "").strip()
    grup_sku_bogor = str(row.get("grup_sku_bogor", "") or "").strip()
    branch = str(row.get("Branch", "") or "").strip()

    is_pipamas = brand.lower() in PIPAMAS_BRANDS

    if is_pipamas:
        result = grup_sku_bogor if branch.upper() == "BOGOR" and grup_sku_bogor else grup_sku
    else:
        result = product_category if product_category else brand

    if not result or result.lower() in {"nan", "none"}:
        result = brand

    return str(result or "").strip().lower()


# =============================================================================
# 4. SALES INVOICE PREPARATION
# =============================================================================

FINAL_SALES_COLUMNS = [
    "Invoice_Date",
    "Due_Date",
    "Month_Invoice",
    "Type",
    "Invoice_Code",
    "Sales_Order_Return_Code",
    "References",
    "Branch",
    "Sales_Div",
    "Salesman",
    "Customer_Code",
    "Customer_Name",
    "Prod_Code",
    "Brand_Name",
    "Product_Category_Name",
    "Prod_Name",
    "Quantity",
    "Net_Price",
    "Volume",
    "Weight",
    "sku",
    "Status",
    "Invoice_Address",
    "Packing_Slip",
    "Packing_Date",
]


def prepare_invoice_dataframe(raw_df: pd.DataFrame, pp_ref: pd.DataFrame, pl_ref: pd.DataFrame) -> pd.DataFrame:
    print("\n[2/10] Menyiapkan invoice dataframe...")

    df = raw_df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    out = pd.DataFrame(index=df.index)

    out["Invoice_Date"] = safe_datetime(get_series(df, ["Invoice Date", "Invoice_Date", "InvoiceDate"]))
    out["Due_Date"] = safe_datetime(get_series(df, ["Due Date", "Due_Date", "DueDate"]))
    out["Packing_Date"] = safe_datetime(get_series(df, ["Packing Date", "Packing_Date", "PackingDate"]))

    out = out.dropna(subset=["Invoice_Date"]).copy()
    df = df.loc[out.index].copy()

    month_col = first_existing_col(df, ["Month Invoice", "Month_Invoice", "Month"])
    if month_col:
        out["Month_Invoice"] = clean_text_series(df[month_col])
        out.loc[out["Month_Invoice"].isin(["", "nan", "None"]), "Month_Invoice"] = month_invoice_from_date(out["Invoice_Date"])
    else:
        out["Month_Invoice"] = month_invoice_from_date(out["Invoice_Date"])

    out["Type"] = clean_text_series(get_series(df, ["Type"], ""))
    out["Invoice_Code"] = clean_text_series(get_series(df, ["Invoice Code", "Invoice_Code", "Code"], ""))
    out["Sales_Order_Return_Code"] = clean_text_series(get_series(df, ["Sales Order Return Code", "Sales_Order_Return_Code"], ""))
    out["References"] = clean_text_series(get_series(df, ["References", "Reference"], ""))

    out["Salesman"] = normalize_salesman(get_series(df, ["Salesman"], ""))

    branch_col = first_existing_col(df, ["Branch"])
    if branch_col:
        out["Branch"] = clean_text_series(df[branch_col])
        mask_blank = out["Branch"].isin(["", "nan", "None"])
        out.loc[mask_blank, "Branch"] = out.loc[mask_blank, "Salesman"].apply(assign_branch_from_salesman)
    else:
        out["Branch"] = out["Salesman"].apply(assign_branch_from_salesman)

    sales_div_col = first_existing_col(df, ["Sales Div.", "Sales_Div", "Sales Div", "Div"])
    if sales_div_col:
        out["Sales_Div"] = clean_text_series(df[sales_div_col]).apply(normalize_div)
    else:
        out["Sales_Div"] = out["Salesman"].astype(str).str[:2].apply(normalize_div)

    out["Customer_Code"] = clean_text_series(get_series(df, ["Customer Code", "Customer_Code", "Customer"], ""))
    out["Customer_Name"] = clean_text_series(get_series(df, ["Customer Name", "Customer_Name"], ""))

    # KHUSUS ELMOD01 & ELMOD02:
    # Customer_Name diganti dengan Delivery Address Name jika kolomnya tersedia.
    delivery_col = first_existing_col(df, ["Delivery Address Name", "Delivery_Address_Name"])
    if delivery_col is not None:
        delivery_address_name = clean_text_series(df[delivery_col])
        is_elmod = out["Salesman"].isin(ELMOD_SALESMEN)

        out["Customer_Name"] = np.where(
            is_elmod,
            delivery_address_name.replace({"": np.nan}).fillna(out["Customer_Name"]),
            out["Customer_Name"]
        )

        out["Customer_Name"] = clean_text_series(out["Customer_Name"])

    out["Prod_Code"] = clean_text_series(get_series(df, ["Prod. Code", "Prod_Code", "Prod Code", "Item Code"], ""))
    out["Brand_Name"] = clean_text_series(get_series(df, ["Brand Name", "Brand_Name", "Brand"], ""))
    out["Product_Category_Name"] = clean_text_series(
        get_series(df, ["Product Category Name", "Product_Category_Name", "Product Category"], "")
    )
    out["Prod_Name"] = clean_text_series(get_series(df, ["Prod. Name", "Prod_Name", "Product Name", "Item Name"], ""))

    quantity_col = first_existing_col(df, ["Quantity", "Invoiced Qty", "Invoiced_Qty"])
    if quantity_col:
        out["Quantity"] = safe_numeric(df[quantity_col])
    elif first_existing_col(df, ["Unit"]) and first_existing_col(df, ["Qty"]):
        out["Quantity"] = (
            safe_numeric(df[first_existing_col(df, ["Unit"])])
            + safe_numeric(df[first_existing_col(df, ["Qty"])])
        )
    else:
        out["Quantity"] = 0.0

    out["Net_Price"] = safe_numeric(get_series(df, ["Net Price", "Net_Price", "Nett Invoiced"], 0))

    out["Volume"] = safe_numeric(get_series(df, ["Volume", "Volume_Actual", "Line Volume", "Line_Volume"], 0))
    out["Weight"] = safe_numeric(get_series(df, ["Weight", "Weight_Actual", "Line Weight", "Line_Weight"], 0))

    out["Status"] = clean_text_series(get_series(df, ["Status"], ""))
    out["Invoice_Address"] = clean_text_series(get_series(df, ["Invoice Address", "Invoice_Address"], ""))
    out["Packing_Slip"] = clean_text_series(get_series(df, ["Packing Slip", "Packing_Slip"], ""))

    out = out.merge(pp_ref, on="Prod_Code", how="left")
    out = out.merge(pl_ref, on="Prod_Code", how="left")

    out["grup_sku"] = out["grup_sku"].fillna("")
    out["grup_sku_bogor"] = out["grup_sku_bogor"].fillna("")
    out["Product_Category"] = out["Product_Category"].fillna("")

    # =========================================================================
    # CUSTOM CATEGORY MAPPING: Panasonic/Sekai/Maspion Ex Fan
    # Diterapkan sebelum Product_Category dipakai sebagai fallback nama
    # dan sebelum assign_sku_from_row, supaya konsisten dengan Power Query.
    # =========================================================================
    out["Product_Category"] = out.apply(
        lambda row: apply_custom_category_mapping(
            row["Product_Category"], row["Branch"], row["Sales_Div"]
        ),
        axis=1,
    )

    mask_cat_blank = out["Product_Category_Name"].astype(str).str.strip().isin(["", "nan", "None"])
    out.loc[mask_cat_blank, "Product_Category_Name"] = out.loc[mask_cat_blank, "Product_Category"]

    out["sku"] = out.apply(assign_sku_from_row, axis=1)

    for c in FINAL_SALES_COLUMNS:
        if c not in out.columns:
            out[c] = np.nan

    out = out[FINAL_SALES_COLUMNS].copy()

    text_cols = [
        "Month_Invoice", "Type", "Invoice_Code", "Sales_Order_Return_Code", "References",
        "Branch", "Sales_Div", "Salesman", "Customer_Code", "Customer_Name",
        "Prod_Code", "Brand_Name", "Product_Category_Name", "Prod_Name",
        "sku", "Status", "Invoice_Address", "Packing_Slip",
    ]

    for col in text_cols:
        out[col] = clean_text_series(out[col])

    print(f"[OK] Invoice dataframe siap: {len(out):,} rows")
    print(f"     Min date: {out['Invoice_Date'].min()}")
    print(f"     Max date: {out['Invoice_Date'].max()}")

    return out


def load_sales_invoice_2026_from_xlsx(pp_ref, pl_ref) -> pd.DataFrame:
    print("\n[3/10] Membaca data invoice dari NEW_FILE_XLSX saja...")

    if not Path(NEW_FILE_XLSX).exists():
        raise FileNotFoundError(f"File invoice baru tidak ditemukan: {NEW_FILE_XLSX}")

    raw_new = pd.read_excel(NEW_FILE_XLSX)
    df_all = prepare_invoice_dataframe(raw_new, pp_ref, pl_ref)

    df_all["Invoice_Date"] = pd.to_datetime(df_all["Invoice_Date"], errors="coerce")
    df_all = df_all[df_all["Invoice_Date"].dt.year == 2026].copy()

    df_all["Salesman"] = normalize_salesman(df_all["Salesman"])
    df_all["Sales_Div"] = df_all["Sales_Div"].apply(normalize_div)
    df_all["Month_Invoice"] = month_invoice_from_date(df_all["Invoice_Date"])

    df_all = df_all.sort_values(["Invoice_Date", "Invoice_Code", "Prod_Code"]).reset_index(drop=True)

    print("\n[OK] Sales invoice 2026 dari XLSX selesai")
    print(f"Rows      : {len(df_all):,}")
    print(f"Min date  : {df_all['Invoice_Date'].min()}")
    print(f"Max date  : {df_all['Invoice_Date'].max()}")
    print(f"Net sales : {df_all['Net_Price'].sum():,.2f}")

    return df_all


# =============================================================================
# 5. TARGET 2026
# =============================================================================

def load_target_2026_final() -> pd.DataFrame:
    print("\n[4/10] Membaca target_2026...")

    target_data = PRODUCT_PIPAMAS

    df_target_raw = pd.read_excel(target_data, sheet_name="Target (belum_agen prj)")
    df_target_raw = df_target_raw[df_target_raw["Div"] != "ICI"].copy()

    month_cols = [c for c in df_target_raw.columns if str(c).startswith("Mo ")]
    id_cols = [c for c in df_target_raw.columns if c not in month_cols]

    df_target = df_target_raw.melt(
        id_vars=id_cols,
        value_vars=month_cols,
        var_name="Month_Label",
        value_name="Target",
    )

    df_target["Month_Num"] = df_target["Month_Label"].str.extract(r"(\d+)$").astype(int)
    df_target["Month"] = df_target["Month_Num"].map(MONTH_MAP)
    df_target = df_target.drop(columns=["Month_Label", "Month_Num"])
    df_target = df_target.dropna(subset=["Target"])
    df_target = df_target[df_target["Target"] != 0].copy()

    df_target = clean_colnames(df_target)
    df_target["Target"] = pd.to_numeric(df_target["Target"], errors="coerce").fillna(0)
    df_target["UOM"] = "Net Price"

    df_target = df_target[
        [
            "Branch", "Div", "Salesman", "Breakdown", "Breakdown_MEI_26",
            "Brand_Focus", "Month", "Target", "UOM",
        ]
    ].copy()

    print(f"[OK] Target non-ICI unpivot selesai: {len(df_target):,} rows")
    print(f"     Div tersisa: {sorted(df_target['Div'].dropna().unique())}")

    df_ici_raw = pd.read_excel(target_data, sheet_name="Target Cat (V_W)")

    brand_casing_fix = {
        "DULUX WTP": "Dulux WTP",
    }

    df_ici_raw["Brand"] = df_ici_raw["Brand"].astype(str).str.strip()
    df_ici_raw["Brand"] = df_ici_raw["Brand"].replace(brand_casing_fix)
    df_ici_raw = df_ici_raw[~df_ici_raw["Brand"].apply(is_cat_sku)].copy()

    ici_month_cols = [c for c in df_ici_raw.columns if str(c).startswith("Mo-")]
    ici_id_cols = ["Branch", "Div", "Salesman", "Brand", "Volume (Lt) /Weight (Kg)"]

    df_ici = df_ici_raw[ici_id_cols + ici_month_cols].melt(
        id_vars=ici_id_cols,
        value_vars=ici_month_cols,
        var_name="Month_Label",
        value_name="Target",
    )

    df_ici["Month_Num"] = df_ici["Month_Label"].str.extract(r"(\d+)$").astype(int)
    df_ici["Month"] = df_ici["Month_Num"].map(MONTH_MAP)
    df_ici = df_ici.drop(columns=["Month_Label", "Month_Num"])
    df_ici = df_ici.dropna(subset=["Target"])
    df_ici = df_ici[df_ici["Target"] != 0].copy()

    df_ici["UOM"] = np.where(
        df_ici["Brand"].apply(is_warnamu_sku),
        "Weight",
        "Volume",
    )

    brand_focus_map = {
        "Catylac": "Yes",
        "Catylac SC": "Yes",
        "Dulux": "Yes",
        "Dulux WTP": "Yes",
        "Maxilite": "No",
        "Warnamu": "No",
    }

    df_ici["Brand_Focus"] = df_ici["Brand"].map(brand_focus_map)

    unmapped = df_ici[df_ici["Brand_Focus"].isna()]["Brand"].unique()
    if len(unmapped) > 0:
        print(f"[WARN] Brand ICI belum ada di brand_focus_map: {list(unmapped)}")

    df_ici = df_ici.rename(columns={"Brand": "Breakdown"})
    df_ici["Breakdown_MEI_26"] = df_ici["Breakdown"]
    df_ici["Target"] = pd.to_numeric(df_ici["Target"], errors="coerce").fillna(0)

    df_ici = df_ici[
        [
            "Branch", "Div", "Salesman", "Breakdown", "Breakdown_MEI_26",
            "Brand_Focus", "Month", "Target", "UOM",
        ]
    ].copy()

    print(f"[OK] Target ICI Volume/Weight unpivot selesai: {len(df_ici):,} rows")
    print(df_ici["UOM"].value_counts().to_string())

    df_target_final = pd.concat([df_target, df_ici], ignore_index=True)

    df_target_final["Branch"] = clean_text_series(df_target_final["Branch"])
    df_target_final["Div"] = clean_text_series(df_target_final["Div"]).apply(normalize_div)
    df_target_final["Salesman"] = normalize_salesman(df_target_final["Salesman"])
    df_target_final["Breakdown"] = clean_text_series(df_target_final["Breakdown"])
    df_target_final["Breakdown_MEI_26"] = clean_text_series(df_target_final["Breakdown_MEI_26"])
    df_target_final["Brand_Focus"] = clean_text_series(df_target_final["Brand_Focus"])
    df_target_final["Month"] = clean_text_series(df_target_final["Month"])
    df_target_final["UOM"] = clean_text_series(df_target_final["UOM"])
    df_target_final["Target"] = pd.to_numeric(df_target_final["Target"], errors="coerce").fillna(0)

    df_target_final = df_target_final[~df_target_final["Breakdown"].apply(is_cat_sku)].copy()

    is_ici_target = df_target_final["Div"].astype(str).str.upper().isin(["IC", "ICI"])

    df_target_final.loc[
        is_ici_target & df_target_final["Breakdown"].apply(is_warnamu_sku),
        "UOM",
    ] = "Weight"

    df_target_final.loc[
        is_ici_target & ~df_target_final["Breakdown"].apply(is_warnamu_sku),
        "UOM",
    ] = "Volume"

    bad_ici_uom = df_target_final[
        is_ici_target & ~df_target_final["UOM"].isin(["Volume", "Weight"])
    ]

    if len(bad_ici_uom) > 0:
        raise ValueError("Masih ada ICI dengan UOM selain Volume/Weight di target_2026.")

    bad_cat = df_target_final[df_target_final["Breakdown"].apply(is_cat_sku)]
    if len(bad_cat) > 0:
        raise ValueError("Masih ada Breakdown CAT/cat di target_2026.")

    df_target_final["Month_Num"] = df_target_final["Month"].map({v: k for k, v in MONTH_MAP.items()})
    df_target_final["Month_Invoice"] = df_target_final["Month_Num"].apply(lambda x: f"{int(x):02d}-2026")
    df_target_final["Month_Date"] = pd.to_datetime(
        "01-" + df_target_final["Month_Invoice"],
        format="%d-%m-%Y",
        errors="coerce",
    )

    df_target_final = df_target_final[
        [
            "Month_Date", "Month_Invoice", "Month",
            "Branch", "Div", "Salesman",
            "Breakdown", "Breakdown_MEI_26",
            "Brand_Focus", "Target", "UOM",
        ]
    ].copy()

    print(f"\n[OK] Total target_2026 gabungan: {len(df_target_final):,} rows")
    print("UOM distribution:")
    print(df_target_final["UOM"].value_counts().to_string())
    print("\nDiv distribution:")
    print(df_target_final["Div"].value_counts().to_string())

    print("\n[VALIDATION] target_2026 ICI UOM:")
    print(
        df_target_final[df_target_final["Div"].isin(["ICI", "IC"])]["UOM"]
        .value_counts(dropna=False)
        .to_string()
    )

    print("\n[VALIDATION] target_2026 CAT rows:")
    print(df_target_final[df_target_final["Breakdown"].apply(is_cat_sku)].shape[0])

    return df_target_final


# =============================================================================
# 6. TARGET AO
# =============================================================================

def load_target_2026_ao() -> pd.DataFrame:
    print("\n[5/10] Membaca target_2026_ao dari sheet AO...")

    df_ao_raw = pd.read_excel(PRODUCT_PIPAMAS, sheet_name="AO", header=1)

    id_cols_ao = [c for c in df_ao_raw.columns if not str(c).startswith("Mo ")]
    df_ao = unpivot_target(df_ao_raw, id_cols_ao)
    df_ao = clean_colnames(df_ao)

    required = ["Branch", "Div", "Salesman", "Month", "Target"]
    missing = [c for c in required if c not in df_ao.columns]
    if missing:
        raise ValueError(f"Kolom AO tidak lengkap. Missing: {missing}")

    df_ao["Branch"] = clean_text_series(df_ao["Branch"])
    df_ao["Div"] = clean_text_series(df_ao["Div"])
    df_ao["Salesman"] = normalize_salesman(df_ao["Salesman"])
    df_ao["Month"] = clean_text_series(df_ao["Month"])
    df_ao["Target"] = pd.to_numeric(df_ao["Target"], errors="coerce").fillna(0)

    df_ao_grouped = (
        df_ao.groupby(["Branch", "Div", "Salesman", "Month"], as_index=False)["Target"]
        .sum()
    )

    df_ao_grouped["Month_Num"] = df_ao_grouped["Month"].map({v: k for k, v in MONTH_MAP.items()})
    df_ao_grouped["Month_Invoice"] = df_ao_grouped["Month_Num"].apply(lambda x: f"{int(x):02d}-2026")
    df_ao_grouped["Month_Date"] = pd.to_datetime(
        "01-" + df_ao_grouped["Month_Invoice"],
        format="%d-%m-%Y",
        errors="coerce",
    )

    df_ao_grouped = df_ao_grouped[
        ["Month_Date", "Month_Invoice", "Branch", "Div", "Salesman", "Month", "Target"]
    ].copy()

    print(f"[OK] Target AO siap: {len(df_ao_grouped):,} rows")
    print(f"Total Target AO: {df_ao_grouped['Target'].sum():,.0f}")

    return df_ao_grouped


# =============================================================================
# 7. BUILD DASHBOARD TABLES
# =============================================================================

def build_sales_invoice_dashboard(df_all: pd.DataFrame) -> pd.DataFrame:
    print("\n[6/10] Membuat sales_invoice_dashboard...")
    out = df_all[FINAL_SALES_COLUMNS].copy()
    print(f"[OK] sales_invoice_dashboard: {len(out):,} rows")
    return out


def build_summary_tables(df_all: pd.DataFrame) -> dict:
    print("\n[7/10] Membuat summary tables...")

    df = df_all.copy()
    df["Date"] = pd.to_datetime(df["Invoice_Date"]).dt.date
    df["Month_Date"] = pd.to_datetime(df["Invoice_Date"]).dt.to_period("M").dt.to_timestamp()
    df["Year"] = pd.to_datetime(df["Invoice_Date"]).dt.year
    df["Month"] = pd.to_datetime(df["Invoice_Date"]).dt.month

    daily_sales = (
        df.groupby(["Date"], as_index=False)
        .agg(
            Total_Sales=("Net_Price", "sum"),
            Total_Quantity=("Quantity", "sum"),
            Total_Volume=("Volume", "sum"),
            Total_Weight=("Weight", "sum"),
            Total_Rows=("Net_Price", "count"),
            Total_Invoice=("Invoice_Code", "nunique"),
        )
        .sort_values("Date")
    )
    daily_sales["DoD_Sales_Pct"] = daily_sales["Total_Sales"].pct_change() * 100

    monthly_sales = (
        df.groupby(["Year", "Month", "Month_Date", "Month_Invoice"], as_index=False)
        .agg(
            Total_Sales=("Net_Price", "sum"),
            Total_Quantity=("Quantity", "sum"),
            Total_Volume=("Volume", "sum"),
            Total_Weight=("Weight", "sum"),
            Total_Rows=("Net_Price", "count"),
            Total_Invoice=("Invoice_Code", "nunique"),
        )
        .sort_values(["Year", "Month"])
    )
    monthly_sales["MoM_Sales_Pct"] = monthly_sales["Total_Sales"].pct_change() * 100

    branch_daily_sales = (
        df.groupby(["Date", "Branch", "Sales_Div"], as_index=False)
        .agg(
            Total_Sales=("Net_Price", "sum"),
            Total_Quantity=("Quantity", "sum"),
            Total_Volume=("Volume", "sum"),
            Total_Weight=("Weight", "sum"),
            Total_Rows=("Net_Price", "count"),
            Total_Invoice=("Invoice_Code", "nunique"),
        )
        .sort_values(["Date", "Branch", "Sales_Div"])
    )

    salesman_daily_sales = (
        df.groupby(["Date", "Branch", "Sales_Div", "Salesman"], as_index=False)
        .agg(
            Total_Sales=("Net_Price", "sum"),
            Total_Quantity=("Quantity", "sum"),
            Total_Volume=("Volume", "sum"),
            Total_Weight=("Weight", "sum"),
            Total_Rows=("Net_Price", "count"),
            Total_Invoice=("Invoice_Code", "nunique"),
        )
        .sort_values(["Date", "Branch", "Sales_Div", "Salesman"])
    )

    sku_monthly_sales = (
        df.groupby(
            ["Year", "Month", "Month_Date", "Month_Invoice", "Branch", "Sales_Div", "Salesman", "sku"],
            as_index=False,
        )
        .agg(
            Total_Sales=("Net_Price", "sum"),
            Total_Quantity=("Quantity", "sum"),
            Total_Volume=("Volume", "sum"),
            Total_Weight=("Weight", "sum"),
            Total_Rows=("Net_Price", "count"),
            Total_Invoice=("Invoice_Code", "nunique"),
        )
        .sort_values(["Year", "Month", "Branch", "Sales_Div", "Salesman", "sku"])
    )

    print(f"[OK] daily_sales: {len(daily_sales):,} rows")
    print(f"[OK] monthly_sales: {len(monthly_sales):,} rows")
    print(f"[OK] branch_daily_sales: {len(branch_daily_sales):,} rows")
    print(f"[OK] salesman_daily_sales: {len(salesman_daily_sales):,} rows")
    print(f"[OK] sku_monthly_sales: {len(sku_monthly_sales):,} rows")

    return {
        TABLE_DAILY_SALES: daily_sales,
        TABLE_MONTHLY_SALES: monthly_sales,
        TABLE_BRANCH_DAILY_SALES: branch_daily_sales,
        TABLE_SALESMAN_DAILY_SALES: salesman_daily_sales,
        TABLE_SKU_MONTHLY_SALES: sku_monthly_sales,
    }


def build_sales_vs_target_monthly_dashboard(df_all: pd.DataFrame, target_2026: pd.DataFrame) -> pd.DataFrame:
    print("\n[8/10] Membuat sales_vs_target_monthly_dashboard...")

    if target_2026 is None or target_2026.empty:
        print("[WARN] Target 2026 kosong.")
        return pd.DataFrame()

    sales = df_all.copy()

    sales["Invoice_Date"] = pd.to_datetime(sales["Invoice_Date"], errors="coerce")
    sales["Invoice_Year"] = sales["Invoice_Date"].dt.year
    sales = sales[sales["Invoice_Year"] == 2026].copy()

    sales = sales[~sales["Branch"].apply(is_excluded_actual_target_branch)].copy()

    sales["Sales_Div"] = sales["Sales_Div"].replace({"IC": "ICI"})
    sales["sku"] = sales["sku"].astype(str).str.strip().str.lower()

    sales = sales[~sales["sku"].apply(is_cat_sku)].copy()
    sales["sku_key"] = sales["sku"].apply(norm_key)

    actual_base = (
        sales.groupby(
            ["Month_Invoice", "Branch", "Salesman", "Sales_Div", "sku_key"],
            as_index=False,
        )
        .agg(
            Total_Sales_NetPrice=("Net_Price", "sum"),
            Total_Sales_Volume=("Volume", "sum"),
            Total_Sales_Weight=("Weight", "sum"),
            Total_Quantity=("Quantity", "sum"),
            Total_Invoice=("Invoice_Code", "nunique"),
            sku=("sku", "first"),
        )
    )

    target = target_2026.copy()
    target = target[~target["Branch"].apply(is_excluded_target_branch)].copy()

    target["Div"] = target["Div"].replace({"IC": "ICI"})
    target["Breakdown"] = target["Breakdown"].astype(str).str.strip()
    target["sku_key"] = target["Breakdown"].apply(norm_key)
    target = target[~target["Breakdown"].apply(is_cat_sku)].copy()

    is_ici_target = target["Div"].astype(str).str.upper().isin(["IC", "ICI"])

    target.loc[
        is_ici_target & target["Breakdown"].apply(is_warnamu_sku),
        "UOM",
    ] = "Weight"

    target.loc[
        is_ici_target & ~target["Breakdown"].apply(is_warnamu_sku),
        "UOM",
    ] = "Volume"

    bad_ici_target = target[
        is_ici_target & ~target["UOM"].isin(["Volume", "Weight"])
    ]

    if len(bad_ici_target) > 0:
        raise ValueError("Target ICI masih punya UOM selain Volume/Weight.")

    target_agg = (
        target.groupby(
            ["Month_Invoice", "Branch", "Salesman", "Div", "sku_key", "UOM"],
            as_index=False,
        )
        .agg(
            Target_SKU=("Target", "sum"),
            Target_SKU_Name=("Breakdown", "first"),
            Brand_Focus=("Brand_Focus", "max"),
            Month_Date=("Month_Date", "max"),
        )
    )

    out = actual_base.merge(
        target_agg,
        how="outer",
        left_on=["Month_Invoice", "Branch", "Salesman", "Sales_Div", "sku_key"],
        right_on=["Month_Invoice", "Branch", "Salesman", "Div", "sku_key"],
    )

    out["Sales_Div"] = out["Sales_Div"].combine_first(out["Div"])
    out["sku"] = out["sku"].combine_first(out["Target_SKU_Name"])
    out["sku"] = out["sku"].astype(str).str.strip().str.lower()

    out = out[~out["sku"].apply(is_cat_sku)].copy()

    out["Brand_Focus"] = out["Brand_Focus"].fillna("")

    for col in [
        "Total_Sales_NetPrice",
        "Total_Sales_Volume",
        "Total_Sales_Weight",
        "Total_Quantity",
        "Total_Invoice",
        "Target_SKU",
    ]:
        out[col] = pd.to_numeric(out.get(col, 0), errors="coerce").fillna(0)

    out["UOM"] = out["UOM"].fillna("")

    is_ici_out = out["Sales_Div"].astype(str).str.upper().isin(["IC", "ICI"])

    out.loc[
        is_ici_out & out["sku"].apply(is_warnamu_sku),
        "UOM",
    ] = "Weight"

    out.loc[
        is_ici_out & ~out["sku"].apply(is_warnamu_sku),
        "UOM",
    ] = "Volume"

    out.loc[
        ~is_ici_out & out["UOM"].eq(""),
        "UOM",
    ] = "Net Price"

    out.loc[is_ici_out, "Total_Sales_NetPrice"] = 0

    out["Total_Achieve"] = np.select(
        [
            out["UOM"].eq("Net Price"),
            out["UOM"].eq("Volume"),
            out["UOM"].eq("Weight"),
        ],
        [
            out["Total_Sales_NetPrice"],
            out["Total_Sales_Volume"],
            out["Total_Sales_Weight"],
        ],
        default=0,
    )

    out["Gap"] = out["Total_Achieve"] - out["Target_SKU"]

    out["Achievement_Pct"] = np.where(
        out["Target_SKU"] > 0,
        out["Total_Achieve"] / out["Target_SKU"] * 100,
        np.nan,
    )

    out["Month_Date"] = out["Month_Date"].combine_first(
        pd.to_datetime(
            "01-" + out["Month_Invoice"],
            format="%d-%m-%Y",
            errors="coerce",
        )
    )

    bad_ici_output = out[
        is_ici_out & ~out["UOM"].isin(["Volume", "Weight"])
    ]

    if len(bad_ici_output) > 0:
        raise ValueError("Output sales_vs_target masih punya ICI dengan UOM selain Volume/Weight.")

    bad_cat_output = out[out["sku"].apply(is_cat_sku)]

    if len(bad_cat_output) > 0:
        raise ValueError("Output sales_vs_target masih punya sku CAT/cat.")

    final_cols = [
        "Month_Date",
        "Month_Invoice",
        "Branch",
        "Salesman",
        "Sales_Div",
        "sku",
        "sku_key",
        "Brand_Focus",
        "UOM",
        "Total_Sales_NetPrice",
        "Total_Sales_Volume",
        "Total_Sales_Weight",
        "Total_Achieve",
        "Target_SKU",
        "Gap",
        "Achievement_Pct",
        "Total_Quantity",
        "Total_Invoice",
    ]

    out = out[final_cols].copy()

    print(f"[OK] sales_vs_target_monthly_dashboard: {len(out):,} rows")
    print(f"Actual total achieve: {out['Total_Achieve'].sum():,.2f}")
    print(f"Target total: {out['Target_SKU'].sum():,.2f}")

    print("\n[VALIDATION] sales_vs_target ICI UOM distribution:")
    print(
        out[out["Sales_Div"].astype(str).str.upper().isin(["IC", "ICI"])]["UOM"]
        .value_counts(dropna=False)
        .to_string()
    )

    print("\n[VALIDATION] sales_vs_target CAT sku rows:")
    print(out[out["sku"].apply(is_cat_sku)].shape[0])

    return out


def build_sales_invoice_ao_flag(df_all: pd.DataFrame, target_ao: pd.DataFrame) -> pd.DataFrame:
    print("\n[9/10] Membuat sales_invoice_ao_flag...")

    sales = df_all.copy()

    sales["Invoice_Date"] = pd.to_datetime(sales["Invoice_Date"], errors="coerce")
    sales["Net_Price"] = pd.to_numeric(sales["Net_Price"], errors="coerce").fillna(0)
    sales["Salesman"] = normalize_salesman(sales["Salesman"])
    sales["Sales_Div"] = sales["Sales_Div"].astype(str).str.strip()
    sales["Branch"] = sales["Branch"].astype(str).str.strip()
    sales["Customer_Name"] = sales["Customer_Name"].astype(str).str.strip()
    sales["Month_Invoice"] = sales["Month_Invoice"].astype(str).str.strip()

    sales = sales[
        (sales["Invoice_Date"].dt.year == 2026)
        & (~sales["Branch"].isin(["Project", "Dist Kalimantan", "Dist Sumatera"]))
    ].copy()

    customer_monthly = (
        sales.groupby(
            ["Sales_Div", "Salesman", "Month_Invoice", "Customer_Name"],
            as_index=False,
        )
        .agg(Total_Net_Price=("Net_Price", "sum"))
    )

    customer_monthly["AO_Flag"] = 0

    customer_monthly.loc[
        (customer_monthly["Sales_Div"] == "PI")
        & (customer_monthly["Total_Net_Price"] >= 1_250_000),
        "AO_Flag",
    ] = 1

    customer_monthly.loc[
        (customer_monthly["Sales_Div"].isin(["IC", "ICI"]))
        & (customer_monthly["Total_Net_Price"] >= 2_000_000),
        "AO_Flag",
    ] = 1

    customer_monthly.loc[
        (customer_monthly["Sales_Div"].isin(["EL", "PP"]))
        & (customer_monthly["Total_Net_Price"] >= 2_500_000),
        "AO_Flag",
    ] = 1

    customer_monthly.loc[
        (customer_monthly["Sales_Div"] == "LM")
        & (customer_monthly["Total_Net_Price"] >= 1_250_000),
        "AO_Flag",
    ] = 1

    salesman_monthly = (
        customer_monthly.groupby(
            ["Sales_Div", "Salesman", "Month_Invoice"],
            as_index=False,
        )
        .agg(Total_AO=("AO_Flag", "sum"))
    )

    target_mapped = target_ao.copy()

    div_map = {
        "Elektrik": "EL",
        "Pipamas": "PI",
        "Pompa": "PP",
        "Pipa Pompa": "PP",
        "ICI": "ICI",
        "LM": "LM",
    }

    target_mapped["Sales_Div_Mapped"] = (
        target_mapped["Div"]
        .astype(str)
        .str.strip()
        .map(div_map)
        .fillna(target_mapped["Div"].astype(str).str.strip())
        .apply(normalize_div)
    )

    target_mapped["Salesman"] = normalize_salesman(target_mapped["Salesman"])

    month_num = target_mapped["Month"].astype(str).str.strip().map(MONTH_TO_NUM)
    target_mapped["Month_Mapped"] = month_num.fillna("") + "-2026"
    target_mapped = target_mapped[target_mapped["Month_Mapped"] != "-2026"].copy()

    target_mapped["Target"] = (
        pd.to_numeric(target_mapped["Target"], errors="coerce")
        .fillna(0)
        .astype("int64")
    )

    target_mapped = target_mapped.drop(
        columns=["Month_Invoice", "Month_Date"],
        errors="ignore",
    )

    out = salesman_monthly.merge(
        target_mapped,
        how="outer",
        left_on=["Salesman", "Sales_Div", "Month_Invoice"],
        right_on=["Salesman", "Sales_Div_Mapped", "Month_Mapped"],
    )

    out["Month_Invoice"] = out["Month_Invoice"].combine_first(out["Month_Mapped"])
    out["Sales_Div"] = out["Sales_Div"].combine_first(out["Sales_Div_Mapped"])
    out["Salesman"] = out["Salesman"].fillna("")

    out["Target_AO"] = pd.to_numeric(out["Target"], errors="coerce").fillna(0)
    out["Total_AO"] = pd.to_numeric(out["Total_AO"], errors="coerce").fillna(0)

    out["Pct_AO"] = np.where(
        out["Target_AO"] > 0,
        out["Total_AO"] / out["Target_AO"] * 100,
        np.nan,
    )

    out["Pct_AO"] = out["Pct_AO"].round(2)

    out["Month_Date"] = pd.to_datetime(
        "01-" + out["Month_Invoice"],
        format="%d-%m-%Y",
        errors="coerce",
    )

    final = out[
        [
            "Month_Date",
            "Month_Invoice",
            "Sales_Div",
            "Salesman",
            "Target_AO",
            "Total_AO",
            "Pct_AO",
        ]
    ].copy()

    final = final.sort_values(["Month_Date", "Sales_Div", "Salesman"]).reset_index(drop=True)

    print(f"[OK] sales_invoice_ao_flag siap: {len(final):,} rows")
    print(f"Total Target AO: {final['Target_AO'].sum():,.0f}")
    print(f"Total Actual AO: {final['Total_AO'].sum():,.0f}")

    return final


def build_incentive_dashboard(
    sales_vs_target: pd.DataFrame,
    sales_invoice_ao_flag: pd.DataFrame,
) -> pd.DataFrame:
    print("\n[9b/10] Membuat incentive_dashboard...")

    if sales_vs_target is None or sales_vs_target.empty:
        print("[WARN] sales_vs_target kosong.")
        return pd.DataFrame()

    df = sales_vs_target.copy()

    bf = df.copy()
    bf["Is_Brand_Focus"] = bf["Brand_Focus"].astype(str).str.strip().str.upper().eq("YES")
    bf["Is_Achieved_70"] = bf["Achievement_Pct"] >= 70

    bf_agg = (
        bf[bf["Is_Brand_Focus"]]
        .groupby(["Month_Date", "Month_Invoice", "Salesman"], as_index=False)
        .agg(
            Total_Brand_Focus=("sku_key", "nunique"),
            Achieve_Brand_Focus=("Is_Achieved_70", "sum"),
        )
    )

    sales_agg = (
        df.groupby(["Month_Date", "Month_Invoice", "Salesman"], as_index=False)
        .agg(
            Total_Sales_NetPrice=("Total_Sales_NetPrice", "sum"),
            Total_Sales_Volume=("Total_Sales_Volume", "sum"),
            Total_Sales_Weight=("Total_Sales_Weight", "sum"),
            Total_Achieve=("Total_Achieve", "sum"),
            Target_Achieve=("Target_SKU", "sum"),
        )
    )

    out = sales_agg.merge(
        bf_agg,
        on=["Month_Date", "Month_Invoice", "Salesman"],
        how="left",
    )

    out["Total_Brand_Focus"] = out["Total_Brand_Focus"].fillna(0)
    out["Achieve_Brand_Focus"] = out["Achieve_Brand_Focus"].fillna(0)

    out["Pct_Sales_Combined"] = np.where(
        out["Target_Achieve"] > 0,
        out["Total_Achieve"] / out["Target_Achieve"],
        np.nan,
    )

    out["Pct_Brand_Focus"] = np.where(
        out["Total_Brand_Focus"] > 0,
        out["Achieve_Brand_Focus"] / out["Total_Brand_Focus"],
        np.nan,
    )

    if sales_invoice_ao_flag is not None and not sales_invoice_ao_flag.empty:
        ao = (
            sales_invoice_ao_flag
            .groupby(["Month_Date", "Month_Invoice", "Salesman"], as_index=False)
            .agg(
                Total_AO=("Total_AO", "sum"),
                Target_AO=("Target_AO", "sum"),
            )
        )

        ao["Pct_AO"] = np.where(
            ao["Target_AO"] > 0,
            ao["Total_AO"] / ao["Target_AO"],
            np.nan,
        )

        out = out.merge(
            ao,
            on=["Month_Date", "Month_Invoice", "Salesman"],
            how="left",
        )
    else:
        out["Total_AO"] = np.nan
        out["Target_AO"] = np.nan
        out["Pct_AO"] = np.nan

    out["Total_AO"] = out["Total_AO"].fillna(0)
    out["Target_AO"] = out["Target_AO"].fillna(0)

    out["Overall_Achievement"] = out[
        ["Pct_Sales_Combined", "Pct_Brand_Focus", "Pct_AO"]
    ].mean(axis=1, skipna=True)

    print(f"[OK] incentive_dashboard: {len(out):,} rows")

    return out


# =============================================================================
# 8. BIGQUERY LOAD HELPERS
# =============================================================================

def create_dataset_if_missing(project_id: str, dataset_id: str, location: str = LOCATION):
    client = bigquery.Client(project=project_id, location=location, credentials=BQ_CREDENTIALS)
    full_dataset_id = f"{project_id}.{dataset_id}"

    try:
        client.get_dataset(full_dataset_id)
        print(f"[OK] Dataset exists: {full_dataset_id}")
    except NotFound:
        dataset = bigquery.Dataset(full_dataset_id)
        dataset.location = location
        client.create_dataset(dataset)
        print(f"[OK] Dataset created: {full_dataset_id}")


def delete_table_if_clustering_mismatch(
    client: bigquery.Client,
    table_id: str,
    clustering_fields: list[str] | None,
):
    requested = clustering_fields or []

    try:
        table = client.get_table(table_id)
    except NotFound:
        return

    existing = table.clustering_fields or []

    if existing != requested:
        print(f"[INFO] Existing clustering mismatch for {table_id}")
        print(f"       Existing : {existing}")
        print(f"       Requested: {requested}")
        print("       Deleting existing table first...")
        client.delete_table(table_id, not_found_ok=True)


def upload_dataframe_to_destination(
    df: pd.DataFrame,
    project_id: str,
    dataset_id: str,
    table_name: str,
    write_disposition: str = "WRITE_TRUNCATE",
    clustering_fields: list[str] | None = None,
):
    if df is None or df.empty:
        print(f"[SKIP] {project_id}.{dataset_id}.{table_name}: dataframe kosong.")
        return

    client = bigquery.Client(project=project_id, location=LOCATION, credentials=BQ_CREDENTIALS)
    table_id = f"{project_id}.{dataset_id}.{table_name}"

    existing_cluster_cols = []
    if clustering_fields:
        existing_cluster_cols = [c for c in clustering_fields if c in df.columns]

    delete_table_if_clustering_mismatch(client, table_id, existing_cluster_cols)

    job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
    )

    if existing_cluster_cols:
        job_config.clustering_fields = existing_cluster_cols

    print(f"\nUploading to {table_id} ...")
    print(f"Rows: {len(df):,}")

    job = client.load_table_from_dataframe(
        df,
        table_id,
        job_config=job_config,
    )
    job.result()

    table = client.get_table(table_id)

    print(f"[OK] Uploaded: {table_id}")
    print(f"Rows    : {table.num_rows:,}")
    print(f"Size MB : {round(table.num_bytes / 1024 / 1024, 2)}")


def upload_dataframe_to_all_projects(
    df: pd.DataFrame,
    table_name: str,
    write_disposition: str = "WRITE_TRUNCATE",
    clustering_fields: list[str] | None = None,
):
    for dest in BQ_DESTINATIONS:
        create_dataset_if_missing(dest["project_id"], dest["dataset_id"], LOCATION)

        upload_dataframe_to_destination(
            df=df,
            project_id=dest["project_id"],
            dataset_id=dest["dataset_id"],
            table_name=table_name,
            write_disposition=write_disposition,
            clustering_fields=clustering_fields,
        )


# =============================================================================
# 9. VALIDATION
# =============================================================================

def print_validation(df_all: pd.DataFrame):
    print("\n===============================================================================")
    print("VALIDATION - LOCAL DATAFRAME")
    print("===============================================================================")

    print(f"Rows              : {len(df_all):,}")
    print(f"Min Invoice_Date  : {df_all['Invoice_Date'].min()}")
    print(f"Max Invoice_Date  : {df_all['Invoice_Date'].max()}")
    print(f"Total Net_Price   : {df_all['Net_Price'].sum():,.2f}")
    print(f"Total Quantity    : {df_all['Quantity'].sum():,.2f}")
    print(f"Total Volume      : {df_all['Volume'].sum():,.2f}")
    print(f"Total Weight      : {df_all['Weight'].sum():,.2f}")

    print("\nRows by year:")
    by_year = (
        df_all.assign(Year=pd.to_datetime(df_all["Invoice_Date"]).dt.year)
        .groupby("Year", as_index=False)
        .agg(
            Rows=("Net_Price", "count"),
            Total_Sales=("Net_Price", "sum"),
        )
        .sort_values("Year")
    )
    print(by_year.to_string(index=False))


# =============================================================================
# 10. MAIN
# =============================================================================

def main():
    print("===============================================================================")
    print("DAILY SALES PERFORMANCE - BIGQUERY UPLOAD PIPELINE - XLSX 2026 ONLY")
    print("===============================================================================")

    pp_ref, pl_ref = load_product_references()

    df_all = load_sales_invoice_2026_from_xlsx(pp_ref, pl_ref)

    print_validation(df_all)

    target_2026 = load_target_2026_final()
    target_2026_ao = load_target_2026_ao()

    sales_invoice_dashboard = build_sales_invoice_dashboard(df_all)

    summary_tables = build_summary_tables(df_all)

    sales_vs_target_monthly_dashboard = build_sales_vs_target_monthly_dashboard(
        df_all,
        target_2026,
    )

    sales_invoice_ao_flag = build_sales_invoice_ao_flag(
        df_all,
        target_2026_ao,
    )

    incentive_dashboard = build_incentive_dashboard(
        sales_vs_target_monthly_dashboard,
        sales_invoice_ao_flag,
    )

    upload_dataframe_to_all_projects(
        df_all,
        table_name=TABLE_SALES_INVOICE,
        clustering_fields=["Branch", "Sales_Div", "Salesman", "sku"],
    )

    upload_dataframe_to_all_projects(
        sales_invoice_dashboard,
        table_name=TABLE_SALES_INVOICE_DASHBOARD,
        clustering_fields=["Branch", "Sales_Div", "Salesman", "sku"],
    )

    upload_dataframe_to_all_projects(
        target_2026,
        table_name=TABLE_TARGET_2026,
        clustering_fields=["Branch", "Div", "Salesman"],
    )

    upload_dataframe_to_all_projects(
        target_2026_ao,
        table_name=TABLE_TARGET_2026_AO,
        clustering_fields=["Branch", "Div", "Salesman"],
    )

    upload_dataframe_to_all_projects(
        sales_invoice_ao_flag,
        table_name=TABLE_SALES_INVOICE_AO_FLAG,
        clustering_fields=["Sales_Div", "Salesman"],
    )

    upload_dataframe_to_all_projects(
        summary_tables[TABLE_DAILY_SALES],
        table_name=TABLE_DAILY_SALES,
    )

    upload_dataframe_to_all_projects(
        summary_tables[TABLE_MONTHLY_SALES],
        table_name=TABLE_MONTHLY_SALES,
        clustering_fields=["Year", "Month"],
    )

    upload_dataframe_to_all_projects(
        summary_tables[TABLE_BRANCH_DAILY_SALES],
        table_name=TABLE_BRANCH_DAILY_SALES,
        clustering_fields=["Branch", "Sales_Div"],
    )

    upload_dataframe_to_all_projects(
        summary_tables[TABLE_SALESMAN_DAILY_SALES],
        table_name=TABLE_SALESMAN_DAILY_SALES,
        clustering_fields=["Branch", "Sales_Div", "Salesman"],
    )

    upload_dataframe_to_all_projects(
        summary_tables[TABLE_SKU_MONTHLY_SALES],
        table_name=TABLE_SKU_MONTHLY_SALES,
        clustering_fields=["Branch", "Sales_Div", "Salesman", "sku"],
    )

    upload_dataframe_to_all_projects(
        sales_vs_target_monthly_dashboard,
        table_name=TABLE_SALES_VS_TARGET_MONTHLY_DASHBOARD,
        clustering_fields=["Branch", "Sales_Div", "Salesman", "sku"],
    )

    upload_dataframe_to_all_projects(
        incentive_dashboard,
        table_name=TABLE_INCENTIVE_DASHBOARD,
        clustering_fields=["Salesman"],
    )

    print("\n===============================================================================")
    print("DONE")
    print("===============================================================================")

    print("\nTables uploaded to:")
    for dest in BQ_DESTINATIONS:
        print(f"- {dest['project_id']}.{dest['dataset_id']}")

    print("\nRecommended Looker Studio sources:")
    dest = BQ_DESTINATIONS[0]
    for table in [
        TABLE_SALES_INVOICE_DASHBOARD,
        TABLE_SALES_VS_TARGET_MONTHLY_DASHBOARD,
        TABLE_SALES_INVOICE_AO_FLAG,
        TABLE_TARGET_2026,
        TABLE_TARGET_2026_AO,
        TABLE_INCENTIVE_DASHBOARD,
        TABLE_DAILY_SALES,
        TABLE_BRANCH_DAILY_SALES,
        TABLE_SALESMAN_DAILY_SALES,
        TABLE_SKU_MONTHLY_SALES,
    ]:
        print(f"- {dest['project_id']}.{dest['dataset_id']}.{table}")


if __name__ == "__main__":
    main()
