# 1. Main Dashboard

!pip install google-cloud-bigquery pandas pyarrow openpyxl db-dtypes pandas-gbq -q

from google.colab import auth
auth.authenticate_user()

import re
import numpy as np
import pandas as pd
from pathlib import Path

from google.cloud import bigquery
from google.api_core.exceptions import NotFound


# =============================================================================
# 1. CONFIGURATION
# =============================================================================

LOCATION = "asia-southeast2"

BQ_DESTINATIONS = [
    {
        "project_id": "pipamas-v2",
        "dataset_id": "data",
    },
]

NEW_FILE_XLSX = "/content/Invoice - 9 Jul 2026 (1783603188880).xlsx"

PRODUCT_PIPAMAS = "/content/Target 2026.xlsx"
PRODUCT_LAINNYA = "/content/List Brand Name Active (1775788460191).xlsx"

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
    client = bigquery.Client(project=project_id, location=location)
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

    client = bigquery.Client(project=project_id, location=LOCATION)
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
    display(by_year)


# =============================================================================
# 10. MAIN
# =============================================================================

def main():
    print("===============================================================================")
    print("PIPAMAS V2 BIGQUERY UPLOAD PIPELINE - XLSX 2026 ONLY")
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
    print("- pipamas-v2.data.sales_invoice_dashboard")
    print("- pipamas-v2.data.sales_vs_target_monthly_dashboard")
    print("- pipamas-v2.data.sales_invoice_ao_flag")
    print("- pipamas-v2.data.target_2026")
    print("- pipamas-v2.data.target_2026_ao")
    print("- pipamas-v2.data.incentive_dashboard")
    print("- pipamas-v2.data.daily_sales")
    print("- pipamas-v2.data.branch_daily_sales")
    print("- pipamas-v2.data.salesman_daily_sales")
    print("- pipamas-v2.data.sku_monthly_sales")


main()

# 2. Monitoring Sales

# ============================================================
# INSTALL LIBRARY
# ============================================================
!pip install polars fastexcel openpyxl xlsxwriter google-cloud-bigquery pyarrow -q


# ============================================================
# IMPORT LIBRARY
# ============================================================
import re
import os
import polars as pl
import xlsxwriter

from google.colab import auth
from google.cloud import bigquery


# ============================================================
# DISPLAY SETTING
# ============================================================
pl.Config.set_tbl_cols(100)
pl.Config.set_tbl_width_chars(300)


# ============================================================
# AUTH GOOGLE CLOUD
# ============================================================
auth.authenticate_user()


# ============================================================
# CONFIG BIGQUERY
# ============================================================

BQ_DESTINATIONS = [
    {
        "project_id": "pipamas-v2",
        "dataset_id": "data",
    },
    # Kalau mau upload juga ke project business flow, aktifkan ini:
    # {
    #     "project_id": "pipamas-v3",
    #     "dataset_id": "data",
    # },
]

TABLE_SALES_MONITORING = "sales_monitoring"
TABLE_SALES_CUSTOMER_MONITORING = "sales_customer_monitoring"


# ============================================================
# FILE INPUT
# ============================================================
SO_FILE = "/content/SO Summary - 9 Jul 2026 (1783602991950).xlsx"
SI_FILE = "/content/Invoice Summary - 9 Jul 2026 (1783602893861).xlsx"


# ============================================================
# OUTPUT FILE
# ============================================================
OUTPUT_FILE = "/content/sales_monitoring_outputs.xlsx"


# ============================================================
# BUSINESS CONFIG
# ============================================================

# Closed / Cancel / Declined langsung dibuang dari SO monitoring.
EXCLUDE_CLOSED_CANCELLED_DECLINED_SO = True


# ============================================================
# FUNCTION UPLOAD POLARS TO BIGQUERY
# ============================================================
def upload_polars_to_bigquery(df: pl.DataFrame, table_name: str, write_disposition="WRITE_TRUNCATE"):
    temp_parquet_path = f"/content/_temp_{table_name}.parquet"

    df.write_parquet(temp_parquet_path)

    for dest in BQ_DESTINATIONS:
        project_id = dest["project_id"]
        dataset_id = dest["dataset_id"]

        table_full_id = f"{project_id}.{dataset_id}.{table_name}"

        client = bigquery.Client(project=project_id)

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
# EXPORT LOCAL EXCEL
# ============================================================
workbook = xlsxwriter.Workbook(OUTPUT_FILE)

sales_monitoring.write_excel(
    workbook=workbook,
    worksheet="sales_monitoring"
)

sales_customer_monitoring.write_excel(
    workbook=workbook,
    worksheet="sales_customer_monitoring"
)

so_activity.write_excel(
    workbook=workbook,
    worksheet="so_activity"
)

invoice_activity.write_excel(
    workbook=workbook,
    worksheet="invoice_activity"
)

payment_activity.write_excel(
    workbook=workbook,
    worksheet="payment_activity"
)

due_activity.write_excel(
    workbook=workbook,
    worksheet="due_activity"
)

past_due_activity.write_excel(
    workbook=workbook,
    worksheet="past_due_activity"
)

workbook.close()

print(f"File Excel berhasil dibuat: {OUTPUT_FILE}")


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
display(sales_monitoring.head())

print("Preview sales_customer_monitoring:")
display(sales_customer_monitoring.head())

print("Preview so_activity:")
display(so_activity.head())

print("Preview past_due_activity:")
display(past_due_activity.head())

# Business Flow

# ============================================================
# INSTALL LIBRARY
# ============================================================
!pip install polars fastexcel openpyxl xlsxwriter google-cloud-bigquery pyarrow -q


# ============================================================
# IMPORT LIBRARY
# ============================================================
import os
import re
import tempfile
import datetime as dt

import polars as pl

from google.colab import auth
from google.cloud import bigquery
from google.api_core.exceptions import NotFound


# ============================================================
# AUTH GOOGLE CLOUD
# ============================================================
auth.authenticate_user()


# ============================================================
# DISPLAY SETTING
# ============================================================
pl.Config.set_tbl_cols(120)
pl.Config.set_tbl_width_chars(320)


# ============================================================
# BIGQUERY CONFIG
# ============================================================
PROJECT_ID = "pipamas-v3"
DATASET_ID = "data"

BQ_LOCATION = None
WRITE_DISPOSITION = "WRITE_TRUNCATE"
TABLE_PREFIX = "o2c_"


# ============================================================
# FILE INPUT
# ============================================================

SO_FILE = "/content/SO Summary - 9 Jul 2026 (1783602991950).xlsx"
PACKING_FILE = "/content/Packing Summary - 9 Jul 2026 (1783602932474).xlsx"
INVOICE_FILE = "/content/Invoice Summary - 9 Jul 2026 (1783602893861).xlsx"


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

client = bigquery.Client(project=PROJECT_ID)

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

# 4. Tracker

# 1. Pastikan library terinstal
# !pip install gspread google-auth pandas-gbq google-cloud-bigquery

import pandas as pd
import gspread
from google.colab import auth
from google.auth import default
from google.cloud import bigquery

# 2. Autentikasi Google
auth.authenticate_user()
creds, _ = default()
gc = gspread.authorize(creds)

# --- KONFIGURASI ---
SPREADSHEET_ID = '18z9DJl2bB1eEaPwVJ01wm2lwrmnPYr-IqjW1d0v_en4'
PROJECT_ID     = "pipamas"
DATASET_ID     = "sales_data"
TABLE_ID       = "invoice_detail"

# --- PROSES SHEET 1: Tracking Salesman ---
print("Memulai update Tracking Salesman...")
spreadsheet = gc.open_by_key(SPREADSHEET_ID)
main_sheet = spreadsheet.worksheet('Tracking Salesman')

df_sales = pd.read_csv('/content/Visit Plan Report.csv')
# Konversi tanggal
df_sales['Date'] = pd.to_datetime(df_sales['Date'], dayfirst=True, format='mixed').dt.strftime('%Y-%m-%d')
df_sales = df_sales.fillna('')

main_sheet.clear()
data_sales = [df_sales.columns.values.tolist()] + df_sales.values.tolist()
main_sheet.update(range_name='A1', values=data_sales)
print("Data 'Tracking Salesman' berhasil diupdate ke Google Sheets.")

# --- PROSES SHEET 2: Invoiced Detail (BigQuery) ---
print("Memulai upload Invoiced Detail ke BigQuery...")

df_invoice = pd.read_csv('/content/Invoice Detail.csv')

# Pembersihan Nama Kolom (BigQuery tidak menerima spasi/titik)
df_invoice.columns = [c.replace(' ', '_').replace('.', '_').lower() for c in df_invoice.columns]

# Penanganan Tipe Data agar upload lebih stabil
# Mengonversi kolom angka agar tidak terjadi error type mismatch
numeric_cols = df_invoice.select_dtypes(include=['number']).columns
df_invoice[numeric_cols] = df_invoice[numeric_cols].apply(pd.to_numeric, errors='coerce')

# Mengisi data kosong
df_invoice = df_invoice.fillna('')

# Upload ke BigQuery
df_invoice.to_gbq(
    destination_table=f"{DATASET_ID}.{TABLE_ID}",
    project_id=PROJECT_ID,
    if_exists='replace'
)

print(f"Data berhasil di-upload ke BigQuery: {DATASET_ID}.{TABLE_ID}")
print("Semua proses selesai!")