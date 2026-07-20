

import os
import re
import warnings
import numpy as np
import pandas as pd

# BigQuery upload
from google.cloud import bigquery
try:
    from google.colab import auth
except Exception:
    auth = None

# ═══════════════════════════════════════════════════════════
# KONFIGURASI
# ═══════════════════════════════════════════════════════════
INPUT_FILE_PATH      = "/content/SO - 9 Jul 2026 (1783603653005).xlsx"

# BigQuery target
BQ_PROJECT_ID = "pipamas-v3"
BQ_DATASET_ID = "data"
BQ_LOCATION   = "asia-southeast2"  # Jakarta. Ganti jika dataset kamu beda lokasi.
OUTPUT_TO_BIGQUERY = True
BQ_WRITE_DISPOSITION = "WRITE_TRUNCATE"  # replace table setiap run

# Referensi untuk membuat ulang kolom Branch dan sku jika belum ada / ingin distandardisasi.
# Sesuaikan path ini dengan file yang kamu upload di Colab.
PRODUCT_PIPAMAS_PATH   = "/content/Target 2026.xlsx"
PRODUCT_LAINNYA_PATH   = "/content/List Brand Name Active (1775788460191).xlsx"
PRODUCT_PIPAMAS_SHEET  = "BREAKDOWN"
PRODUCT_PIPAMAS_HEADER = 1
PRODUCT_LAINNYA_SHEET  = "Report"

# True = selalu hitung ulang Branch dari Salesman dan sku dari referensi produk.
# Ini direkomendasikan agar COS/SPV tidak salah branch dan SKU PIPAMAS Bogor memakai GRUP SKU BOGOR.
RECALCULATE_BRANCH = True
RECALCULATE_SKU    = True

FREE_GIFT_CATEGORY   = "Free Gift"
FILTER_BRAND         = "PIPAMAS"   # isi None / "" jika tidak ingin filter brand
COHORT_MIN_THRESHOLD = 10
WINDOWS              = [7, 14, 28, 60, 90]
PRIMARY_WINDOW       = 28
HIGH_FREQ_GIFT_THRESHOLD = 5

# True = transaksi setelah gift lama tidak dihitung jika sudah ada gift baru sebelum window selesai.
# Default False agar output tetap mirip script v4 dan tidak terlalu agresif memotong revenue.
# Bias overlap tetap ditandai lewat Post_Overlap_28D.
CUTOFF_POST_WINDOW_AT_NEXT_GIFT = False

# Candidate kolom customer ID/code. Jika tidak ada, fallback ke Customer Name.
CUSTOMER_ID_CANDIDATES = [
    "Customer Code", "Customer ID", "Customer Id", "Customer No", "Customer",
    "customer_code", "customer_id", "Kode Customer", "Cust ID", "No Customer"
]

DATE_COL        = "Sales Order Date"
CATEGORY_COL    = "Product Category Name"
BRAND_COL       = "Brand Name"
TYPE_COL        = "Type"
NET_PRICE_COL   = "Net Price"
ORDER_CODE_COL  = "Sales Order/Return Code"
CUSTOMER_COL    = "Customer Name"
PRODUCT_COL     = "Prod. Name"
SKU_COL         = "sku"
BRANCH_COL      = "Branch"
SALESMAN_COL    = "Salesman"

BASE_REQUIRED_COLUMNS = [
    DATE_COL, CATEGORY_COL, BRAND_COL, TYPE_COL, NET_PRICE_COL,
    ORDER_CODE_COL, CUSTOMER_COL, PRODUCT_COL, SALESMAN_COL
]

# Kolom ini harus tersedia setelah tahap auto-enrichment.
REQUIRED_COLUMNS = BASE_REQUIRED_COLUMNS + [SKU_COL, BRANCH_COL]

PRODUCT_CODE_CANDIDATES = [
    "Prod. Code", "Product Code", "Item Code", "Code", "Prod Code",
    "prod_code", "product_code", "item_code"
]

PIPAMAS_BRANDS = {"mtn", "pipamas", "tangit"}
SALESMAN_RENAME_MAP = {
    "ICSLM80": "ICCOS08",
}

# ═══════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════
def read_input_file(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    return pd.read_csv(path, engine="c")


def require_columns(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Kolom wajib tidak ditemukan: {missing}")


def first_existing_col(df: pd.DataFrame, candidates: list[str]):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def normalize_salesman(df: pd.DataFrame, col: str = SALESMAN_COL) -> pd.DataFrame:
    if col not in df.columns:
        return df
    df[col] = (
        df[col]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace(SALESMAN_RENAME_MAP)
    )
    return df


def assign_branch(salesman) -> str:
    """
    Mapping branch berdasarkan Salesman sesuai logic sales invoice yang kamu berikan.
    COS/SPV diprioritaskan eksplisit agar tidak salah masuk branch dari suffix.
    """
    salesman = str(salesman).strip().upper()
    try:
        last2 = int(salesman[-2:])
    except Exception:
        last2 = None

    if salesman in ["ELCOS01", "PICOS01", "PICOS21", "PPCOS01"]:
        return "Bandung"
    elif salesman in ["ELCOS06", "PICOS06", "PPCOS06", "SPV06"]:
        return "Cirebon"
    elif salesman in ["ELCOS08", "ICCOS08", "PPCOS08", "ICSPV08", "PPSPV08"]:
        return "Bogor"
    elif salesman in ["ICCOS07", "PPCOS07", "ELCOS07", "PICOS07"]:
        return "Tasik"
    elif salesman in ["PISLP33", "PISLP35", "PISLP39", "PISLP51", "PISLP52", "PISLP53"]:
        return "Project"
    elif salesman == "PISLP37":
        return "Dist Sumatera"
    elif salesman == "PISLP38":
        return "Dist Kalimantan"
    elif last2 is None:
        return "Project"
    elif last2 < 20:
        return "Bandung"
    elif last2 < 30:
        return "PCK"
    elif last2 >= 60 and last2 < 70:
        return "Cirebon"
    elif last2 >= 70 and last2 < 80:
        return "Tasik"
    elif last2 >= 80 and last2 < 90:
        return "Bogor"
    else:
        return "Project"


def _clean_key(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper()


def load_product_references() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load referensi produk PIPAMAS dan brand lainnya. Jika file tidak ada, return dataframe kosong."""
    pipamas_ref = pd.DataFrame()
    lainnya_ref = pd.DataFrame()

    if PRODUCT_PIPAMAS_PATH and os.path.exists(PRODUCT_PIPAMAS_PATH):
        try:
            pipamas_ref = pd.read_excel(
                PRODUCT_PIPAMAS_PATH,
                sheet_name=PRODUCT_PIPAMAS_SHEET,
                header=PRODUCT_PIPAMAS_HEADER,
            )
            pipamas_ref.columns = pipamas_ref.columns.str.strip().str.lower()
            needed = ["eigen code", "grup sku", "grup sku bogor"]
            missing = [c for c in needed if c not in pipamas_ref.columns]
            if missing:
                warnings.warn(f"Referensi PIPAMAS tidak lengkap, kolom hilang: {missing}. SKU PIPAMAS akan fallback ke brand/category.")
                pipamas_ref = pd.DataFrame()
            else:
                pipamas_ref = pipamas_ref[needed].copy()
                pipamas_ref["__prod_code_key"] = _clean_key(pipamas_ref["eigen code"])
                pipamas_ref = pipamas_ref.rename(columns={
                    "grup sku": "__pipamas_grup_sku",
                    "grup sku bogor": "__pipamas_grup_sku_bogor",
                })
                pipamas_ref = pipamas_ref[["__prod_code_key", "__pipamas_grup_sku", "__pipamas_grup_sku_bogor"]].drop_duplicates("__prod_code_key")
                print(f"  ✓ Referensi PIPAMAS loaded: {len(pipamas_ref):,} SKU")
        except Exception as e:
            warnings.warn(f"Gagal load referensi PIPAMAS: {e}. SKU PIPAMAS akan fallback.")
            pipamas_ref = pd.DataFrame()
    else:
        warnings.warn(f"File referensi PIPAMAS tidak ditemukan: {PRODUCT_PIPAMAS_PATH}. SKU PIPAMAS akan fallback.")

    if PRODUCT_LAINNYA_PATH and os.path.exists(PRODUCT_LAINNYA_PATH):
        try:
            lainnya_ref = pd.read_excel(PRODUCT_LAINNYA_PATH, sheet_name=PRODUCT_LAINNYA_SHEET)
            if "Code" not in lainnya_ref.columns or "Product Category" not in lainnya_ref.columns:
                warnings.warn("Referensi brand lainnya tidak punya kolom Code/Product Category. SKU non-PIPAMAS akan fallback.")
                lainnya_ref = pd.DataFrame()
            else:
                lainnya_ref = lainnya_ref[["Code", "Product Category"]].copy()
                lainnya_ref["__prod_code_key"] = _clean_key(lainnya_ref["Code"])
                lainnya_ref = lainnya_ref.rename(columns={"Product Category": "__other_product_category"})
                lainnya_ref = lainnya_ref[["__prod_code_key", "__other_product_category"]].drop_duplicates("__prod_code_key")
                print(f"  ✓ Referensi brand lainnya loaded: {len(lainnya_ref):,} SKU")
        except Exception as e:
            warnings.warn(f"Gagal load referensi brand lainnya: {e}. SKU non-PIPAMAS akan fallback.")
            lainnya_ref = pd.DataFrame()
    else:
        warnings.warn(f"File referensi brand lainnya tidak ditemukan: {PRODUCT_LAINNYA_PATH}. SKU non-PIPAMAS akan fallback.")

    return pipamas_ref, lainnya_ref


def build_sku_from_row(row: pd.Series) -> str:
    brand = str(row.get(BRAND_COL, "")).strip()
    brand_lower = brand.lower()
    branch = str(row.get(BRANCH_COL, "")).strip()

    pipamas_bogor = row.get("__pipamas_grup_sku_bogor", np.nan)
    pipamas_other = row.get("__pipamas_grup_sku", np.nan)
    other_category = row.get("__other_product_category", np.nan)

    if brand_lower in PIPAMAS_BRANDS:
        result = pipamas_bogor if branch == "Bogor" else pipamas_other
        if pd.isna(result) or str(result).strip() == "":
            result = row.get(CATEGORY_COL, brand)
    else:
        result = other_category
        if pd.isna(result) or str(result).strip() == "":
            # Jika dataset sudah punya Product Category dari proses sebelumnya, pakai itu.
            result = row.get("Product Category", np.nan)
        if pd.isna(result) or str(result).strip() == "":
            result = row.get(CATEGORY_COL, brand)
        if pd.isna(result) or str(result).strip() == "":
            result = brand

    if pd.isna(result) or str(result).strip() == "":
        result = brand
    return str(result).strip().lower()


def enrich_branch_and_sku(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tambah/perbaiki Branch dan sku sebelum validasi kolom utama.
    - Branch dihitung dari Salesman.
    - sku dihitung dari referensi produk dan branch, sesuai logic PIPAMAS/Bogor vs selain Bogor.
    """
    df = df.copy()
    df = normalize_salesman(df, SALESMAN_COL)

    if RECALCULATE_BRANCH or BRANCH_COL not in df.columns:
        df[BRANCH_COL] = df[SALESMAN_COL].apply(assign_branch)
        df["Branch_Source"] = "Mapped from Salesman"
    else:
        df[BRANCH_COL] = df[BRANCH_COL].fillna("").astype(str).str.strip()
        missing_branch = df[BRANCH_COL].eq("")
        if missing_branch.any():
            df.loc[missing_branch, BRANCH_COL] = df.loc[missing_branch, SALESMAN_COL].apply(assign_branch)
        df["Branch_Source"] = np.where(missing_branch, "Filled from Salesman", "Existing Branch")

    if RECALCULATE_SKU or SKU_COL not in df.columns:
        product_code_col = first_existing_col(df, PRODUCT_CODE_CANDIDATES)
        if product_code_col is None:
            warnings.warn("Kolom product code tidak ditemukan. sku akan dibuat dari Product Category Name / Brand Name sebagai fallback.")
            df["__prod_code_key"] = ""
            pipamas_ref, lainnya_ref = pd.DataFrame(), pd.DataFrame()
        else:
            df["__prod_code_key"] = _clean_key(df[product_code_col])
            pipamas_ref, lainnya_ref = load_product_references()

        if not pipamas_ref.empty:
            df = df.merge(pipamas_ref, on="__prod_code_key", how="left")
        else:
            df["__pipamas_grup_sku"] = np.nan
            df["__pipamas_grup_sku_bogor"] = np.nan

        if not lainnya_ref.empty:
            df = df.merge(lainnya_ref, on="__prod_code_key", how="left")
        else:
            df["__other_product_category"] = np.nan

        df[SKU_COL] = df.apply(build_sku_from_row, axis=1)
        df["SKU_Source"] = np.where(
            df[BRAND_COL].astype(str).str.lower().isin(PIPAMAS_BRANDS),
            "PIPAMAS ref / fallback",
            "Other brand ref / fallback"
        )

        temp_cols = [
            "__prod_code_key", "__pipamas_grup_sku",
            "__pipamas_grup_sku_bogor", "__other_product_category"
        ]
        df = df.drop(columns=[c for c in temp_cols if c in df.columns])
    else:
        df[SKU_COL] = df[SKU_COL].fillna("").astype(str).str.strip().str.lower()
        empty_sku = df[SKU_COL].eq("")
        if empty_sku.any():
            warnings.warn(f"Ada {int(empty_sku.sum()):,} baris sku kosong. Baris tersebut fallback ke Brand Name.")
            df.loc[empty_sku, SKU_COL] = df.loc[empty_sku, BRAND_COL].astype(str).str.strip().str.lower()
        df["SKU_Source"] = "Existing sku"

    print(f"  ✓ Branch siap: {df[BRANCH_COL].notna().sum():,}/{len(df):,} rows")
    print(f"  ✓ sku siap   : {df[SKU_COL].notna().sum():,}/{len(df):,} rows")
    return df


def safe_mode(series: pd.Series):
    s = series.dropna().astype(str).str.strip()
    s = s[s != ""]
    if len(s) == 0:
        return ""
    return s.value_counts().index[0]


def join_unique(series: pd.Series, sep: str = " + ", max_items: int = 12) -> str:
    vals = []
    for x in series.dropna().astype(str):
        x = x.strip()
        if x and x not in vals:
            vals.append(x)
    if len(vals) > max_items:
        return sep.join(vals[:max_items]) + f" + ... ({len(vals)} items)"
    return sep.join(vals)


def clean_upper(x) -> str:
    return str(x).upper().strip()


def classify_gift_type(row: pd.Series) -> str:
    """
    Urutan penting: kategori spesifik dicek dulu.
    Ini memperbaiki risiko program channel/loyalty masuk ke Discount Program general.
    """
    name = clean_upper(row.get(PRODUCT_COL, ""))

    if re.search(r"HELM|TUMBLER|KAOS|PAYUNG|BLENDER|RICE COOKER|OVEN|SPANDUK|GLOSSY|MUG|TOPI|JAKET", name):
        return "Physical Gift"

    if "CASHBACK" in name:
        return "Cashback Incentive"

    if re.search(r"SETAHUN|REWARD|PUSAKA|SUPER BOOSTER|DOUBLE REWARD|TAHUNAN|LOYALTY", name):
        return "Loyalty Reward Program"

    if re.search(r"BANDUNG|TASIK|CIREBON|KARAWANG|BOGOR|JABAR|PARETO|NON PARETO|AREA|CABANG|DEPO", name) and \
       re.search(r"DISCOUNT|DISKON|POTONGAN|DISC", name):
        return "Channel Discount Program"

    if re.search(r"PROGRAM PIPA|PROGRAM FITTING|PROGRAM TALANG|PROGRAM PVC|PROGRAM HDPE|PROGRAM PIPAMAS", name):
        return "Product Sales Program"

    if re.search(r"DISCOUNT|DISKON|POTONGAN|SUPPORT DISC|TAMBAHAN DISCOUNT|EXTRA DISCOUNT|DISC", name):
        return "Discount Program"

    if re.search(r"SELL IN|SELL OUT|DISTRIBUTOR|DISTRIBUSI", name):
        return "Distributor Program"

    return "Other Program"


def rfm_qcut(series: pd.Series, labels: list[int], reverse: bool = False) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(0)
    if s.nunique() <= 1:
        mid = int(np.median(labels))
        return pd.Series([mid] * len(s), index=s.index).astype(int)

    ranked = s.rank(method="first", ascending=True)
    q = min(4, ranked.nunique())
    use_labels = labels[:q]
    if reverse:
        use_labels = sorted(use_labels, reverse=True)
    try:
        return pd.qcut(ranked, q=q, labels=use_labels, duplicates="drop").astype(int)
    except Exception:
        pct = ranked.rank(pct=True)
        if reverse:
            return pd.cut(pct, [0, .25, .5, .75, 1], labels=[4, 3, 2, 1], include_lowest=True).astype(int)
        return pd.cut(pct, [0, .25, .5, .75, 1], labels=[1, 2, 3, 4], include_lowest=True).astype(int)


def classify_value_segment(revenue_series: pd.Series) -> pd.Series:
    rev_positive = revenue_series[revenue_series > 0]
    if len(rev_positive) == 0:
        return pd.Series(["No Impact"] * len(revenue_series), index=revenue_series.index)
    q25 = rev_positive.quantile(0.25)
    q75 = rev_positive.quantile(0.75)
    return pd.Series(
        np.select(
            [revenue_series == 0, revenue_series >= q75, revenue_series >= q25],
            ["No Impact", "High Impact", "Mid Impact"],
            default="Low Impact"
        ),
        index=revenue_series.index
    )


def classify_marketing_response(row: pd.Series) -> str:
    before = row["Revenue_Before_28D"]
    after = row["Revenue_28D"]
    uplift = row["Revenue_Uplift_28D"]
    if row.get("Post_28D_Mature") == "Not Mature":
        return "Incomplete Post Window"
    if before == 0 and after == 0:
        return "No Baseline - No Response"
    if before == 0 and after > 0:
        return "Activated After Gift"
    if before > 0 and after == 0:
        return "No Repeat After Gift"
    if uplift > 0:
        return "Positive Uplift"
    if uplift < 0 and after > 0:
        return "Repeat but Lower Value"
    if uplift < 0:
        return "Negative Impact"
    return "No Change"


def sanitize_bigquery_column_names(columns) -> list[str]:
    """
    Standardisasi nama kolom agar valid di BigQuery.
    Contoh:
    - Prod. Name         -> Prod_Name
    - Revenue_Uplift_%  -> Revenue_Uplift_Pct
    - Sales Order Date  -> Sales_Order_Date

    Function ini juga handle duplicate column setelah disanitasi.
    """
    cleaned = []
    seen = {}

    for i, col in enumerate(columns):
        name = str(col).strip()

        # Buat nama lebih readable sebelum regex.
        name = name.replace("%", "Pct")
        name = name.replace("/", "_")
        name = name.replace("-", "_")
        name = name.replace(".", "_")
        name = name.replace("(", "")
        name = name.replace(")", "")

        # BigQuery safe characters: huruf, angka, underscore.
        name = re.sub(r"[^A-Za-z0-9_]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")

        # Nama kolom tidak boleh kosong.
        if not name:
            name = f"column_{i + 1}"

        # Lebih aman prefix jika diawali angka.
        if re.match(r"^[0-9]", name):
            name = f"col_{name}"

        # Max BigQuery column name 300 chars.
        name = name[:300]

        # Handle duplikat setelah sanitasi.
        base = name
        if base not in seen:
            seen[base] = 0
            cleaned.append(base)
        else:
            seen[base] += 1
            suffix = f"_{seen[base]}"
            cleaned.append(f"{base[:300-len(suffix)]}{suffix}")

    return cleaned


def clean_for_bigquery(data: pd.DataFrame) -> pd.DataFrame:
    """
    Rapikan dataframe agar aman diload ke BigQuery:
    1. Nama kolom disanitasi.
    2. Kolom date/datetime dipaksa menjadi datetime atau NULL.
    3. Numeric tetap numeric.
    4. Text/object dipaksa string nullable.
    5. Inf diganti NULL.
    """
    out = data.copy()

    # 1. Sanitasi nama kolom dulu.
    out.columns = sanitize_bigquery_column_names(out.columns)

    # 2. Replace inf lebih awal.
    out = out.replace([np.inf, -np.inf], np.nan)

    # 3. Paksa kolom tanggal menjadi datetime.
    date_keywords = [
        "date",
        "tanggal",
        "_dt",
        "created",
        "updated",
    ]

    for col in out.columns:
        col_lower = col.lower()
        if any(keyword in col_lower for keyword in date_keywords):
            out[col] = pd.to_datetime(out[col], errors="coerce")

    # 4. Rapikan tipe data non-date.
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            continue

        if pd.api.types.is_bool_dtype(out[col]):
            out[col] = out[col].astype("boolean")

        elif pd.api.types.is_numeric_dtype(out[col]):
            out[col] = pd.to_numeric(out[col], errors="coerce")

        else:
            out[col] = out[col].astype("string")
            out[col] = out[col].replace(
                ["nan", "NaN", "None", "NaT", "nat", ""],
                pd.NA
            )

    return out


def ensure_bigquery_dataset(client: bigquery.Client, dataset_id: str, location: str | None = None) -> None:
    dataset_ref = bigquery.Dataset(f"{client.project}.{dataset_id}")
    if location:
        dataset_ref.location = location
    try:
        client.get_dataset(dataset_ref)
        print(f"  ✓ Dataset tersedia: {client.project}.{dataset_id}")
    except Exception:
        client.create_dataset(dataset_ref, exists_ok=True)
        print(f"  ✓ Dataset dibuat: {client.project}.{dataset_id}")


def upload_table_to_bigquery(
    client,
    table_name: str,
    data: pd.DataFrame,
    dataset_id: str = BQ_DATASET_ID,
    write_disposition: str = BQ_WRITE_DISPOSITION
):
    """
    Upload dataframe ke BigQuery.
    Function ini sudah memanggil clean_for_bigquery(), jadi aman untuk:
    - kolom dengan titik/spasi/persen seperti Prod. Name atau Revenue_Uplift_%
    - kolom tanggal object yang campur NaT/None/string kosong
    - numeric NaN/inf
    """
    table_id = f"{BQ_PROJECT_ID}.{dataset_id}.{table_name}"
    out = clean_for_bigquery(data)

    job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        autodetect=True,
    )

    job = client.load_table_from_dataframe(out, table_id, job_config=job_config)
    job.result()

    print(f"  ✓ {table_id} — {len(out):,} rows, {len(out.columns)} cols")


# ═══════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 80)
    print("FREE GIFT PROGRAM IMPACT ANALYSIS — PIPAMAS v4.2 VALIDATED")
    print("=" * 80)

    # STEP 1 — Load, clean, filter
    print("\n[1/12] Membaca dataset...")
    df = read_input_file(INPUT_FILE_PATH)
    require_columns(df, BASE_REQUIRED_COLUMNS)

    # Tambahkan/standardisasi Branch dan sku terlebih dahulu.
    # Ini menjawab error kolom wajib sku/Branch belum tersedia pada dataset input.
    df = enrich_branch_and_sku(df)
    require_columns(df, REQUIRED_COLUMNS)

    customer_id_col = first_existing_col(df, CUSTOMER_ID_CANDIDATES)
    if customer_id_col:
        print(f"  ✓ Customer_Key memakai: {customer_id_col}")
    else:
        customer_id_col = CUSTOMER_COL
        warnings.warn("Customer Code/ID tidak ditemukan. Fallback ke Customer Name.")
        print("  ⚠ Customer_Key fallback ke Customer Name")

    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    df[NET_PRICE_COL] = pd.to_numeric(df[NET_PRICE_COL], errors="coerce").fillna(0)
    df = df.dropna(subset=[DATE_COL]).copy()

    df["Customer_Key"] = df[customer_id_col].fillna(df[CUSTOMER_COL]).astype(str).str.strip()
    df["Customer_Display"] = df[CUSTOMER_COL].fillna(df["Customer_Key"]).astype(str).str.strip()

    df_clean = df[
        (df[CATEGORY_COL] == FREE_GIFT_CATEGORY) |
        ((df[NET_PRICE_COL] >= 0) & (df[TYPE_COL] == "SALES INVOICE"))
    ].copy()

    if FILTER_BRAND:
        df_clean = df_clean[df_clean[BRAND_COL].astype(str).str.upper().str.strip() == FILTER_BRAND.upper()].copy()

    if df_clean.empty:
        raise ValueError("Data kosong setelah filter. Cek FREE_GIFT_CATEGORY / FILTER_BRAND / Type.")

    data_min = df_clean[DATE_COL].min()
    data_max = df_clean[DATE_COL].max()

    print(f"✓ Rows setelah filter  : {len(df_clean):,}")
    print(f"  Unique customers     : {df_clean['Customer_Key'].nunique():,}")
    print(f"  Date range           : {data_min.date()} → {data_max.date()}")

    # STEP 2 — Gift & non-gift split + classify Gift_Type
    print("\n[2/12] Split gift vs non-gift + Gift_Type...")
    gift_mask = df_clean[CATEGORY_COL] == FREE_GIFT_CATEGORY
    df_gift = df_clean[gift_mask].copy()
    df_non_gift = df_clean[~gift_mask].copy()

    if len(df_gift) == 0:
        raise ValueError(f"Kategori '{FREE_GIFT_CATEGORY}' tidak ditemukan.")
    if len(df_non_gift) == 0:
        raise ValueError("Transaksi non-gift kosong. Tidak bisa hitung repeat/uplift.")

    df_gift["Gift_Type"] = df_gift.apply(classify_gift_type, axis=1)
    print(f"✓ Gift rows     : {len(df_gift):,}")
    print(f"✓ Non-gift rows : {len(df_non_gift):,}")
    print(df_gift["Gift_Type"].value_counts().to_string())

    # STEP 3 — Gift events per Customer × Program × SKU × Date
    print("\n[3/12] Membuat gift event per customer x program x date...")
    gift_per_event = (
        df_gift
        .groupby(["Customer_Key", "Customer_Display", PRODUCT_COL, SKU_COL, DATE_COL], dropna=False)
        .agg(
            Gift_Count=(DATE_COL, "count"),
            Branch=(BRANCH_COL, safe_mode),
            Salesman=(SALESMAN_COL, safe_mode),
            Gift_Type=("Gift_Type", safe_mode),
        )
        .reset_index()
        .rename(columns={
            DATE_COL: "Gift_Date",
            PRODUCT_COL: "Gift_Product_Name",
            SKU_COL: "Gift_SKU",
        })
        .sort_values(["Customer_Key", "Gift_Date", "Gift_Product_Name"])
        .reset_index(drop=True)
    )

    gift_per_event["Gift_Event_ID"] = [f"GE{x:07d}" for x in range(1, len(gift_per_event) + 1)]
    gift_per_event["Gift_Cohort"] = gift_per_event["Gift_Date"].dt.to_period("M").astype(str)

    # Same-day multi program allocation. Ini membuat revenue tidak double-count di level total.
    same_day_count = (
        gift_per_event
        .groupby(["Customer_Key", "Gift_Date"])["Gift_Event_ID"]
        .nunique()
        .reset_index()
        .rename(columns={"Gift_Event_ID": "Same_Day_Program_Count"})
    )
    gift_per_event = gift_per_event.merge(same_day_count, on=["Customer_Key", "Gift_Date"], how="left")
    gift_per_event["Same_Day_Multi_Program_Flag"] = np.where(
        gift_per_event["Same_Day_Program_Count"] > 1,
        "Same Day Multi Program",
        "Single Program"
    )
    gift_per_event["Attribution_Weight"] = 1 / gift_per_event["Same_Day_Program_Count"].replace(0, 1)

    gift_freq_per_customer = (
        gift_per_event
        .groupby("Customer_Key")["Gift_Date"]
        .nunique()
        .reset_index()
        .rename(columns={"Gift_Date": "Gift_Frequency_Same_Customer"})
    )
    gift_per_event = gift_per_event.merge(gift_freq_per_customer, on="Customer_Key", how="left")

    # Previous/next gift date untuk overlap flag.
    gift_dates_unique = (
        gift_per_event[["Customer_Key", "Gift_Date"]]
        .drop_duplicates()
        .sort_values(["Customer_Key", "Gift_Date"])
    )
    gift_dates_unique["Previous_Gift_Date"] = gift_dates_unique.groupby("Customer_Key")["Gift_Date"].shift(1)
    gift_dates_unique["Next_Gift_Date"] = gift_dates_unique.groupby("Customer_Key")["Gift_Date"].shift(-1)
    gift_per_event = gift_per_event.merge(gift_dates_unique, on=["Customer_Key", "Gift_Date"], how="left")

    gift_per_event["Days_Since_Previous_Gift"] = (gift_per_event["Gift_Date"] - gift_per_event["Previous_Gift_Date"]).dt.days
    gift_per_event["Days_to_Next_Gift"] = (gift_per_event["Next_Gift_Date"] - gift_per_event["Gift_Date"]).dt.days
    gift_per_event["Baseline_Overlap_28D"] = np.where(
        gift_per_event["Previous_Gift_Date"].notna() &
        (gift_per_event["Previous_Gift_Date"] >= gift_per_event["Gift_Date"] - pd.Timedelta(days=PRIMARY_WINDOW)),
        "Baseline Overlap",
        "No Baseline Overlap"
    )
    gift_per_event["Post_Overlap_28D"] = np.where(
        gift_per_event["Next_Gift_Date"].notna() &
        (gift_per_event["Next_Gift_Date"] <= gift_per_event["Gift_Date"] + pd.Timedelta(days=PRIMARY_WINDOW)),
        "Post Overlap",
        "No Post Overlap"
    )

    for w in WINDOWS:
        gift_per_event[f"Pre_{w}D_Mature"] = np.where(
            gift_per_event["Gift_Date"] - pd.Timedelta(days=w) >= data_min,
            "Mature",
            "Not Mature"
        )
        gift_per_event[f"Post_{w}D_Mature"] = np.where(
            gift_per_event["Gift_Date"] + pd.Timedelta(days=w) <= data_max,
            "Mature",
            "Not Mature"
        )

    gift_event_table = (
        gift_per_event
        .groupby("Customer_Key")
        .agg(
            Customer_Display=("Customer_Display", safe_mode),
            Gift_Date=("Gift_Date", "min"),
            Gift_Count=("Gift_Count", "sum"),
            Branch=("Branch", safe_mode),
            Salesman=("Salesman", safe_mode),
            Gift_Type=("Gift_Type", safe_mode),
        )
        .reset_index()
    )
    gift_event_table["Gift_Cohort"] = gift_event_table["Gift_Date"].dt.to_period("M").astype(str)

    print(f"✓ Gift events total         : {len(gift_per_event):,}")
    print(f"  Unique customers          : {gift_per_event['Customer_Key'].nunique():,}")
    print(f"  Same-day multi-program    : {(gift_per_event['Same_Day_Multi_Program_Flag'] == 'Same Day Multi Program').sum():,} program rows")

    # STEP 4 — Post-event & before-event dataframes
    print("\n[4/12] Mapping transaksi before/after gift...")
    df_post_event = df_non_gift.merge(
        gift_per_event[[
            "Gift_Event_ID", "Customer_Key", "Gift_Product_Name", "Gift_SKU",
            "Gift_Date", "Gift_Type", "Branch", "Next_Gift_Date", "Attribution_Weight"
        ]],
        on="Customer_Key",
        how="inner",
        suffixes=("", "_Gift")
    )
    df_post_event["Days_After_Gift"] = (df_post_event[DATE_COL] - df_post_event["Gift_Date"]).dt.days
    df_post_event = df_post_event[df_post_event["Days_After_Gift"] > 0].copy()

    if CUTOFF_POST_WINDOW_AT_NEXT_GIFT:
        df_post_event = df_post_event[
            df_post_event["Next_Gift_Date"].isna() |
            (df_post_event[DATE_COL] < df_post_event["Next_Gift_Date"])
        ].copy()

    df_before_event = df_non_gift.merge(
        gift_per_event[["Gift_Event_ID", "Customer_Key", "Gift_Product_Name", "Gift_Date", "Attribution_Weight"]],
        on="Customer_Key",
        how="inner",
        suffixes=("", "_Gift")
    )
    df_before_event["Days_Before_Gift"] = (df_before_event["Gift_Date"] - df_before_event[DATE_COL]).dt.days
    df_before_event = df_before_event[
        (df_before_event["Days_Before_Gift"] > 0) &
        (df_before_event["Days_Before_Gift"] <= max(WINDOWS))
    ].copy()

    last_txn_before = (
        df_non_gift.merge(
            gift_per_event[["Gift_Event_ID", "Customer_Key", "Gift_Date"]].drop_duplicates(),
            on="Customer_Key",
            how="inner"
        )
        .assign(Days_Before=lambda x: (x["Gift_Date"] - x[DATE_COL]).dt.days)
        .query("Days_Before > 0")
        .groupby("Gift_Event_ID")["Days_Before"]
        .min()
        .reset_index()
        .rename(columns={"Days_Before": "Days_Since_Last_Txn_Before_Gift"})
    )
    gift_per_event = gift_per_event.merge(last_txn_before, on="Gift_Event_ID", how="left")

    print(f"✓ Post-event rows      : {len(df_post_event):,}")
    print(f"✓ Before-event rows    : {len(df_before_event):,}")

    # STEP 5 — Agregasi per window → page1_master
    print("\n[5/12] Agregasi window ke page1_master...")
    def agg_window_event(days: int):
        suffix = f"{days}D"
        sub = df_post_event[df_post_event["Days_After_Gift"] <= days].copy()
        if sub.empty:
            return pd.DataFrame({"Gift_Event_ID": []})
        return (
            sub.groupby("Gift_Event_ID")
            .agg(**{
                f"Revenue_{suffix}_Raw": (NET_PRICE_COL, "sum"),
                f"Transaction_Count_{suffix}": (ORDER_CODE_COL, "nunique"),
                f"SKU_Count_{suffix}": (SKU_COL, "nunique"),
                f"First_Repeat_Date_{suffix}": (DATE_COL, "min"),
                f"Last_Repeat_Date_{suffix}": (DATE_COL, "max"),
            })
            .reset_index()
        )

    page1_master = gift_per_event[[
        "Gift_Event_ID", "Customer_Key", "Customer_Display", "Gift_Product_Name", "Gift_SKU",
        "Gift_Type", "Gift_Date", "Gift_Count", "Branch", "Salesman", "Gift_Cohort",
        "Gift_Frequency_Same_Customer", "Days_Since_Last_Txn_Before_Gift",
        "Same_Day_Program_Count", "Same_Day_Multi_Program_Flag", "Attribution_Weight",
        "Previous_Gift_Date", "Next_Gift_Date", "Days_Since_Previous_Gift", "Days_to_Next_Gift",
        "Baseline_Overlap_28D", "Post_Overlap_28D",
        "Pre_28D_Mature", "Post_28D_Mature", "Pre_60D_Mature", "Post_60D_Mature", "Pre_90D_Mature", "Post_90D_Mature"
    ]].copy()

    for days in WINDOWS:
        page1_master = page1_master.merge(agg_window_event(days), on="Gift_Event_ID", how="left")

    before_event_agg = (
        df_before_event[df_before_event["Days_Before_Gift"] <= PRIMARY_WINDOW]
        .groupby("Gift_Event_ID")
        .agg(
            Revenue_Before_28D_Raw=(NET_PRICE_COL, "sum"),
            Txn_Before_28D=(ORDER_CODE_COL, "nunique"),
            SKU_Before_28D=(SKU_COL, "nunique"),
            First_Before_Txn_Date_28D=(DATE_COL, "min"),
            Last_Before_Txn_Date_28D=(DATE_COL, "max"),
        )
        .reset_index()
    )
    page1_master = page1_master.merge(before_event_agg, on="Gift_Event_ID", how="left")

    # Fill numeric cols
    fill_cols = [c for c in page1_master.columns if any(x in c for x in ["Revenue_", "Transaction_Count_", "SKU_Count_", "Txn_", "SKU_Before"])]
    page1_master[fill_cols] = page1_master[fill_cols].fillna(0)

    # Allocate revenue supaya same-day multi program tidak double-count di dashboard.
    for days in WINDOWS:
        suffix = f"{days}D"
        raw_col = f"Revenue_{suffix}_Raw"
        page1_master[f"Revenue_{suffix}"] = page1_master[raw_col] * page1_master["Attribution_Weight"]
        page1_master[f"Repeat_Flag_{suffix}"] = (page1_master[f"Transaction_Count_{suffix}"] > 0).astype(int)
        page1_master[f"AOV_{suffix}"] = np.where(
            page1_master[f"Transaction_Count_{suffix}"] > 0,
            page1_master[f"Revenue_{suffix}"] / page1_master[f"Transaction_Count_{suffix}"],
            0
        )

    page1_master["Revenue_Before_28D"] = page1_master["Revenue_Before_28D_Raw"] * page1_master["Attribution_Weight"]
    page1_master["AOV_Before_28D"] = np.where(
        page1_master["Txn_Before_28D"] > 0,
        page1_master["Revenue_Before_28D"] / page1_master["Txn_Before_28D"],
        0
    )

    page1_master["Revenue_Uplift_28D"] = page1_master["Revenue_28D"] - page1_master["Revenue_Before_28D"]
    page1_master["Revenue_Uplift_%"] = np.where(
        page1_master["Revenue_Before_28D"] > 0,
        page1_master["Revenue_Uplift_28D"] / page1_master["Revenue_Before_28D"] * 100,
        np.nan
    )

    # Uplift_Flag: No baseline dicek lebih dulu, supaya customer without before tidak menjadi Positive.
    page1_master["Uplift_Flag"] = np.select(
        [
            (page1_master["Revenue_Before_28D"] == 0) & (page1_master["Revenue_28D"] > 0),
            (page1_master["Revenue_Before_28D"] == 0) & (page1_master["Revenue_28D"] == 0),
            page1_master["Revenue_Uplift_28D"] > 0,
            page1_master["Revenue_Uplift_28D"] < 0,
        ],
        ["No Baseline - Activated", "No Baseline - No Response", "Positive", "Negative"],
        default="No Change"
    )

    page1_master["Baseline_Quality"] = np.select(
        [
            page1_master["Pre_28D_Mature"] != "Mature",
            page1_master["Revenue_Before_28D"] == 0,
        ],
        ["Incomplete Baseline Window (Exclude)", "No Baseline (Exclude)"],
        default="Valid Baseline (Include)"
    )

    page1_master["Customer_Type_For_Uplift"] = np.where(
        page1_master["Gift_Frequency_Same_Customer"] >= HIGH_FREQ_GIFT_THRESHOLD,
        "High Freq (Review Separately)",
        "Normal"
    )

    first_repeat_event = (
        df_post_event
        .groupby("Gift_Event_ID")["Days_After_Gift"]
        .min()
        .reset_index()
        .rename(columns={"Days_After_Gift": "Days_to_First_Repeat"})
    )
    page1_master = page1_master.merge(first_repeat_event, on="Gift_Event_ID", how="left")

    # Tetap pakai Impact_Segment style lama agar dashboard tidak rusak, tapi revenue-nya sudah allocated.
    page1_master["Impact_Segment"] = classify_value_segment(page1_master["Revenue_28D"])
    page1_master["Marketing_Response_Segment"] = page1_master.apply(classify_marketing_response, axis=1)

    page1_master["Official_Valid_28D_Flag"] = np.where(
        (page1_master["Baseline_Quality"] == "Valid Baseline (Include)") &
        (page1_master["Post_28D_Mature"] == "Mature"),
        "Recommended KPI Include",
        "Exclude / Review"
    )

    print(f"✓ page1_master rows    : {len(page1_master):,}")

    # STEP 6 — Bundle event summary: 1 customer x 1 gift date
    print("\n[6/12] Membuat bundle_event_summary untuk customer-event tanpa double counting...")
    agg_dict = {
        "Customer_Display": ("Customer_Display", safe_mode),
        "Gift_Product_Name": ("Gift_Product_Name", join_unique),
        "Gift_SKU": ("Gift_SKU", join_unique),
        "Gift_Type": ("Gift_Type", join_unique),
        "Branch": ("Branch", safe_mode),
        "Salesman": ("Salesman", safe_mode),
        "Gift_Count": ("Gift_Count", "sum"),
        "Same_Day_Program_Count": ("Same_Day_Program_Count", "max"),
        "Gift_Cohort": ("Gift_Cohort", safe_mode),
        "Gift_Frequency_Same_Customer": ("Gift_Frequency_Same_Customer", "max"),
        "Baseline_Quality": ("Baseline_Quality", safe_mode),
        "Pre_28D_Mature": ("Pre_28D_Mature", safe_mode),
        "Post_28D_Mature": ("Post_28D_Mature", safe_mode),
        "Baseline_Overlap_28D": ("Baseline_Overlap_28D", safe_mode),
        "Post_Overlap_28D": ("Post_Overlap_28D", safe_mode),
        "Days_to_First_Repeat": ("Days_to_First_Repeat", "min"),
    }
    for days in WINDOWS:
        suffix = f"{days}D"
        agg_dict[f"Revenue_{suffix}"] = (f"Revenue_{suffix}", "sum")
        agg_dict[f"Transaction_Count_{suffix}"] = (f"Transaction_Count_{suffix}", "max")
        agg_dict[f"Repeat_Flag_{suffix}"] = (f"Repeat_Flag_{suffix}", "max")
    agg_dict["Revenue_Before_28D"] = ("Revenue_Before_28D", "sum")
    agg_dict["Txn_Before_28D"] = ("Txn_Before_28D", "max")

    bundle_event_summary = (
        page1_master
        .groupby(["Customer_Key", "Gift_Date"], dropna=False)
        .agg(**agg_dict)
        .reset_index()
    )
    bundle_event_summary["Bundle_Event_ID"] = [f"BE{x:07d}" for x in range(1, len(bundle_event_summary) + 1)]
    bundle_event_summary["Revenue_Uplift_28D"] = bundle_event_summary["Revenue_28D"] - bundle_event_summary["Revenue_Before_28D"]
    bundle_event_summary["Revenue_Uplift_%"] = np.where(
        bundle_event_summary["Revenue_Before_28D"] > 0,
        bundle_event_summary["Revenue_Uplift_28D"] / bundle_event_summary["Revenue_Before_28D"] * 100,
        np.nan
    )
    bundle_event_summary["Uplift_Flag"] = np.select(
        [
            (bundle_event_summary["Revenue_Before_28D"] == 0) & (bundle_event_summary["Revenue_28D"] > 0),
            (bundle_event_summary["Revenue_Before_28D"] == 0) & (bundle_event_summary["Revenue_28D"] == 0),
            bundle_event_summary["Revenue_Uplift_28D"] > 0,
            bundle_event_summary["Revenue_Uplift_28D"] < 0,
        ],
        ["No Baseline - Activated", "No Baseline - No Response", "Positive", "Negative"],
        default="No Change"
    )
    bundle_event_summary["Impact_Segment"] = classify_value_segment(bundle_event_summary["Revenue_28D"])

    print(f"✓ bundle_event_summary rows: {len(bundle_event_summary):,}")

    # STEP 7 — Cohort aggregation
    print("\n[7/12] Cohort aggregation...")
    bundle_dedup_cohort = (
        bundle_event_summary
        .sort_values("Revenue_28D", ascending=False)
        .drop_duplicates(subset=["Customer_Key", "Gift_Cohort"])
    )
    cohort_agg = (
        bundle_dedup_cohort
        .groupby("Gift_Cohort")
        .agg(
            Customer_Unique=("Customer_Key", "nunique"),
            Event_Count=("Bundle_Event_ID", "nunique"),
            Revenue_28D=("Revenue_28D", "sum"),
            Revenue_Before_28D=("Revenue_Before_28D", "sum"),
            Customers_Repeat_7D=("Repeat_Flag_7D", "sum"),
            Customers_Repeat_14D=("Repeat_Flag_14D", "sum"),
            Customers_Repeat_28D=("Repeat_Flag_28D", "sum"),
            Customers_Repeat_60D=("Repeat_Flag_60D", "sum"),
            Customers_Repeat_90D=("Repeat_Flag_90D", "sum"),
        )
        .reset_index()
    )
    for col in ["7D", "14D", "28D", "60D", "90D"]:
        cohort_agg[f"Repeat_Rate_{col}_%"] = cohort_agg[f"Customers_Repeat_{col}"] / cohort_agg["Customer_Unique"] * 100
    cohort_agg["Revenue_Uplift_28D"] = cohort_agg["Revenue_28D"] - cohort_agg["Revenue_Before_28D"]
    cohort_agg["Revenue_Uplift_%"] = np.where(
        cohort_agg["Revenue_Before_28D"] > 0,
        cohort_agg["Revenue_Uplift_28D"] / cohort_agg["Revenue_Before_28D"] * 100,
        np.nan
    )
    cohort_agg["Cohort_Min_Size"] = np.where(
        cohort_agg["Customer_Unique"] >= COHORT_MIN_THRESHOLD,
        "Sufficient",
        f"Small (<{COHORT_MIN_THRESHOLD})"
    )
    cohort_agg["Chart_Color_Flag"] = np.where(
        cohort_agg["Cohort_Min_Size"] == "Sufficient",
        "Normal",
        "Small — Tidak Representatif"
    )

    page1_master = page1_master.merge(
        cohort_agg[["Gift_Cohort", "Cohort_Min_Size", "Chart_Color_Flag"]],
        on="Gift_Cohort",
        how="left"
    )
    bundle_event_summary = bundle_event_summary.merge(
        cohort_agg[["Gift_Cohort", "Cohort_Min_Size", "Chart_Color_Flag"]],
        on="Gift_Cohort",
        how="left"
    )

    rr_max = cohort_agg["Repeat_Rate_28D_%"].max() if len(cohort_agg) else 0
    print(f"✓ Max repeat rate cohort 28D: {rr_max:.1f}% {'✓' if rr_max <= 100 else '✗ MASIH > 100%'}")

    # STEP 8 — Negative uplift detail
    print("\n[8/12] Investigasi uplift negatif...")
    def categorize_negative_uplift(row):
        if row["Uplift_Flag"] != "Negative":
            return ""
        if row["Baseline_Quality"] != "Valid Baseline (Include)":
            return row["Baseline_Quality"]
        if row["Post_28D_Mature"] != "Mature":
            return "Post Window Not Mature"
        if row["Gift_Frequency_Same_Customer"] >= HIGH_FREQ_GIFT_THRESHOLD:
            return "High Gift Frequency - Review Separately"
        if row["Baseline_Overlap_28D"] == "Baseline Overlap" or row["Post_Overlap_28D"] == "Post Overlap":
            return "Gift Overlap - Review Separately"
        rev_28 = row["Revenue_28D"]
        rev_bef = row["Revenue_Before_28D"]
        if rev_28 > 0 and rev_bef > 0:
            drop_pct = (rev_bef - rev_28) / rev_bef * 100
            if drop_pct <= 30:
                return "Mild Drop (<30%)"
            if drop_pct <= 60:
                return "Moderate Drop (30-60%)"
            return "Severe Drop (>60%)"
        return "No Revenue After Gift"

    page1_master["Uplift_Negative_Reason"] = page1_master.apply(categorize_negative_uplift, axis=1)
    negative_summary = (
        page1_master[page1_master["Uplift_Flag"] == "Negative"]
        .groupby(["Gift_Type", "Uplift_Negative_Reason"], dropna=False)
        .agg(
            Event_Count=("Gift_Event_ID", "count"),
            Customer_Unique=("Customer_Key", "nunique"),
            Total_Revenue_Loss=("Revenue_Uplift_28D", "sum"),
            Avg_Gift_Freq=("Gift_Frequency_Same_Customer", "mean"),
        )
        .reset_index()
        .sort_values("Total_Revenue_Loss")
    )

    # STEP 9 — RFM Dynamic
    print("\n[9/12] Dynamic RFM...")
    snapshot_date = df_clean[DATE_COL].max()
    rfm_dynamic = (
        df_non_gift
        .groupby(["Customer_Key", "Customer_Display"], dropna=False)
        .agg(
            Last_Purchase_Date=(DATE_COL, "max"),
            First_Purchase_Date=(DATE_COL, "min"),
            Frequency=(ORDER_CODE_COL, "nunique"),
            Monetary=(NET_PRICE_COL, "sum"),
            Total_SKU_Bought=(SKU_COL, "nunique"),
            Branch=(BRANCH_COL, safe_mode),
        )
        .reset_index()
    )
    rfm_dynamic["Avg_Order_Value"] = np.where(rfm_dynamic["Frequency"] > 0, rfm_dynamic["Monetary"] / rfm_dynamic["Frequency"], 0)
    rfm_dynamic["Recency_Days"] = (snapshot_date - rfm_dynamic["Last_Purchase_Date"]).dt.days
    rfm_dynamic["R_Score"] = rfm_qcut(rfm_dynamic["Recency_Days"], [1, 2, 3, 4], reverse=True)
    rfm_dynamic["F_Score"] = rfm_qcut(rfm_dynamic["Frequency"], [1, 2, 3, 4], reverse=False)
    rfm_dynamic["M_Score"] = rfm_qcut(rfm_dynamic["Monetary"], [1, 2, 3, 4], reverse=False)
    rfm_dynamic["RFM_Total"] = rfm_dynamic["R_Score"] + rfm_dynamic["F_Score"] + rfm_dynamic["M_Score"]
    rfm_dynamic["Frequency"] = rfm_dynamic["Frequency"].astype(int)

    def rfm_segment(row):
        R, F, M = row["R_Score"], row["F_Score"], row["M_Score"]
        if R >= 4 and F >= 4 and M >= 4:
            return "Champions"
        if F >= 4 and M >= 3:
            return "Loyal Customers"
        if M >= 4:
            return "Big Spenders"
        if R >= 4:
            return "Recent Customers"
        if R >= 3 and F >= 3:
            return "Potential Loyalist"
        if R <= 2 and F >= 3:
            return "At Risk"
        if R == 1 and F <= 2:
            return "Lost Customers"
        return "Need Attention"

    rfm_dynamic["Segment"] = rfm_dynamic.apply(rfm_segment, axis=1)
    rfm_dynamic["Snapshot_Date"] = snapshot_date.date().isoformat()
    rfm_dynamic["Ever_Got_Gift"] = rfm_dynamic["Customer_Key"].isin(set(gift_event_table["Customer_Key"])).map({True: "Ya", False: "Tidak"})

    post_gift_per_customer = (
        page1_master
        .sort_values(["Customer_Key", "Gift_Date"], ascending=[True, False])
        .drop_duplicates(subset="Customer_Key")
        [[
            "Customer_Key", "Revenue_28D", "Transaction_Count_28D", "Impact_Segment",
            "Marketing_Response_Segment", "Gift_Date", "Gift_Type", "Gift_Product_Name",
            "Revenue_Before_28D", "Revenue_Uplift_28D", "Revenue_Uplift_%",
            "Days_to_First_Repeat", "Uplift_Flag", "Gift_Frequency_Same_Customer", "Baseline_Quality"
        ]]
        .rename(columns={
            "Revenue_28D": "Revenue_After_Gift_28D",
            "Transaction_Count_28D": "Txn_After_Gift_28D",
            "Gift_Date": "Latest_Gift_Date",
            "Gift_Type": "Latest_Gift_Type",
            "Gift_Product_Name": "Latest_Gift_Product_Name",
        })
    )
    rfm_dynamic = rfm_dynamic.merge(post_gift_per_customer, on="Customer_Key", how="left")

    fill_map = {
        "Revenue_After_Gift_28D": 0,
        "Revenue_Before_28D": 0,
        "Revenue_Uplift_28D": 0,
        "Txn_After_Gift_28D": 0,
        "Impact_Segment": "Tidak Dapat Gift",
        "Marketing_Response_Segment": "Tidak Dapat Gift",
        "Latest_Gift_Type": "Tidak Dapat Gift",
        "Latest_Gift_Product_Name": "Tidak Dapat Gift",
        "Latest_Gift_Date": "",
        "Uplift_Flag": "Tidak Dapat Gift",
        "Gift_Frequency_Same_Customer": 0,
        "Baseline_Quality": "Tidak Dapat Gift",
    }
    for col, val in fill_map.items():
        if col in rfm_dynamic.columns:
            rfm_dynamic[col] = rfm_dynamic[col].fillna(val)

    customer_profile = (
        df_non_gift
        .groupby("Customer_Key")
        .agg(
            Top_SKU_Name=(SKU_COL, safe_mode),
            Top_Category=(CATEGORY_COL, safe_mode),
            Top_Brand=(BRAND_COL, safe_mode),
        )
        .reset_index()
    )
    rfm_dynamic = rfm_dynamic.merge(customer_profile, on="Customer_Key", how="left")

    def recommend_action(row):
        seg = row["Segment"]
        gift = row["Ever_Got_Gift"]
        response = row.get("Marketing_Response_Segment", "")
        if gift == "Ya" and response in ["Negative Impact", "Repeat but Lower Value", "No Repeat After Gift"]:
            return "Evaluasi program — gift belum efektif"
        if seg == "Champions" and gift == "Tidak":
            return "Prioritas gift eksklusif"
        if seg == "Champions" and gift == "Ya":
            return "Pertahankan — monitor value after gift"
        if seg == "Loyal Customers" and gift == "Tidak":
            return "Gift untuk apresiasi loyalitas"
        if seg == "Loyal Customers" and gift == "Ya":
            return "Monitor — sudah loyal & dapat gift"
        if seg == "Lost Customers" and gift == "Ya":
            return "Butuh pendekatan non-gift (gift tidak cukup)"
        if seg == "Lost Customers" and gift == "Tidak":
            return "Coba win-back campaign dengan gift"
        if seg == "At Risk" and gift == "Tidak":
            return "Coba gift untuk retensi segera"
        if seg == "At Risk" and gift == "Ya":
            return "Evaluasi — gift tidak mencegah churn"
        if seg == "Potential Loyalist" and gift == "Tidak":
            return "Gift untuk konversi ke Loyal"
        if seg == "Potential Loyalist" and gift == "Ya":
            return "Monitor konversi ke Loyal"
        if seg == "Big Spenders" and gift == "Tidak":
            return "Gift premium untuk high spender"
        if seg == "Recent Customers":
            return "Nurture — terlalu baru untuk gift"
        if seg == "Need Attention" and gift == "Tidak":
            return "Gift untuk reaktivasi"
        if seg == "Need Attention" and gift == "Ya":
            return "Re-evaluasi efektivitas gift"
        return "Monitor"

    rfm_dynamic["Next_Action"] = rfm_dynamic.apply(recommend_action, axis=1)
    rfm_dynamic["Last_Purchase_Date"] = pd.to_datetime(rfm_dynamic["Last_Purchase_Date"])
    rfm_dynamic["Latest_Gift_Date_dt"] = pd.to_datetime(rfm_dynamic["Latest_Gift_Date"].replace("", pd.NaT), errors="coerce")
    rfm_dynamic["Days_After_Gift_to_Churn"] = np.where(
        (rfm_dynamic["Ever_Got_Gift"] == "Ya") & rfm_dynamic["Latest_Gift_Date_dt"].notna(),
        (rfm_dynamic["Last_Purchase_Date"] - rfm_dynamic["Latest_Gift_Date_dt"]).dt.days,
        np.nan
    )
    rfm_dynamic.drop(columns=["Latest_Gift_Date_dt"], inplace=True)

    lost_after_gift = rfm_dynamic[
        (rfm_dynamic["Ever_Got_Gift"] == "Ya") &
        (rfm_dynamic["Segment"].isin(["Lost Customers", "At Risk"]))
    ][[
        "Customer_Key", "Customer_Display", "Branch", "Segment", "Recency_Days",
        "Frequency", "Monetary", "Latest_Gift_Type", "Latest_Gift_Date",
        "Revenue_After_Gift_28D", "Revenue_Before_28D", "Uplift_Flag",
        "Days_After_Gift_to_Churn", "Impact_Segment", "Marketing_Response_Segment", "Next_Action"
    ]].sort_values("Days_After_Gift_to_Churn").copy()

    print(f"✓ rfm_dynamic rows     : {rfm_dynamic['Customer_Key'].nunique():,}")

    # STEP 10 — Check Cashback
    print("\n[10/13] Membuat tabel check_cashback...")
    so_cashback = df.copy()

    if FILTER_BRAND:
        so_cashback = so_cashback[
            so_cashback[BRAND_COL].astype(str).str.upper().str.strip() == FILTER_BRAND.upper()
        ].copy()

    free_gift_cashback = so_cashback[so_cashback[CATEGORY_COL] == FREE_GIFT_CATEGORY].copy()
    free_gift_so = free_gift_cashback[ORDER_CODE_COL].dropna().unique().tolist()

    so_cashback = so_cashback[so_cashback[ORDER_CODE_COL].isin(free_gift_so)].copy()

    # Total nilai SO (semua baris berbayar di order itu, bukan hanya free
    # gift) — basis pembanding untuk discount_pct.
    order_sales_total = (
        so_cashback
        .groupby([DATE_COL, ORDER_CODE_COL, CUSTOMER_COL], as_index=False)
        .agg(
            Branch=(BRANCH_COL, safe_mode),
            total_sales=(NET_PRICE_COL, lambda x: x[x > 0].sum()),
        )
    )

    # Baris output HANYA dari kategori Free Gift — produk berbayar tidak
    # ikut jadi baris. Dipisah per Prod. Name: kalau 1 SO punya 2 free gift
    # dengan Prod. Name berbeda, sebelumnya net price keduanya digabung jadi
    # satu angka lalu di-merge ke tiap nama produk — hasilnya total_discount
    # yang sama persis muncul dobel untuk 2 produk berbeda (double count).
    # Sekarang tiap free gift dapat total_discount miliknya sendiri.
    check_cashback = (
        free_gift_cashback
        .groupby([DATE_COL, ORDER_CODE_COL, CUSTOMER_COL, PRODUCT_COL], as_index=False)
        .agg(total_discount=(NET_PRICE_COL, lambda x: abs(x[x < 0].sum())))
    )

    check_cashback = check_cashback.merge(
        order_sales_total,
        on=[DATE_COL, ORDER_CODE_COL, CUSTOMER_COL],
        how="left",
    )

    check_cashback["discount_pct"] = np.where(
        check_cashback["total_sales"] > 0,
        check_cashback["total_discount"] / check_cashback["total_sales"],
        np.nan,
    )

    check_cashback = check_cashback[[
        DATE_COL,
        BRANCH_COL,
        PRODUCT_COL,
        ORDER_CODE_COL,
        CUSTOMER_COL,
        "total_sales",
        "total_discount",
        "discount_pct",
    ]]

    print(f"✓ check_cashback rows  : {len(check_cashback):,}")

    # STEP 11 — KPI summaries
    print("\n[11/13] KPI summary...")
    def calc_uplift_summary(label, mask, data=bundle_event_summary):
        sub = data[mask].copy()
        before = sub["Revenue_Before_28D"].sum()
        after = sub["Revenue_28D"].sum()
        net = after - before
        pct = net / before * 100 if before > 0 else np.nan
        return {
            "Uplift_Version": label,
            "Event_Count": len(sub),
            "Customer_Unique": sub["Customer_Key"].nunique(),
            "Revenue_Before": before,
            "Revenue_After": after,
            "Net_Uplift_Rp": net,
            "Net_Uplift_Pct": round(pct, 2) if not np.isnan(pct) else None,
        }

    b = bundle_event_summary
    mask_all = pd.Series(True, index=b.index)
    mask_valid = b["Baseline_Quality"] == "Valid Baseline (Include)"
    mask_mature = (b["Pre_28D_Mature"] == "Mature") & (b["Post_28D_Mature"] == "Mature")
    mask_no_overlap = (b["Baseline_Overlap_28D"] == "No Baseline Overlap") & (b["Post_Overlap_28D"] == "No Post Overlap")
    mask_normal_freq = b["Gift_Frequency_Same_Customer"] < HIGH_FREQ_GIFT_THRESHOLD

    kpi_uplift_summary = pd.DataFrame([
        calc_uplift_summary("(A) All Bundle Events", mask_all),
        calc_uplift_summary("(B) Valid Baseline Only", mask_valid),
        calc_uplift_summary("(C) RECOMMENDED - Valid Baseline + Mature Window", mask_valid & mask_mature),
        calc_uplift_summary("(D) Strict - Valid + Mature + No Overlap + Normal Freq", mask_valid & mask_mature & mask_no_overlap & mask_normal_freq),
        calc_uplift_summary("(E) Diagnostic - Positive Only", mask_valid & mask_mature & (b["Uplift_Flag"] == "Positive")),
    ])

    def calc_repeat_summary(label, mask, data=bundle_event_summary):
        sub = data[mask].copy()
        out = {
            "Repeat_Version": label,
            "Event_Count": len(sub),
            "Customer_Unique": sub["Customer_Key"].nunique(),
        }
        for suffix in ["7D", "14D", "28D", "60D", "90D"]:
            n = sub[f"Repeat_Flag_{suffix}"].sum() if len(sub) else 0
            out[f"Repeat_Events_{suffix}"] = n
            out[f"Repeat_Rate_{suffix}_%"] = n / len(sub) * 100 if len(sub) else np.nan
        out["Revenue_28D"] = sub["Revenue_28D"].sum()
        return out

    kpi_repeat_summary = pd.DataFrame([
        calc_repeat_summary("(A) All Bundle Events", mask_all),
        calc_repeat_summary("(B) RECOMMENDED - Mature Post 28D Only", b["Post_28D_Mature"] == "Mature"),
        calc_repeat_summary("(C) Mature + No Post Overlap", (b["Post_28D_Mature"] == "Mature") & (b["Post_Overlap_28D"] == "No Post Overlap")),
        calc_repeat_summary("(D) Strict - Mature + No Overlap + Normal Freq", mask_mature & mask_no_overlap & mask_normal_freq),
    ])

    print(kpi_uplift_summary.to_string(index=False))

    # STEP 12 — Control group diagnostic
    print("\n[12/13] Control group comparison...")
    control_group_comparison = (
        rfm_dynamic
        .groupby(["Segment", "Ever_Got_Gift"])
        .agg(
            Customer_Count=("Customer_Key", "nunique"),
            Avg_Frequency=("Frequency", "mean"),
            Avg_Monetary=("Monetary", "mean"),
            Avg_Recency_Days=("Recency_Days", "mean"),
            Avg_RFM_Total=("RFM_Total", "mean"),
        )
        .reset_index()
        .round(2)
    )

    gift_vals = control_group_comparison[control_group_comparison["Ever_Got_Gift"] == "Ya"].set_index("Segment")
    non_gift_vals = control_group_comparison[control_group_comparison["Ever_Got_Gift"] == "Tidak"].set_index("Segment")

    delta_rows = []
    for seg in gift_vals.index.intersection(non_gift_vals.index):
        g = gift_vals.loc[seg]
        ng = non_gift_vals.loc[seg]
        delta_rows.append({
            "Segment": seg,
            "Delta_Avg_Frequency": round(g["Avg_Frequency"] - ng["Avg_Frequency"], 2),
            "Delta_Avg_Monetary": round(g["Avg_Monetary"] - ng["Avg_Monetary"], 2),
            "Delta_Avg_Recency_Days": round(g["Avg_Recency_Days"] - ng["Avg_Recency_Days"], 2),
            "Interpretation": "Gift recipients lebih aktif" if g["Avg_Frequency"] > ng["Avg_Frequency"] else "Non-gift recipients sama/lebih aktif",
            "Causal_Validity_Note": "Diagnostic only, bukan bukti sebab-akibat."
        })
    control_group_delta = pd.DataFrame(delta_rows)

    # STEP 13 — Diagnostic & upload
    print("\n[13/13] Diagnostic final...")
    top_loss_events = (
        bundle_event_summary[bundle_event_summary["Uplift_Flag"] == "Negative"]
        .sort_values("Revenue_Uplift_28D")
        .head(50)
        .copy()
    )

    data_quality_summary = pd.DataFrame([
        {"Metric": "Rows processed", "Value": len(df_clean)},
        {"Metric": "Missing Branch after enrichment", "Value": int(df_clean[BRANCH_COL].isna().sum() + df_clean[BRANCH_COL].astype(str).str.strip().eq("").sum())},
        {"Metric": "Missing sku after enrichment", "Value": int(df_clean[SKU_COL].isna().sum() + df_clean[SKU_COL].astype(str).str.strip().eq("").sum())},
        {"Metric": "Gift program rows", "Value": len(df_gift)},
        {"Metric": "Program-level gift events", "Value": len(page1_master)},
        {"Metric": "Bundle-level gift events", "Value": len(bundle_event_summary)},
        {"Metric": "Unique gift customers", "Value": bundle_event_summary["Customer_Key"].nunique()},
        {"Metric": "Same-day multi-program bundle events", "Value": int((bundle_event_summary["Same_Day_Program_Count"] > 1).sum())},
        {"Metric": "Baseline overlap 28D bundle events", "Value": int((bundle_event_summary["Baseline_Overlap_28D"] == "Baseline Overlap").sum())},
        {"Metric": "Post overlap 28D bundle events", "Value": int((bundle_event_summary["Post_Overlap_28D"] == "Post Overlap").sum())},
        {"Metric": "Valid baseline bundle events", "Value": int((bundle_event_summary["Baseline_Quality"] == "Valid Baseline (Include)").sum())},
        {"Metric": "Post 28D mature bundle events", "Value": int((bundle_event_summary["Post_28D_Mature"] == "Mature").sum())},
    ])

    total_events = len(bundle_event_summary)
    total_cust = bundle_event_summary["Customer_Key"].nunique()
    total_rev_28D = float(bundle_event_summary["Revenue_28D"].sum())
    total_rev_bef = float(bundle_event_summary["Revenue_Before_28D"].sum())
    total_uplift = total_rev_28D - total_rev_bef

    print("\n" + "=" * 60)
    print("DIAGNOSTIC & VALIDASI")
    print("=" * 60)
    print(f"Total bundle events   : {total_events:,}")
    print(f"Unique customers      : {total_cust:,}")
    for w in WINDOWS:
        n = int(bundle_event_summary[f"Repeat_Flag_{w}D"].sum())
        print(f"Repeat {w}D            : {n:,} ({n / total_events * 100:.1f}%)")
    print(f"\nRevenue Before 28D    : Rp {total_rev_bef:,.0f}")
    print(f"Revenue After 28D     : Rp {total_rev_28D:,.0f}")
    print(f"Uplift 28D            : Rp {total_uplift:,.0f}")
    if total_rev_bef > 0:
        print(f"Uplift % vs Before    : {total_uplift / total_rev_bef * 100:.1f}%")
    print("\nUplift Flag distribution:")
    print(bundle_event_summary["Uplift_Flag"].value_counts().to_string())
    print("\nData Quality Summary:")
    print(data_quality_summary.to_string(index=False))

    output_tables = {
        "page1_master": page1_master,
        "rfm_dynamic": rfm_dynamic,
        "check_cashback": check_cashback,
    }

    if OUTPUT_TO_BIGQUERY:
        print("\n🔐 Upload ke BigQuery...")
        if auth is not None:
            auth.authenticate_user()
        client = bigquery.Client(project=BQ_PROJECT_ID, location=BQ_LOCATION)
        ensure_bigquery_dataset(client, BQ_DATASET_ID, BQ_LOCATION)
        for name, data in output_tables.items():
            upload_table_to_bigquery(client, name, data)
        print("✓ Upload BigQuery selesai.")

    print("\n" + "=" * 60)
    print("PIPELINE SELESAI — v4.2 VALIDATED BIGQUERY")
    print("=" * 60)
    print("Tabel yang diload ke BigQuery:")
    print(f"  · {BQ_PROJECT_ID}.{BQ_DATASET_ID}.page1_master")
    print(f"  · {BQ_PROJECT_ID}.{BQ_DATASET_ID}.rfm_dynamic")
    print(f"  · {BQ_PROJECT_ID}.{BQ_DATASET_ID}.check_cashback")
    print("=" * 60)

    return output_tables


if __name__ == "__main__":
    main()