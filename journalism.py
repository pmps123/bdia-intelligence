import html
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
import warnings
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd

try:
    from weasyprint import HTML as WeasyHTML
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "weasyprint", "-q"])
    from weasyprint import HTML as WeasyHTML

warnings.filterwarnings("ignore")

# =============================================================================
# 1. CONFIGURATION
# =============================================================================

FILE_PATH        = "/content/Invoice Jan - 3 Jul 2026 (1783220669991).xlsx"
PRODUCT_PIPAMAS  = "/content/Target 2026.xlsx"
PRODUCT_LAINNYA  = "/content/List Brand Name Active (1775788460191).xlsx"

COMPANY_NAME            = "PT Pancamas Pipasakti"
PREPARED_BY             = "Rafli - BDIA"
REPORT_AUDIENCE         = "Commercial Management & Board of Directors"
REPORT_CLASSIFICATION   = "Daily Sales Performance by Sales Invoice"
REPORT_DASHBOARD_URL    = "https://datastudio.google.com/reporting/e6132485-e233-469d-86b0-dca2429ec508"
REPORT_TITLE_TEMPLATE   = "Daily Sales Performance by Sales Invoice - {date_max:%d %b %Y}"
OUTPUT_DIR              = "."

THRESHOLD_NAIK  = 5.0
THRESHOLD_TURUN = -5.0
CONTENT_PAGES   = 13

M = {
    "ink": "#0B1220", "navy": "#0F172A", "blue": "#1D4ED8", "blue2": "#2563EB",
    "sky": "#38BDF8", "cyan": "#0891B2", "teal": "#0D9488", "purple": "#6D28D9",
    "red": "#DC2626", "green": "#16A34A", "amber": "#D97706", "slate": "#475569",
    "muted": "#94A3B8", "line": "#E2E8F0", "soft": "#F8FAFC", "white": "#FFFFFF",
}

# =============================================================================
# 2. FORMATTERS AND UTILITIES
# =============================================================================

def _safe(value) -> str:
    return html.escape(str(value))

def _clean_num_text(value: float, decimals: int = 1) -> str:
    value = float(value)
    text = f"{value:.{decimals}f}"
    if decimals > 0 and text.endswith(".0"):
        text = text[:-2]
    return text

def fmt_rp_smart(value: float) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    av = abs(value)
    sign = "-" if value < 0 else ""
    v = abs(value)
    if av >= 1e9:
        return f"Rp {sign}{_clean_num_text(v/1e9, 1)} M"
    if av >= 1e6:
        dec = 1 if v/1e6 < 100 else 0
        return f"Rp {sign}{_clean_num_text(v/1e6, dec)} Jt"
    if av >= 1e3:
        return f"Rp {sign}{_clean_num_text(v/1e3, 0)} Rb"
    return f"Rp {sign}{v:,.0f}"

def fmt_pct(value: float) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):+.1f}%"

def delta_pct(actual: float, comparison: float) -> float:
    if comparison == 0 or pd.isna(comparison):
        return 0.0
    return (actual - comparison) / abs(comparison) * 100

def safe_pct(delta, base):
    base = np.asarray(base)
    return np.where(base == 0, 0.0, delta / base * 100)

def truncate_text(value, n: int = 24) -> str:
    s = str(value)
    return s if len(s) <= n else s[:max(1, n-3)] + "..."

def truncate_list(values: Iterable, n: int = 24) -> List[str]:
    return [truncate_text(v, n) for v in values]

def rupiah_scale(max_abs: float) -> Tuple[float, str, str]:
    max_abs = abs(float(max_abs or 0))
    if max_abs >= 1e9: return 1e9, "Rp Miliar", "M"
    if max_abs >= 1e6: return 1e6, "Rp Juta",   "Jt"
    if max_abs >= 1e3: return 1e3, "Rp Ribu",   "Rb"
    return 1.0, "Rp", ""

def fmt_axis_value(value: float, max_abs: float) -> str:
    scale, _, suffix = rupiah_scale(max_abs)
    vv = float(value) / scale
    if abs(vv) >= 100: txt = f"{vv:.0f}"
    else:              txt = f"{vv:.1f}".rstrip("0").rstrip(".")
    return txt

def pct_class(value: float) -> str:
    if value > 0:  return "up"
    if value < 0:  return "down"
    return "flat"

def arrow(value: float) -> str:
    if value > 0:  return "▲"
    if value < 0:  return "▼"
    return "●"

def trend_badge_class(kondisi: str) -> str:
    if kondisi == "EKSPANSI":  return "badge-green"
    if kondisi == "STABIL":    return "badge-amber"
    return "badge-red"

def date_range_text(k: dict) -> str:
    return f"{k['date_min']:%d %b %Y} - {k['date_max']:%d %b %Y}"

def report_title(k: dict) -> str:
    return REPORT_TITLE_TEMPLATE.format(date_max=k["date_max"])

def report_filename(k: dict, ext: str) -> str:
    date_token = pd.Timestamp(k["date_max"]).strftime("%Y-%m-%d")
    return f"Daily_Sales_Performance_by_Sales_Invoice_{date_token}.{ext}"

def is_friday(date_value) -> bool:
    return pd.Timestamp(date_value).weekday() == 4

def quarter_to_date_frames(df: pd.DataFrame, date_max: pd.Timestamp) -> tuple:
    date_max    = pd.Timestamp(date_max).normalize()
    current_q   = date_max.to_period("Q")
    q_start     = pd.Timestamp(current_q.start_time).normalize()
    elapsed_days= max(0, (date_max - q_start).days)
    prev_q      = current_q - 1
    prev_q_start= pd.Timestamp(prev_q.start_time).normalize()
    prev_q_end  = pd.Timestamp(prev_q.end_time).normalize()
    prev_q_equiv= min(prev_q_end, prev_q_start + pd.Timedelta(days=elapsed_days))
    df_current  = df[(df["Date_Only"] >= q_start)     & (df["Date_Only"] <= date_max)]
    df_previous = df[(df["Date_Only"] >= prev_q_start) & (df["Date_Only"] <= prev_q_equiv)]
    return df_current, df_previous, q_start, prev_q_start, prev_q_equiv

def year_to_date_frames(df: pd.DataFrame, date_max: pd.Timestamp) -> tuple:
    date_max    = pd.Timestamp(date_max).normalize()
    y_start     = pd.Timestamp(year=date_max.year, month=1, day=1)
    prev_y_start= pd.Timestamp(year=date_max.year-1, month=1, day=1)
    try:
        prev_y_end = pd.Timestamp(year=date_max.year-1, month=date_max.month, day=date_max.day)
    except ValueError:
        prev_y_end = pd.Timestamp(year=date_max.year-1, month=date_max.month, day=1) + pd.offsets.MonthEnd(0)
    df_current  = df[(df["Date_Only"] >= y_start)      & (df["Date_Only"] <= date_max)]
    df_previous = df[(df["Date_Only"] >= prev_y_start) & (df["Date_Only"] <= prev_y_end)]
    return df_current, df_previous, y_start, prev_y_start, prev_y_end


def completed_quarter_frames(df: pd.DataFrame, date_max: pd.Timestamp) -> tuple:
    """Return latest completed quarter and its previous quarter.

    Business rule for QoQ in this report:
    - Do not compare an unfinished current quarter as QoQ.
    - When a new quarter has started, compare the latest completed quarter
      against the quarter before it. Example: on 1 Jul 2026, compare Q2 vs Q1.
    - If either quarter has no data, the report suppresses the QoQ card.
    """
    date_max = pd.Timestamp(date_max).normalize()
    current_q = date_max.to_period("Q")
    latest_completed_q = current_q - 1
    previous_completed_q = current_q - 2

    df_current = df[df["YearQuarter"].eq(latest_completed_q)].copy()
    df_previous = df[df["YearQuarter"].eq(previous_completed_q)].copy()

    current_start = pd.Timestamp(latest_completed_q.start_time).normalize()
    current_end = pd.Timestamp(latest_completed_q.end_time).normalize()
    previous_start = pd.Timestamp(previous_completed_q.start_time).normalize()
    previous_end = pd.Timestamp(previous_completed_q.end_time).normalize()

    return (
        df_current,
        df_previous,
        latest_completed_q,
        previous_completed_q,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )


def completed_month_frames(df: pd.DataFrame, date_max: pd.Timestamp) -> tuple:
    """Return latest completed month and its previous month.

    Business rule for MoM in this report:
    - Do not compare an unfinished current month against a full previous month.
    - Show completed MoM only when the latest invoice date is day 1, meaning a
      new month has started. Example: on 1 Jul 2026, compare Jun 2026 vs May 2026.
    - If either month has no data, suppress the completed MoM scorecard row.
    """
    date_max = pd.Timestamp(date_max).normalize()
    current_m = date_max.to_period("M")
    latest_completed_m = current_m - 1
    previous_completed_m = current_m - 2

    df_current = df[df["YearMonth"].eq(latest_completed_m)].copy()
    df_previous = df[df["YearMonth"].eq(previous_completed_m)].copy()

    current_start = pd.Timestamp(latest_completed_m.start_time).normalize()
    current_end = pd.Timestamp(latest_completed_m.end_time).normalize()
    previous_start = pd.Timestamp(previous_completed_m.start_time).normalize()
    previous_end = pd.Timestamp(previous_completed_m.end_time).normalize()

    return (
        df_current,
        df_previous,
        latest_completed_m,
        previous_completed_m,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )


# =============================================================================
# TARGET 2026 LOADING AND MATCHING
# =============================================================================

MONTH_NAME_MAP = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}
MONTH_ABBR_MAP = {i: pd.Timestamp(year=2026, month=i, day=1).strftime("%b") for i in range(1, 13)}

def _norm_text(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text

def _norm_key(value) -> str:
    text = _norm_text(value)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text

def _pretty_brand_label(value) -> str:
    """Return a stable display label for brand names after key-level grouping.

    Target and invoice sources sometimes contain the same brand with different
    casing, for example 'Dulux WTP' and 'DULUX WTP'. The report should treat
    them as one brand while still showing a readable label.
    """
    s = str(value or "").strip()
    if not s or s.lower() in {"nan", "none"}:
        return "Unknown"
    upper_aliases = {"WTP", "SC", "ICI"}
    parts = []
    for part in re.split(r"(\s+|[-_/])", s):
        if part.isspace() or part in {"-", "_", "/"}:
            parts.append(part)
            continue
        token = part.strip()
        if not token:
            parts.append(part)
        elif token.upper() in upper_aliases:
            parts.append(token.upper())
        else:
            parts.append(token.capitalize())
    return "".join(parts).strip()

def _first_non_empty(series, default="-"):
    for value in series:
        s = str(value or "").strip()
        if s and s.lower() not in {"nan", "none"}:
            return s
    return default


SALESMAN_RENAME_MAP = {
    "ICSLM80": "ICCOS08",
}


def normalize_salesman_series(series: pd.Series) -> pd.Series:
    """Normalize salesman code so report logic follows the Excel/Power Query rule."""
    return (
        series.astype(str)
        .str.strip()
        .str.upper()
        .replace(SALESMAN_RENAME_MAP)
    )


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return first existing column, matching exact name first then normalized name."""
    if df is None or df.empty:
        return None
    existing = {str(c).strip(): c for c in df.columns}
    for cand in candidates:
        if cand in existing:
            return existing[cand]
    norm_existing = {_norm_key(c): c for c in df.columns}
    for cand in candidates:
        hit = norm_existing.get(_norm_key(cand))
        if hit is not None:
            return hit
    return None


def _normalize_ici_target_unit(value, brand=None) -> str:
    """Normalize target UOM from Target Cat (V_W).

    Excel target uses V/W, while dashboard/report charts need VOLUME/WEIGHT.
    Warnamu remains WEIGHT as fallback when UOM is blank.
    """
    key = str(value or "").strip().upper().replace("_", " ")
    if key in {"V", "VOL", "VOLUME", "LT", "L", "LITER", "LITRE"}:
        return "VOLUME"
    if key in {"W", "WEIGHT", "KG", "KILOGRAM", "BERAT"}:
        return "WEIGHT"
    if _norm_key(brand) == _norm_key("warnamu"):
        return "WEIGHT"
    return "VOLUME"


# Dashboard / Looker Studio target-control scope.
# Important findings from audit:
# - IC/ICI must stay included in Monthly Revenue vs Actual Target.
# - Actual sales must exclude Branch Agen because the dashboard/BQ total does not include it.
# - Target must exclude Project, DIST KALIMANTAN, and DIST SUMATERA in a case-insensitive way.
TARGET_EXCLUDED_BRANCHES = {"Project", "Dist Kalimantan", "Dist Sumatera"}
TARGET_EXCLUDED_BRANCHES_UPPER = {"PROJECT", "DIST KALIMANTAN", "DIST SUMATERA"}
ACTUAL_TARGET_EXCLUDED_BRANCHES_UPPER = TARGET_EXCLUDED_BRANCHES_UPPER | {"AGEN"}

def is_agen_project_sales_code(salesman) -> bool:
    """Return True for PISLP30-PISLP59.

    Kept for sales category logic only. The monthly target-control scope is
    now aligned to the BigQuery view: exclude by Branch, not by PISLP30-PISLP59.
    """
    s = str(salesman or "").strip().upper()
    m = re.search(r"(\d{2})$", s)
    if not m:
        return False
    suffix = int(m.group(1))
    return s.startswith("PISLP") and 30 <= suffix <= 59

def normalize_branch_for_scope(value) -> str:
    return str(value or "").strip()

def normalize_branch_upper_for_scope(value) -> str:
    return normalize_branch_for_scope(value).upper()

def is_excluded_target_branch(value) -> bool:
    """Target-side exclusion for Monthly Revenue vs Actual Target.

    This follows the dashboard target result:
      exclude Project, DIST KALIMANTAN, and DIST SUMATERA.

    The check is case-insensitive so both 'Dist Sumatera' and
    'DIST SUMATERA' are handled consistently.
    """
    return normalize_branch_upper_for_scope(value) in TARGET_EXCLUDED_BRANCHES_UPPER

def is_excluded_actual_target_branch(value) -> bool:
    """Actual-side exclusion for Monthly Revenue vs Actual Target.

    Audit result shows the dashboard/BQ monthly actual excludes the Python
    Branch 'Agen' amount, while IC/ICI remains included. Therefore actual-side
    scope excludes Project, Dist Kalimantan, Dist Sumatera, and Agen.
    """
    return normalize_branch_upper_for_scope(value) in ACTUAL_TARGET_EXCLUDED_BRANCHES_UPPER

def normalize_division(value) -> str:
    raw = str(value or "").strip()
    key = raw.upper().replace(".", "").replace(" ", "")

    if key in {"EL", "ELEKTRIK", "ELECTRIK"}:
        return "Elektrik"
    if key in {"IC", "ICI"}:
        return "ICI"
    if key in {"PI", "PIPAMAS", "PIPA"}:
        return "Pipamas"
    if key in {"PP", "POMPA"}:
        return "Pompa"
    return raw.title() if raw else "Unknown"

def is_ici_or_ic_division(value) -> bool:
    """Return True for IC/ICI division values across raw and normalized labels.

    Used only for Page 2 Non-ICI visualization scope. The main dashboard
    monthly target-control scope can still include IC/ICI when needed.
    """
    key = str(value or "").strip().upper().replace(".", "").replace(" ", "")
    return key in {"IC", "ICI"}

def _coerce_numeric_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out

def _find_month_cols(columns, prefix_pattern: str) -> dict:
    """
    Return mapping {month_number: original_column_name}.
    Examples accepted:
      Mo 01, Mo 02, ..., Mo 12
      Mo-01, Mo-2, ..., Mo-12
    """
    mapping = {}
    regex = re.compile(prefix_pattern, re.IGNORECASE)
    for col in columns:
        m = regex.match(str(col).strip())
        if not m:
            continue
        month_num = int(m.group(1))
        if 1 <= month_num <= 12:
            mapping[month_num] = col
    return mapping

def _melt_monthly_target(
    df: pd.DataFrame,
    month_col_map: dict,
    value_name: str,
    id_cols: list[str],
    year: int = 2026,
) -> pd.DataFrame:
    available_id_cols = [c for c in id_cols if c in df.columns]
    available_month_cols = [month_col_map[i] for i in sorted(month_col_map) if month_col_map[i] in df.columns]

    if not available_month_cols:
        return pd.DataFrame(columns=available_id_cols + ["Month_Num", "Month_Name", "YearMonth", value_name])

    working = df[available_id_cols + available_month_cols].copy()
    working = _coerce_numeric_columns(working, available_month_cols)

    long_df = working.melt(
        id_vars=available_id_cols,
        value_vars=available_month_cols,
        var_name="Month_Source",
        value_name=value_name,
    )

    reverse_map = {str(v): k for k, v in month_col_map.items()}
    long_df["Month_Num"] = long_df["Month_Source"].astype(str).map(reverse_map).astype(int)
    long_df["Month_Name"] = long_df["Month_Num"].map(MONTH_NAME_MAP)
    long_df["YearMonth"] = long_df["Month_Num"].apply(lambda m: pd.Period(f"{year}-{m:02d}", freq="M"))
    long_df = long_df.drop(columns=["Month_Source"])
    return long_df

def load_target_2026(target_path: str) -> dict:
    """
    Load actual target from Target 2026.xlsx.

    Main target sheet:
      - Sheet: Target (belum_agen prj)
      - Monthly columns: Mo 01 ... Mo 12
      - Month columns are normalized to January ... December.
      - SKU target name follows BigQuery view logic: use 'Breakdown' as SKU key.

    ICI target sheet:
      - Sheet: Target Cat (V_W)
      - Unit target columns: Mo-01 ... Mo-12
      - Revenue target columns: Mo 01 ... Mo 12
      - Warnamu is treated as WEIGHT; all other brands are treated as VOLUME.
    """
    empty = {
        "target_detail": pd.DataFrame(),
        "target_monthly": pd.DataFrame(columns=["YearMonth", "Month_Num", "Month_Name", "Target_Revenue"]),
        "target_salesman_monthly": pd.DataFrame(),
        "target_sku_monthly": pd.DataFrame(),
        "target_ici_vw_monthly": pd.DataFrame(),
        "target_available": False,
        "target_note": "Target 2026.xlsx tidak berhasil dibaca.",
    }

    if not target_path or not Path(target_path).exists():
        empty["target_note"] = f"File target tidak ditemukan: {target_path}"
        print(f"[WARN] {empty['target_note']}")
        return empty

    try:
        # Main SKU/value target
        main = pd.read_excel(target_path, sheet_name="Target (belum_agen prj)")
        main.columns = [str(c).strip() for c in main.columns]
        main = main.dropna(how="all").copy()

        value_months = _find_month_cols(main.columns, r"^Mo\s*0?(\d{1,2})$")
        main_id_cols = ["Branch", "Div", "Salesman", "Breakdown", "Breakdown MEI 26", "Brand Focus"]
        main_long = _melt_monthly_target(main, value_months, "Target_Revenue", main_id_cols)

        if not main_long.empty:
            main_long["Branch"] = main_long["Branch"].astype(str).str.strip()
            main_long["Div"] = main_long["Div"].apply(normalize_division)
            main_long["Salesman"] = main_long["Salesman"].astype(str).str.strip().str.upper()
            # BQ view uses LOWER(TRIM(Breakdown)) as target SKU key.
            # Do not use Breakdown MEI 26 for this monthly sales-vs-target view,
            # otherwise Python output will differ from v_sales_vs_target_monthly.
            if "Breakdown" in main_long.columns:
                main_long["Target_SKU"] = main_long["Breakdown"].astype(str).str.strip()
            else:
                main_long["Target_SKU"] = main_long.get("Breakdown MEI 26", "").astype(str).str.strip()
            main_long["Target_SKU"] = main_long["Target_SKU"].astype(str).str.strip()
            main_long["Target_SKU_Key"] = main_long["Target_SKU"].apply(_norm_key)
            main_long["Div_Key"] = main_long["Div"].apply(_norm_key)
            main_long["Salesman_Key"] = main_long["Salesman"].apply(_norm_key)
            main_long["Target_Source"] = "Target (belum_agen prj)"
            main_long["Target_Unit_Type"] = "VALUE"
            main_long["Target_Qty"] = np.nan

        # ICI volume / weight target
        try:
            ici = pd.read_excel(target_path, sheet_name="Target Cat (V_W)")
            ici.columns = [str(c).strip() for c in ici.columns]
            ici = ici.dropna(how="all").copy()

            ici_value_months = _find_month_cols(ici.columns, r"^Mo\s*0?(\d{1,2})$")
            ici_qty_months = _find_month_cols(ici.columns, r"^Mo-0?(\d{1,2})$")

            ici_id_cols = ["Branch", "Div", "Salesman", "Brand", "Volume (Lt) /Weight (Kg)", "Conv Rate (IDR)", "Indeks"]
            ici_value = _melt_monthly_target(ici, ici_value_months, "Target_Revenue", ici_id_cols)
            ici_qty = _melt_monthly_target(ici, ici_qty_months, "Target_Qty", ici_id_cols)

            if not ici_value.empty:
                key_cols = ["Branch", "Div", "Salesman", "Brand", "Indeks", "Month_Num", "YearMonth"] if "Indeks" in ici_value.columns and "Indeks" in ici_qty.columns else ["Branch", "Div", "Salesman", "Brand", "Month_Num", "YearMonth"]
                keep_qty = [c for c in key_cols + ["Target_Qty"] if c in ici_qty.columns]
                ici_long = ici_value.merge(ici_qty[keep_qty], on=key_cols, how="left") if not ici_qty.empty else ici_value.copy()
                if "Target_Qty" not in ici_long.columns:
                    ici_long["Target_Qty"] = np.nan

                ici_long["Branch"] = ici_long["Branch"].astype(str).str.strip()
                ici_long["Div"] = "ICI"
                ici_long["Salesman"] = ici_long["Salesman"].astype(str).str.strip().str.upper()
                ici_long["Target_SKU"] = ici_long["Brand"].astype(str).str.strip()
                ici_long["Target_SKU_Key"] = ici_long["Target_SKU"].apply(_norm_key)
                ici_long["Div_Key"] = ici_long["Div"].apply(_norm_key)
                ici_long["Salesman_Key"] = ici_long["Salesman"].apply(_norm_key)

                # Target Cat (V_W) uses UOM values V/W.
                # Use the explicit UOM column first, then fallback to Warnamu=WEIGHT.
                uom_source_col = "Volume (Lt) /Weight (Kg)"
                if uom_source_col in ici_long.columns:
                    ici_long["Target_Unit_Type"] = [
                        _normalize_ici_target_unit(uom, brand)
                        for uom, brand in zip(ici_long[uom_source_col], ici_long["Target_SKU"])
                    ]
                else:
                    ici_long["Target_Unit_Type"] = ici_long["Target_SKU"].apply(
                        lambda brand: _normalize_ici_target_unit(None, brand)
                    )
                ici_long["Target_Source"] = "Target Cat (V_W)"
            else:
                ici_long = pd.DataFrame()
        except Exception as exc:
            print(f"[WARN] Sheet Target Cat (V_W) tidak bisa dibaca: {exc}")
            ici_long = pd.DataFrame()

        # BQ-aligned value target uses the main target sheet only.
        # Target Cat (V_W) is kept separate for the ICI unit-control page,
        # because the BigQuery monthly value view compares sales invoice value
        # against target_2026/Breakdown, not against the volume-weight sheet.
        target_detail = main_long.copy() if not main_long.empty else pd.DataFrame()

        if target_detail.empty:
            empty["target_note"] = "Target workbook terbaca, tetapi tidak ada target bulanan valid."
            print(f"[WARN] {empty['target_note']}")
            return empty

        target_detail["Target_Revenue"] = pd.to_numeric(target_detail["Target_Revenue"], errors="coerce").fillna(0.0)
        if "Target_Qty" in target_detail.columns:
            target_detail["Target_Qty"] = pd.to_numeric(target_detail["Target_Qty"], errors="coerce")

        target_monthly = (
            target_detail.groupby(["YearMonth", "Month_Num", "Month_Name"], as_index=False)["Target_Revenue"]
            .sum()
            .sort_values("Month_Num")
        )

        target_salesman_monthly = (
            target_detail.groupby(["YearMonth", "Month_Num", "Month_Name", "Branch", "Salesman"], as_index=False)["Target_Revenue"]
            .sum()
            .sort_values(["Month_Num", "Branch", "Salesman"])
        )

        target_sku_monthly = (
            target_detail.groupby(["YearMonth", "Month_Num", "Month_Name", "Branch", "Salesman", "Div", "Target_SKU", "Target_SKU_Key"], as_index=False)["Target_Revenue"]
            .sum()
            .sort_values(["Month_Num", "Branch", "Salesman", "Div", "Target_SKU"])
        )

        if not ici_long.empty:
            target_ici_vw_monthly = (
                ici_long.groupby(["YearMonth", "Month_Num", "Month_Name", "Branch", "Salesman", "Target_SKU", "Target_Unit_Type"], as_index=False)
                .agg(Target_Qty=("Target_Qty", "sum"), Target_Revenue=("Target_Revenue", "sum"))
                .sort_values(["Month_Num", "Branch", "Salesman", "Target_SKU"])
            )
        else:
            target_ici_vw_monthly = pd.DataFrame()

        print(f"[OK] Target 2026 dibaca: {len(target_detail):,} baris target bulanan")
        return {
            "target_detail": target_detail,
            "target_monthly": target_monthly,
            "target_salesman_monthly": target_salesman_monthly,
            "target_sku_monthly": target_sku_monthly,
            "target_ici_vw_monthly": target_ici_vw_monthly,
            "target_available": True,
            "target_note": "Target aktual menggunakan Target 2026.xlsx",
        }

    except Exception as exc:
        empty["target_note"] = f"Target workbook gagal diproses: {exc}"
        print(f"[WARN] {empty['target_note']}")
        return empty

def _target_for_month(target_monthly: pd.DataFrame, period_value, fallback_value: float = 0.0) -> float:
    if target_monthly is None or target_monthly.empty:
        return float(fallback_value or 0.0)
    period_value = pd.Period(period_value, freq="M")
    row = target_monthly[target_monthly["YearMonth"] == period_value]
    if row.empty:
        return float(fallback_value or 0.0)
    return float(row["Target_Revenue"].sum())

def _target_for_date_window(target_monthly: pd.DataFrame, start_date, end_date, fallback_value: float = 0.0) -> float:
    """
    Allocate monthly target by calendar-day proportion for a date window.
    Useful for weekly/QTD target comparison when the source target is monthly.
    """
    if target_monthly is None or target_monthly.empty:
        return float(fallback_value or 0.0)

    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if pd.isna(start) or pd.isna(end) or end < start:
        return float(fallback_value or 0.0)

    total = 0.0
    for period in pd.period_range(start=start, end=end, freq="M"):
        month_start = pd.Timestamp(period.start_time).normalize()
        month_end = pd.Timestamp(period.end_time).normalize()
        overlap_start = max(start, month_start)
        overlap_end = min(end, month_end)
        overlap_days = max(0, (overlap_end - overlap_start).days + 1)
        month_days = max(1, (month_end - month_start).days + 1)
        month_target = _target_for_month(target_monthly, period, 0.0)
        total += month_target * overlap_days / month_days

    return float(total if total > 0 else (fallback_value or 0.0))

def _apply_target_branch_scope(
    df_in: pd.DataFrame,
    branch_col: str = "Branch",
    actual_side: bool = False,
) -> pd.DataFrame:
    """Apply branch scope for Monthly Revenue vs Actual Target.

    actual_side=False is used for target rows:
      exclude Project, Dist Kalimantan, and Dist Sumatera case-insensitively.

    actual_side=True is used for invoice actual rows:
      exclude Project, Dist Kalimantan, Dist Sumatera, and Agen.

    IC/ICI is intentionally not excluded in either side for this line chart.
    """
    if df_in is None or df_in.empty:
        return pd.DataFrame() if df_in is None else df_in.copy()
    out = df_in.copy()
    if branch_col not in out.columns:
        return out
    out[branch_col] = out[branch_col].astype(str).str.strip()
    if actual_side:
        mask_excluded = out[branch_col].apply(is_excluded_actual_target_branch)
    else:
        mask_excluded = out[branch_col].apply(is_excluded_target_branch)
    return out[~mask_excluded].copy()


def build_target_comparisons(df: pd.DataFrame, target_pack: dict, date_max) -> dict:
    """
    Build actual-vs-target detail tables aligned as closely as possible with
    BigQuery view `pipamas.sales_data.v_sales_vs_target_monthly`.

    BQ logic reproduced here:
      Actual invoice:
        - year 2026
        - dashboard scope: exclude Branch Project/Dist Kalimantan/Dist Sumatera/Agen
        - IC/ICI remains included
        - group by Month_Invoice + Branch + Salesman + lower(trim(sku))
        - SUM(Net_Price) as Total_Sales

      Target:
        - source: main target sheet / target_2026 equivalent
        - exclude Branch Project/Dist Kalimantan/Dist Sumatera case-insensitively
        - IC/ICI remains included
        - SKU key uses Breakdown, not Breakdown MEI 26
        - group by Month + Branch + Salesman + lower(trim(Breakdown))
        - SUM(Target) as Target_SKU

      Join:
        - FULL OUTER JOIN on Month + Branch + Salesman + SKU

      Monthly chart:
        - SUM(Total_Sales) and SUM(Target_SKU) from the joined view by month
        - only months up to the latest invoice month are displayed
    """
    date_max = pd.Timestamp(date_max).normalize()
    year = int(date_max.year)
    current_period = date_max.to_period("M")

    target_sku_monthly = target_pack.get("target_sku_monthly", pd.DataFrame())
    target_salesman_monthly = target_pack.get("target_salesman_monthly", pd.DataFrame())

    # ------------------------------------------------------------------
    # 1) Actual side: mirror si_agg in BigQuery view
    # ------------------------------------------------------------------
    df_scope = df.copy()
    df_scope["Branch"] = df_scope["Branch"].astype(str).str.strip()
    df_scope["Salesman"] = df_scope["Salesman"].astype(str).str.strip().str.upper()
    df_scope["Target_SKU_Key"] = df_scope["sku"].apply(_norm_key)
    df_scope["Div_BQ"] = df_scope["Sales Div."].astype(str).str.strip().replace({"IC": "ICI"}) if "Sales Div." in df_scope.columns else ""
    df_scope = df_scope[df_scope["Invoice Date"].dt.year.eq(year)].copy()
    df_scope = _apply_target_branch_scope(df_scope, "Branch", actual_side=True)

    actual_view = (
        df_scope.groupby(["YearMonth", "Branch", "Salesman", "Target_SKU_Key"], as_index=False)
        .agg(
            Total_Sales=("Total_Revenue", "sum"),
            Total_Quantity=("Quantity", "sum") if "Quantity" in df_scope.columns else ("Total_Revenue", "count"),
            Total_Invoice=("Invoice Code", "nunique") if "Invoice Code" in df_scope.columns else ("Total_Revenue", "count"),
            Sales_Div=("Div_BQ", "max"),
        )
        if not df_scope.empty else pd.DataFrame(columns=["YearMonth", "Branch", "Salesman", "Target_SKU_Key", "Total_Sales", "Total_Quantity", "Total_Invoice", "Sales_Div"])
    )

    # ------------------------------------------------------------------
    # 2) Target side: mirror target_sku_agg in BigQuery view
    # ------------------------------------------------------------------
    if target_sku_monthly is not None and not target_sku_monthly.empty:
        target_view = target_sku_monthly.copy()
        target_view["Branch"] = target_view["Branch"].astype(str).str.strip()
        target_view["Salesman"] = target_view["Salesman"].astype(str).str.strip().str.upper()
        target_view["Target_SKU_Key"] = target_view["Target_SKU_Key"].astype(str)
        target_view = _apply_target_branch_scope(target_view, "Branch")
        target_view = (
            target_view.groupby(["YearMonth", "Branch", "Salesman", "Target_SKU_Key"], as_index=False)
            .agg(
                Target_SKU=("Target_Revenue", "sum"),
                Target_SKU_Name=("Target_SKU", "first"),
                Sales_Div_Target=("Div", "first") if "Div" in target_view.columns else ("Target_Revenue", "count"),
            )
        )
    else:
        target_view = pd.DataFrame(columns=["YearMonth", "Branch", "Salesman", "Target_SKU_Key", "Target_SKU", "Target_SKU_Name", "Sales_Div_Target"])

    # ------------------------------------------------------------------
    # 3) FULL OUTER JOIN equivalent: Month + Branch + Salesman + SKU
    # ------------------------------------------------------------------
    join_keys = ["YearMonth", "Branch", "Salesman", "Target_SKU_Key"]
    bq_view = actual_view.merge(target_view, on=join_keys, how="outer")

    for col in ["Total_Sales", "Total_Quantity", "Total_Invoice", "Target_SKU"]:
        bq_view[col] = pd.to_numeric(bq_view.get(col, 0), errors="coerce").fillna(0.0)

    if "Sales_Div" not in bq_view.columns:
        bq_view["Sales_Div"] = np.nan
    if "Sales_Div_Target" not in bq_view.columns:
        bq_view["Sales_Div_Target"] = np.nan
    bq_view["Sales_Div"] = bq_view["Sales_Div"].fillna(bq_view["Sales_Div_Target"])
    bq_view["Target_SKU_Name"] = bq_view.get("Target_SKU_Name", pd.Series(dtype=str)).fillna("")
    bq_view["Gap"] = bq_view["Total_Sales"] - bq_view["Target_SKU"]
    bq_view["AchievementPct"] = np.where(
        bq_view["Target_SKU"] > 0,
        bq_view["Total_Sales"] / bq_view["Target_SKU"] * 100,
        np.nan,
    )
    bq_view["Business_Group"] = np.where(
        bq_view["Branch"].astype(str).str.strip().str.upper().isin(ACTUAL_TARGET_EXCLUDED_BRANCHES_UPPER),
        bq_view["Branch"],
        "Retail",
    )

    # ------------------------------------------------------------------
    # 4) Monthly line chart data from joined view, up to current month
    # ------------------------------------------------------------------
    month_end = int(date_max.month)
    months = pd.DataFrame({
        "YearMonth": [pd.Period(f"{year}-{m:02d}", freq="M") for m in range(1, month_end + 1)],
        "Month_Num": list(range(1, month_end + 1)),
    })
    months["Month_Name"] = months["Month_Num"].map(MONTH_NAME_MAP)
    months["Label"] = months["Month_Num"].apply(lambda m: f"{m:02d}-{year}")

    monthly_from_view = (
        bq_view.groupby("YearMonth", as_index=False)
        .agg(Total_Revenue=("Total_Sales", "sum"), Target_Revenue=("Target_SKU", "sum"))
        if not bq_view.empty else pd.DataFrame(columns=["YearMonth", "Total_Revenue", "Target_Revenue"])
    )

    monthly_vs_target = months.merge(monthly_from_view, on="YearMonth", how="left")
    monthly_vs_target["Total_Revenue"] = pd.to_numeric(monthly_vs_target.get("Total_Revenue", 0), errors="coerce").fillna(0.0)
    monthly_vs_target["Target_Revenue"] = pd.to_numeric(monthly_vs_target.get("Target_Revenue", 0), errors="coerce").fillna(0.0)
    monthly_vs_target["Growth"] = monthly_vs_target["Total_Revenue"].replace(0, np.nan).pct_change(fill_method=None) * 100
    monthly_vs_target["Target_Gap"] = monthly_vs_target["Total_Revenue"] - monthly_vs_target["Target_Revenue"]
    monthly_vs_target["Target_Achievement"] = np.where(
        monthly_vs_target["Target_Revenue"] > 0,
        monthly_vs_target["Total_Revenue"] / monthly_vs_target["Target_Revenue"] * 100,
        np.nan,
    )
    monthly_vs_target["Target_Scope"] = "Dashboard scope: IC/ICI included; actual excludes Agen/Project/Dist; target excludes Project/Dist; target SKU uses Breakdown"

    # ------------------------------------------------------------------
    # 4b) Page 2 specific view: Total Sales excludes IC/ICI
    # ------------------------------------------------------------------
    # User request: page 2 Total Sales should exclude ICI / IC.
    # To keep the comparison apples-to-apples, the target line is filtered
    # using the same non-ICI division scope. This page-2 view still keeps
    # the branch/channel scope already applied above.
    bq_view_non_ici = bq_view.copy()
    if "Sales_Div" in bq_view_non_ici.columns:
        bq_view_non_ici = bq_view_non_ici[
            ~bq_view_non_ici["Sales_Div"].apply(is_ici_or_ic_division)
        ].copy()

    monthly_from_view_non_ici = (
        bq_view_non_ici.groupby("YearMonth", as_index=False)
        .agg(Total_Revenue=("Total_Sales", "sum"), Target_Revenue=("Target_SKU", "sum"))
        if not bq_view_non_ici.empty else pd.DataFrame(columns=["YearMonth", "Total_Revenue", "Target_Revenue"])
    )

    monthly_vs_target_non_ici = months.merge(monthly_from_view_non_ici, on="YearMonth", how="left")
    monthly_vs_target_non_ici["Total_Revenue"] = pd.to_numeric(monthly_vs_target_non_ici.get("Total_Revenue", 0), errors="coerce").fillna(0.0)
    monthly_vs_target_non_ici["Target_Revenue"] = pd.to_numeric(monthly_vs_target_non_ici.get("Target_Revenue", 0), errors="coerce").fillna(0.0)
    monthly_vs_target_non_ici["Growth"] = monthly_vs_target_non_ici["Total_Revenue"].replace(0, np.nan).pct_change(fill_method=None) * 100
    monthly_vs_target_non_ici["Target_Gap"] = monthly_vs_target_non_ici["Total_Revenue"] - monthly_vs_target_non_ici["Target_Revenue"]
    monthly_vs_target_non_ici["Target_Achievement"] = np.where(
        monthly_vs_target_non_ici["Target_Revenue"] > 0,
        monthly_vs_target_non_ici["Total_Revenue"] / monthly_vs_target_non_ici["Target_Revenue"] * 100,
        np.nan,
    )
    monthly_vs_target_non_ici["Target_Scope"] = "Page 2 scope: IC/ICI excluded from Total Sales and Target Sales; branch/channel scope follows dashboard target-control logic"

    # ------------------------------------------------------------------
    # 5) Current-month tables used by report components
    # ------------------------------------------------------------------
    cur_view = bq_view[bq_view["YearMonth"].eq(current_period)].copy()

    salesman_vs_target = (
        cur_view.groupby(["Branch", "Salesman"], as_index=False)
        .agg(Actual_Revenue=("Total_Sales", "sum"), Target_Revenue=("Target_SKU", "sum"))
        if not cur_view.empty else pd.DataFrame(columns=["Branch", "Salesman", "Actual_Revenue", "Target_Revenue"])
    )
    salesman_vs_target["Gap"] = salesman_vs_target["Actual_Revenue"] - salesman_vs_target["Target_Revenue"]
    salesman_vs_target["AchievementPct"] = np.where(
        salesman_vs_target["Target_Revenue"] > 0,
        salesman_vs_target["Actual_Revenue"] / salesman_vs_target["Target_Revenue"] * 100,
        np.nan,
    )
    salesman_vs_target["Sales_Category"] = salesman_vs_target["Salesman"].apply(sales_category_from_code)

    sku_vs_target = cur_view.copy()
    sku_vs_target = sku_vs_target.rename(columns={
        "Total_Sales": "Actual_Revenue",
        "Target_SKU": "Target_Revenue",
        "Target_SKU_Name": "Target_SKU",
    })
    if "Target_SKU" not in sku_vs_target.columns:
        sku_vs_target["Target_SKU"] = ""
    sku_vs_target["Sales_Category"] = sku_vs_target["Salesman"].apply(sales_category_from_code)

    return {
        "monthly_vs_target": monthly_vs_target,
        "monthly_vs_target_non_ici": monthly_vs_target_non_ici,
        "salesman_vs_target": salesman_vs_target,
        "sku_vs_target": sku_vs_target,
        "bq_sales_vs_target_view": bq_view,
    }


# -----------------------------------------------------------------------------
# ICI actual unit matching: target unit must be compared with actual unit, not net price
# -----------------------------------------------------------------------------
def _find_measure_column(df: pd.DataFrame, exact_candidates: list[str], keyword_candidates: list[str], exclude_keywords: list[str] | None = None) -> str | None:
    """Find a likely numeric measure column from invoice data.

    The invoice export may use different labels across runs. This helper first
    checks exact names, then falls back to keyword matching while avoiding value/
    price/target columns.
    """
    if df is None or df.empty:
        return None
    exclude_keywords = [x.lower() for x in (exclude_keywords or [])]
    cols = list(df.columns)
    norm_exact = {_norm_text(c): c for c in cols}

    for cand in exact_candidates:
        hit = norm_exact.get(_norm_text(cand))
        if hit is not None:
            return hit

    for col in cols:
        low = _norm_text(col)
        if any(ex in low for ex in exclude_keywords):
            continue
        if any(kw.lower() in low for kw in keyword_candidates):
            return col
    return None


def _detect_invoice_unit_columns(df: pd.DataFrame) -> dict:
    volume_col = _find_measure_column(
        df,
        exact_candidates=[
            "Volume", "Line Volume", "Total_Volume_Actual", "Volume (Lt)", "Volume (L)", "Volume Lt", "Volume_Lt",
            "Vol", "Vol (Lt)", "Total Volume", "Liter", "Litre",
        ],
        keyword_candidates=["volume", "vol ", " vol", "liter", "litre"],
        exclude_keywords=["target", "price", "value", "amount", "revenue", "conv", "rate"],
    )
    weight_col = _find_measure_column(
        df,
        exact_candidates=[
            "Weight", "Line Weight", "Total_Weight_Actual", "Weight (Kg)", "Weight Kg", "Weight_Kg", "Berat", "Berat (Kg)",
            "Total Weight", "Net Weight", "Gross Weight", "Tonnage", "Tonase",
        ],
        keyword_candidates=["weight", "berat", "kg", "tonnage", "tonase"],
        exclude_keywords=["target", "price", "value", "amount", "revenue", "conv", "rate"],
    )

    # If the source already comes from the same sales-vs-target structure used
    # by Looker Studio, prefer Total_Achieve + UOM because it is the exact metric
    # used by the dashboard for Volume/Weight achievement. Raw invoice exports
    # may not have these fields, so the report still falls back to detected
    # Volume/Weight columns above.
    uom_col = None
    total_achieve_col = None
    for c in df.columns:
        if str(c).strip().lower().replace("_", " ") == "uom":
            uom_col = c
        if str(c).strip().lower().replace("_", " ") in {"total achieve", "total achieve qty", "total achievement"}:
            total_achieve_col = c

    return {
        "volume_col": volume_col,
        "weight_col": weight_col,
        "uom_col": uom_col,
        "total_achieve_col": total_achieve_col,
    }


def _normalized_actual_unit_from_uom(value) -> str:
    key = str(value or "").strip().upper().replace("_", " ")
    if key in {"V", "VOLUME", "VOL", "LITER", "LITRE", "LT", "L"}:
        return "VOLUME"
    if key in {"W", "WEIGHT", "BERAT", "KG", "KILOGRAM"}:
        return "WEIGHT"
    return ""


def _choose_ici_actual_sku_label(row) -> str:
    """Use invoice SKU/Product Category first, then Brand Name as fallback.

    Catylac SC is a SKU/category level target. In the invoice export its Brand
    Name can be only 'Catylac', while the dashboard and target table use SKU
    'catylac sc'. If we match actual by Brand Name, Catylac SC becomes 0 and
    its sales are incorrectly absorbed into Catylac.
    """
    for col in ["sku", "Product Category", "product category", "grup sku", "Grup SKU", "Brand Name"]:
        if col in row.index:
            value = row.get(col)
            text = str(value or "").strip()
            if text and text.lower() not in {"nan", "none", "unknown"}:
                return text
    return "Unknown"


def _prepare_ici_actual_rows(df: pd.DataFrame, date_max) -> pd.DataFrame:
    """Prepare invoice rows for ICI unit realization.

    Business rule: Warnamu realization is read from WEIGHT; all other ICI brands
    are read from VOLUME. Actual brand matching uses invoice SKU/category first,
    so SKU-level targets such as Catylac SC are detected correctly.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    cols = _detect_invoice_unit_columns(df)
    volume_col = cols.get("volume_col")
    weight_col = cols.get("weight_col")
    uom_col = cols.get("uom_col")
    total_achieve_col = cols.get("total_achieve_col")

    dfx = df.copy()
    if "Sales Div." in dfx.columns:
        dfx["Div_Norm"] = dfx["Sales Div."].apply(normalize_division)
    else:
        dfx["Div_Norm"] = ""
    dfx = dfx[dfx["Div_Norm"].astype(str).str.upper().eq("ICI")].copy()

    # Match the dashboard actual scope used by the report: Project/Agen/Dist
    # channels are not part of the target-control actual line.
    if "Branch" in dfx.columns:
        dfx = _apply_target_branch_scope(dfx, "Branch", actual_side=True)

    if dfx.empty:
        return pd.DataFrame(columns=["YearMonth", "Month_Num", "Month_Name", "Branch", "Brand", "Brand_Key", "Target_Unit_Type", "Actual_Qty"])

    # SKU/category-level matching is required for Catylac SC. Brand Name alone
    # may collapse Catylac and Catylac SC into a single Catylac row.
    dfx["Brand"] = dfx.apply(_choose_ici_actual_sku_label, axis=1).astype(str).str.strip()
    dfx["Brand_Key"] = dfx["Brand"].apply(_norm_key)
    dfx["Brand_Display"] = dfx["Brand"].apply(_pretty_brand_label)

    # Prefer dashboard-style Total_Achieve + UOM when available. Otherwise use
    # raw Volume/Weight columns and the Warnamu=WEIGHT rule.
    has_dashboard_achieve = False
    if uom_col and total_achieve_col and uom_col in dfx.columns and total_achieve_col in dfx.columns:
        dfx["__uom_unit"] = dfx[uom_col].apply(_normalized_actual_unit_from_uom)
        has_dashboard_achieve = dfx["__uom_unit"].isin(["VOLUME", "WEIGHT"]).any()
    else:
        dfx["__uom_unit"] = ""

    if has_dashboard_achieve:
        dfx = dfx[dfx["__uom_unit"].isin(["VOLUME", "WEIGHT"])].copy()
        dfx["Target_Unit_Type"] = dfx["__uom_unit"]
        dfx["Actual_Qty"] = pd.to_numeric(dfx[total_achieve_col], errors="coerce").fillna(0.0)
    else:
        dfx["Target_Unit_Type"] = np.where(
            dfx["Brand_Key"].eq(_norm_key("warnamu")),
            "WEIGHT",
            "VOLUME",
        )

        if volume_col and volume_col in dfx.columns:
            dfx["__actual_volume"] = pd.to_numeric(dfx[volume_col], errors="coerce").fillna(0.0)
        else:
            dfx["__actual_volume"] = 0.0

        if weight_col and weight_col in dfx.columns:
            dfx["__actual_weight"] = pd.to_numeric(dfx[weight_col], errors="coerce").fillna(0.0)
        else:
            dfx["__actual_weight"] = 0.0

        dfx["Actual_Qty"] = np.where(
            dfx["Target_Unit_Type"].eq("WEIGHT"),
            dfx["__actual_weight"],
            dfx["__actual_volume"],
        )

    dfx["Month_Num"] = dfx["YearMonth"].apply(lambda p: int(pd.Period(p, freq="M").month))
    dfx["Month_Name"] = dfx["Month_Num"].map(MONTH_NAME_MAP)
    return dfx


def build_ici_actual_target_tables(df: pd.DataFrame, target_ici_vw: pd.DataFrame, date_max) -> dict:
    """Build ICI unit actual-vs-target tables.

    Returns:
      - monthly: Month + Unit Type actual qty vs target qty
      - brand: current-month brand actual qty vs target qty
      - measure_columns: detected invoice columns for diagnostics
    """
    date_max = pd.Timestamp(date_max).normalize()
    cur_month = int(date_max.month)
    year = int(date_max.year)

    target = target_ici_vw.copy() if target_ici_vw is not None and not target_ici_vw.empty else pd.DataFrame()
    if not target.empty:
        target["Month_Num"] = pd.to_numeric(target["Month_Num"], errors="coerce")
        target = target[target["Month_Num"].notna()].copy()
        target["Month_Num"] = target["Month_Num"].astype(int)
        target = target[target["Month_Num"].le(cur_month)].copy()
        target["Target_Qty"] = pd.to_numeric(target.get("Target_Qty", 0), errors="coerce").fillna(0.0)
        target["Target_Revenue"] = pd.to_numeric(target.get("Target_Revenue", 0), errors="coerce").fillna(0.0)
        if "Branch" in target.columns:
            target = _apply_target_branch_scope(target, "Branch", actual_side=False)
        if "Target_Unit_Type" in target.columns:
            target["Target_Unit_Type"] = target["Target_Unit_Type"].apply(_normalize_ici_target_unit)
        if "Target_SKU_Key" not in target.columns:
            target["Target_SKU_Key"] = target.get("Target_SKU", "").apply(_norm_key)
        target["Target_SKU_Key"] = target["Target_SKU_Key"].astype(str)
        target["Target_SKU_Display"] = target.get("Target_SKU", pd.Series(dtype=str)).apply(_pretty_brand_label)
    else:
        target = pd.DataFrame(columns=["YearMonth", "Month_Num", "Month_Name", "Target_SKU", "Target_SKU_Key", "Target_Unit_Type", "Target_Qty", "Target_Revenue"])

    actual_rows = _prepare_ici_actual_rows(df, date_max)
    measure_cols = _detect_invoice_unit_columns(df)

    months = pd.DataFrame({
        "Month_Num": list(range(1, cur_month + 1)),
        "YearMonth": [pd.Period(f"{year}-{m:02d}", freq="M") for m in range(1, cur_month + 1)],
    })
    months["Month_Name"] = months["Month_Num"].map(MONTH_NAME_MAP)
    base = pd.MultiIndex.from_product([months["Month_Num"].tolist(), ["VOLUME", "WEIGHT"]], names=["Month_Num", "Target_Unit_Type"]).to_frame(index=False)
    base = base.merge(months, on="Month_Num", how="left")

    target_monthly = (
        target.groupby(["Month_Num", "Target_Unit_Type"], as_index=False)
        .agg(Target_Qty=("Target_Qty", "sum"), Target_Revenue=("Target_Revenue", "sum"))
        if not target.empty else pd.DataFrame(columns=["Month_Num", "Target_Unit_Type", "Target_Qty", "Target_Revenue"])
    )
    actual_monthly = (
        actual_rows.groupby(["Month_Num", "Target_Unit_Type"], as_index=False)["Actual_Qty"].sum()
        if actual_rows is not None and not actual_rows.empty else pd.DataFrame(columns=["Month_Num", "Target_Unit_Type", "Actual_Qty"])
    )
    monthly = (
        base.merge(target_monthly, on=["Month_Num", "Target_Unit_Type"], how="left")
            .merge(actual_monthly, on=["Month_Num", "Target_Unit_Type"], how="left")
    )
    monthly["Target_Qty"] = pd.to_numeric(monthly.get("Target_Qty", 0), errors="coerce").fillna(0.0)
    monthly["Target_Revenue"] = pd.to_numeric(monthly.get("Target_Revenue", 0), errors="coerce").fillna(0.0)
    monthly["Actual_Qty"] = pd.to_numeric(monthly.get("Actual_Qty", 0), errors="coerce").fillna(0.0)
    monthly["Gap_Qty"] = monthly["Actual_Qty"] - monthly["Target_Qty"]
    monthly["AchievementPct"] = np.where(monthly["Target_Qty"] > 0, monthly["Actual_Qty"] / monthly["Target_Qty"] * 100, np.nan)

    target_cur = target[target["Month_Num"].eq(cur_month)].copy() if not target.empty else pd.DataFrame()
    if not target_cur.empty:
        # Group by normalized brand key only to avoid duplicate display rows such
        # as 'Dulux WTP' and 'DULUX WTP'.
        target_cur = (
            target_cur.groupby(["Target_SKU_Key", "Target_Unit_Type"], as_index=False)
            .agg(
                Target_Qty=("Target_Qty", "sum"),
                Target_Revenue=("Target_Revenue", "sum"),
                Target_SKU=("Target_SKU_Display", _first_non_empty),
            )
        )
    else:
        target_cur = pd.DataFrame(columns=["Target_SKU_Key", "Target_SKU", "Target_Unit_Type", "Target_Qty", "Target_Revenue"])

    actual_cur = actual_rows[actual_rows["Month_Num"].eq(cur_month)].copy() if actual_rows is not None and not actual_rows.empty else pd.DataFrame()
    if not actual_cur.empty:
        actual_cur = (
            actual_cur.groupby(["Brand_Key", "Target_Unit_Type"], as_index=False)
            .agg(Actual_Qty=("Actual_Qty", "sum"), Actual_Brand=("Brand_Display", _first_non_empty))
            .rename(columns={"Brand_Key": "Target_SKU_Key"})
        )
    else:
        actual_cur = pd.DataFrame(columns=["Target_SKU_Key", "Actual_Brand", "Target_Unit_Type", "Actual_Qty"])

    brand = target_cur.merge(actual_cur, on=["Target_SKU_Key", "Target_Unit_Type"], how="outer")
    for col in ["Target_Qty", "Target_Revenue", "Actual_Qty"]:
        brand[col] = pd.to_numeric(brand.get(col, 0), errors="coerce").fillna(0.0)
    if "Target_SKU" not in brand.columns:
        brand["Target_SKU"] = np.nan
    if "Actual_Brand" not in brand.columns:
        brand["Actual_Brand"] = np.nan
    brand["Brand"] = brand["Target_SKU"].where(
        brand["Target_SKU"].astype(str).str.strip().ne("") & brand["Target_SKU"].notna(),
        brand["Actual_Brand"],
    ).apply(_pretty_brand_label)
    brand["Gap_Qty"] = brand["Actual_Qty"] - brand["Target_Qty"]
    brand["AchievementPct"] = np.where(brand["Target_Qty"] > 0, brand["Actual_Qty"] / brand["Target_Qty"] * 100, np.nan)
    brand = brand.sort_values(["Target_Unit_Type", "Target_Qty"], ascending=[True, False])

    return {"monthly": monthly, "brand": brand, "measure_columns": measure_cols}

# =============================================================================
# 3. DATA LOADING AND BUSINESS RULES
# =============================================================================

def validate_columns(df: pd.DataFrame, required: List[str], name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Kolom wajib tidak ditemukan di {name}: {missing}")

def sales_code_suffix(salesman) -> int | None:
    s = str(salesman or "").strip().upper()
    m = re.search(r"(\d{2})$", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def sales_category_from_code(salesman) -> str:
    """
    Business-facing sales classification using internal sales hierarchy:
      Branch Manager -> Supervisor -> Cosales -> Salesman.

    Important:
      - SPV codes are Supervisor regardless of numeric suffix.
      - COS codes are Cosales regardless of numeric suffix.
      - PISLP30-PISLP39 = Sales Project.
      - PISLP50-PISLP59 = Sales Agen.
    """
    s = str(salesman or "").strip().upper()
    suffix = sales_code_suffix(s)

    if "SPV" in s:
        return "Supervisor"
    if "COS" in s:
        return "Cosales"

    if s.startswith("PISLP") and suffix is not None:
        if 30 <= suffix <= 39:
            return "Sales Project"
        if 50 <= suffix <= 59:
            return "Sales Agen"

    if suffix is not None:
        if 60 <= suffix <= 69: return "Sales Cirebon"
        if 70 <= suffix <= 79: return "Sales Tasik"
        if 80 <= suffix <= 89: return "Sales Bogor"
        if suffix < 20:        return "Sales Bandung"
        if 20 <= suffix <= 29: return "Sales PCK"

    return "Sales Other"

def sales_channel_from_row(row) -> str:
    """Return Retail/Project/Agen channel for sales insight segmentation.

    User business rule:
      - Retail = sales yang bukan Project dan bukan Agen/Dist.
      - Project = Branch Project atau Sales Project code.
      - Agen = Branch Agen / Dist Kalimantan / Dist Sumatera atau Sales Agen code.

    This is intentionally separated from the target-control scope. It is used
    for Page 5 insight segmentation only, not to change existing actual-vs-target
    calculations.
    """
    salesman = str(row.get("Salesman", "") or "").strip().upper()
    branch = str(row.get("Branch", "") or "").strip().upper()
    category = sales_category_from_code(salesman)

    if category == "Sales Project" or branch == "PROJECT":
        return "Project"

    if (
        category == "Sales Agen"
        or branch == "AGEN"
        or branch.startswith("DIST ")
        or branch in {"DIST KALIMANTAN", "DIST SUMATERA"}
    ):
        return "Agen"

    return "Retail"


def assign_branch(salesman) -> str:
    s      = str(salesman or "").strip().upper()
    suffix = sales_code_suffix(s)
    if suffix is not None:
        if 30 <= suffix <= 39: return "Project"
        if 50 <= suffix <= 59: return "Agen"
    if s in ["ELCOS01","PICOS01","PICOS21","PPCOS01"]: return "Bandung"
    if s in ["ELCOS06","PICOS06","PPCOS06"]:           return "Cirebon"
    if s in ["ELCOS08","ICCOS08","PPCOS08"]:           return "Bogor"
    if s == "ICCOS07":                                 return "Tasik"
    if suffix is None:         return "Project"
    if suffix < 20:            return "Bandung"
    if suffix < 30:            return "PCK"
    if 40 <= suffix <= 49:     return "Project"
    if 60 <= suffix < 70:      return "Cirebon"
    if 70 <= suffix < 80:      return "Tasik"
    if 80 <= suffix < 90:      return "Bogor"
    return "Project"

PIPAMAS_BRANDS = {"mtn", "pipamas", "tangit"}

def assign_sku(row) -> str:
    brand     = row.get("Brand Name", "Unknown")
    besides   = row.get("Product Category", np.nan)
    sku_bogor = row.get("grup sku bogor", np.nan)
    sku_def   = row.get("grup sku", np.nan)
    is_pip    = str(brand).strip().lower() in PIPAMAS_BRANDS
    if is_pip:
        result = sku_bogor if row.get("Branch") == "Bogor" else sku_def
    else:
        result = besides if pd.notna(besides) and str(besides).strip() else brand
    if pd.isna(result) or str(result).strip() == "":
        result = brand
    return str(result).strip().lower()

def load_data() -> pd.DataFrame:
    print("\n[1/7] Membaca dataset...")
    product_pipamas = pd.read_excel(PRODUCT_PIPAMAS, sheet_name="BREAKDOWN", header=1)
    product_pipamas = product_pipamas[["Eigen Code","Name","Grup SKU","GRUP SKU BOGOR"]]
    product_pipamas.columns = product_pipamas.columns.str.lower()

    product_lainnya = pd.read_excel(PRODUCT_LAINNYA, sheet_name="Report")
    validate_columns(product_lainnya, ["Code","Product Category"], "PRODUCT_LAINNYA")

    df = pd.read_excel(FILE_PATH)
    validate_columns(df, ["Invoice Date","Net Price","Salesman","Prod. Code","Brand Name"], "FILE_PATH")

    df = df.copy()

    # Match Excel/Power Query rule before branch, sales category, and ICI grouping.
    df["Salesman"] = normalize_salesman_series(df["Salesman"])

    df["Invoice Date"]    = pd.to_datetime(df["Invoice Date"], errors="coerce")
    df.dropna(subset=["Invoice Date"], inplace=True)
    df["Total_Revenue"]   = pd.to_numeric(df["Net Price"], errors="coerce").fillna(0)

    # Quantity is still needed for transaction quantity analysis, but ICI
    # Volume/Weight in the current export are already line totals.
    # Therefore DO NOT multiply Unit Volume/Net Weight by Quantity here.
    invoiced_qty_col = _first_existing_column(df, ["Invoiced Qty", "Invoiced_Qty", "Quantity"])
    if invoiced_qty_col is not None:
        df["Quantity"] = pd.to_numeric(df[invoiced_qty_col], errors="coerce").fillna(0.0)
    elif {"Unit", "Qty"}.issubset(set(df.columns)):
        df["Quantity"] = pd.to_numeric(df["Unit"], errors="coerce").fillna(0.0) + pd.to_numeric(df["Qty"], errors="coerce").fillna(0.0)
    elif "Quantity" in df.columns:
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0.0)
    else:
        df["Quantity"] = 0.0

    # Current rule from user:
    # use Volume and Weight directly from data; no multiplication by Quantity.
    volume_col = _first_existing_column(df, ["Volume", "Volume_Actual", "Line Volume", "Line_Volume"])
    if volume_col is not None:
        df["Volume"] = pd.to_numeric(df[volume_col], errors="coerce").fillna(0.0)
    else:
        df["Volume"] = 0.0

    weight_col = _first_existing_column(df, ["Weight", "Weight_Actual", "Line Weight", "Line_Weight"])
    if weight_col is not None:
        df["Weight"] = pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0)
    else:
        df["Weight"] = 0.0

    has_status_source     = "Status" in df.columns
    if not has_status_source: df["Status"] = "UNKNOWN"
    df["Status_Clean"]    = df["Status"].astype(str).str.strip().str.lower()
    df["__has_status_source"] = has_status_source

    df["YearMonth"]    = df["Invoice Date"].dt.to_period("M")
    df["YearWeek"]     = df["Invoice Date"].dt.to_period("W")
    df["YearQuarter"]  = df["Invoice Date"].dt.to_period("Q")
    df["Date_Only"]    = df["Invoice Date"].dt.normalize()

    if "Code" in df.columns:
        df = df.rename(columns={"Code": "Invoice Code"})

    # Match BigQuery view logic: use the Branch column from invoice source when available.
    # The salesman-derived branch is only a fallback; overwriting the source Branch
    # would make Monthly Revenue vs Actual Target differ from v_sales_vs_target_monthly.
    if "Branch" in df.columns:
        df["Branch"] = df["Branch"].astype(str).str.strip()
    else:
        df["Branch"] = df["Salesman"].apply(assign_branch)
    df["Branch_Mapped_From_Salesman"] = df["Salesman"].apply(assign_branch)
    df["Sales_Category"]   = df["Salesman"].apply(sales_category_from_code)
    df["Sales_Channel"]    = df.apply(sales_channel_from_row, axis=1)
    df = pd.merge(df, product_pipamas, left_on="Prod. Code", right_on="eigen code", how="left")
    df = pd.merge(df, product_lainnya[["Code","Product Category"]], left_on="Prod. Code", right_on="Code", how="left")
    df["sku"] = df.apply(assign_sku, axis=1)

    drop_cols = ["grup sku","grup sku bogor","Product Category"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    if "Sales Div." not in df.columns:
        df["Sales Div."] = df["Salesman"].astype(str).str[:2].replace("", "Unknown")

    print(f"[OK] Data berhasil dibaca: {len(df):,} rows")
    return df

# =============================================================================
# 4. METRICS
# =============================================================================

def dim_compare(df_a, df_b, col):
    a   = df_a.groupby(col)["Total_Revenue"].sum()
    b   = df_b.groupby(col)["Total_Revenue"].sum()
    out = pd.concat([a.rename("Rev_A"), b.rename("Rev_B")], axis=1).fillna(0)
    out["Delta"] = out["Rev_A"] - out["Rev_B"]
    out["Pct"]   = safe_pct(out["Delta"], out["Rev_B"])
    return out.sort_values("Delta", ascending=False).reset_index()

def dim_compare_multi(df_a, df_b, cols):
    """Compare current vs previous period by multiple dimensions.

    Used for Retail/Project/Agen channel x Salesman insight.
    """
    if df_a is None or df_a.empty:
        a = pd.Series(dtype=float)
    else:
        a = df_a.groupby(cols)["Total_Revenue"].sum()

    if df_b is None or df_b.empty:
        b = pd.Series(dtype=float)
    else:
        b = df_b.groupby(cols)["Total_Revenue"].sum()

    out = pd.concat([a.rename("Rev_A"), b.rename("Rev_B")], axis=1).fillna(0)
    out["Delta"] = out["Rev_A"] - out["Rev_B"]
    out["Pct"] = safe_pct(out["Delta"], out["Rev_B"])
    return out.sort_values("Delta", ascending=False).reset_index()


def pareto_analysis(df_in, col):
    agg   = df_in.groupby(col)["Total_Revenue"].sum().sort_values(ascending=False)
    total = agg.sum()
    if total == 0 or agg.empty:
        return pd.DataFrame(columns=["entity","revenue","cumulative_pct"]), 0, 0.0
    out   = pd.DataFrame({"entity": agg.index, "revenue": agg.values})
    out["cumulative_pct"] = out["revenue"].cumsum() / total * 100
    n_80  = int((out["cumulative_pct"] <= 80).sum() + 1)
    pct_e80 = n_80 / len(out) * 100 if len(out) else 0.0
    return out.head(12), n_80, pct_e80

def salesman_efficiency(df_in):
    g = df_in.groupby("Salesman").agg(
        Revenue=("Total_Revenue","sum"),
        Trx    =("Total_Revenue","count"),
    ).reset_index()
    if g.empty:
        return pd.DataFrame(columns=["Salesman","Score"])
    g["AvgTrx"]   = g["Revenue"] / g["Trx"].replace(0, np.nan)
    rev_max        = g["Revenue"].max() or 1
    basket_max     = g["AvgTrx"].max() or 1
    g["Score"]     = ((g["Revenue"]/rev_max)*50 + (g["AvgTrx"]/basket_max)*50).round(1)
    return g.sort_values("Score", ascending=False)

def calculate_metrics(df: pd.DataFrame) -> dict:
    print("\n[2/7] Menghitung metrik...")
    date_min      = df["Invoice Date"].min()
    date_max      = df["Invoice Date"].max()
    date_max_norm = pd.Timestamp(date_max).normalize()
    now_str       = datetime.now().strftime("%d %B %Y - %H:%M WIB")

    all_months    = pd.Series(df["YearMonth"].dropna().unique()).sort_values().tolist()
    all_weeks     = pd.Series(df["YearWeek"].dropna().unique()).sort_values().tolist()
    all_quarters  = pd.Series(df["YearQuarter"].dropna().unique()).sort_values().tolist()

    if not all_months or not all_weeks:
        raise ValueError("Dataset tidak memiliki periode bulan/minggu valid.")

    period_bini  = all_months[-1]
    period_blalu = all_months[-2] if len(all_months) >= 2 else period_bini
    period_mini  = all_weeks[-1]
    period_mlalu = all_weeks[-2] if len(all_weeks) >= 2 else period_mini
    period_qini  = all_quarters[-1] if all_quarters else date_max.to_period("Q")

    df_bini  = df[df["YearMonth"] == period_bini]
    df_blalu = df[df["YearMonth"] == period_blalu]
    df_mini  = df[df["YearWeek"]  == period_mini]
    df_mlalu = df[df["YearWeek"]  == period_mlalu]
    df_qtd, df_prev_qtd, q_start, prev_q_start, prev_q_end = quarter_to_date_frames(df, date_max_norm)
    df_ytd, df_prev_ytd, y_start, prev_y_start, prev_y_end = year_to_date_frames(df, date_max_norm)

    rev_bini  = df_bini["Total_Revenue"].sum()
    rev_blalu = df_blalu["Total_Revenue"].sum()
    pct_m     = delta_pct(rev_bini, rev_blalu)

    # Daily report pulse: always use DoD so every report shows day-over-day movement.
    # Previous day means the latest earlier invoice date available in the dataset.
    df_today = df[df["Date_Only"].eq(date_max_norm)].copy()
    previous_dates = pd.Series(df.loc[df["Date_Only"].lt(date_max_norm), "Date_Only"].dropna().unique()).sort_values()
    prev_date_dod = pd.Timestamp(previous_dates.iloc[-1]).normalize() if len(previous_dates) else date_max_norm
    df_prev_day = df[df["Date_Only"].eq(prev_date_dod)].copy()

    pulse_is_wow = False
    pulse_label, pulse_name  = "DoD", "Daily"
    pulse_title              = "Day-over-day versus previous data day"
    df_pulse, df_pulse_prev  = df_today, df_prev_day
    pulse_period_current     = f"{date_max_norm:%d %b %Y}"
    pulse_period_previous    = f"{prev_date_dod:%d %b %Y}"

    (
        df_qoq_current,
        df_qoq_previous,
        qoq_current_period,
        qoq_previous_period,
        qoq_current_start,
        qoq_current_end,
        qoq_previous_start,
        qoq_previous_end,
    ) = completed_quarter_frames(df, date_max_norm)
    rev_qoq_current = df_qoq_current["Total_Revenue"].sum()
    rev_qoq_previous = df_qoq_previous["Total_Revenue"].sum()
    pct_qoq_complete = delta_pct(rev_qoq_current, rev_qoq_previous) if rev_qoq_previous > 0 else np.nan
    has_qoq_complete = bool(rev_qoq_current > 0 and rev_qoq_previous > 0)
    qoq_current_label = str(qoq_current_period)
    qoq_previous_label = str(qoq_previous_period)
    qoq_current_date_range = f"{qoq_current_start:%d %b %Y} - {qoq_current_end:%d %b %Y}"
    qoq_previous_date_range = f"{qoq_previous_start:%d %b %Y} - {qoq_previous_end:%d %b %Y}"

    (
        df_mom_completed_current,
        df_mom_completed_previous,
        mom_completed_current_period,
        mom_completed_previous_period,
        mom_completed_current_start,
        mom_completed_current_end,
        mom_completed_previous_start,
        mom_completed_previous_end,
    ) = completed_month_frames(df, date_max_norm)
    rev_mom_completed_current = df_mom_completed_current["Total_Revenue"].sum()
    rev_mom_completed_previous = df_mom_completed_previous["Total_Revenue"].sum()
    pct_mom_completed = delta_pct(rev_mom_completed_current, rev_mom_completed_previous) if rev_mom_completed_previous > 0 else np.nan
    has_completed_mom = bool(date_max_norm.day == 1 and rev_mom_completed_current > 0 and rev_mom_completed_previous > 0)
    mom_completed_current_label = mom_completed_current_period.strftime("%b %Y")
    mom_completed_previous_label = mom_completed_previous_period.strftime("%b %Y")
    mom_completed_current_date_range = f"{mom_completed_current_start:%d %b %Y} - {mom_completed_current_end:%d %b %Y}"
    mom_completed_previous_date_range = f"{mom_completed_previous_start:%d %b %Y} - {mom_completed_previous_end:%d %b %Y}"

    rev_pulse      = df_pulse["Total_Revenue"].sum()
    rev_pulse_prev = df_pulse_prev["Total_Revenue"].sum()
    pct_pulse      = delta_pct(rev_pulse, rev_pulse_prev)
    trx_pulse      = df_pulse["Total_Revenue"].count()
    trx_pulse_prev = df_pulse_prev["Total_Revenue"].count()
    avg_trx_pulse  = rev_pulse / trx_pulse if trx_pulse > 0 else 0
    avg_trx_pulse_prev = rev_pulse_prev / trx_pulse_prev if trx_pulse_prev > 0 else 0

    # Explicit DoD aliases for scorecard clarity. These currently equal the
    # pulse values because the report pulse is always DoD.
    rev_dod_current = rev_pulse
    rev_dod_previous = rev_pulse_prev
    pct_dod = pct_pulse
    trx_dod_current = trx_pulse
    trx_dod_previous = trx_pulse_prev
    avg_trx_dod_current = avg_trx_pulse
    avg_trx_dod_previous = avg_trx_pulse_prev

    has_status_source = bool(df["__has_status_source"].iloc[0]) if "__has_status_source" in df.columns and len(df) else False
    if has_status_source:
        paid_mask_bini  = df_bini["Status_Clean"].fillna("").eq("paid")
        paid_mask_blalu = df_blalu["Status_Clean"].fillna("").eq("paid")
        paid_bini  = df_bini.loc[paid_mask_bini,  "Total_Revenue"].sum()
        paid_blalu = df_blalu.loc[paid_mask_blalu, "Total_Revenue"].sum()
        ar_bini    = df_bini.loc[~paid_mask_bini,  "Total_Revenue"].sum()
        ar_blalu   = df_blalu.loc[~paid_mask_blalu,"Total_Revenue"].sum()
    else:
        paid_bini = paid_blalu = ar_bini = ar_blalu = 0.0
    ar_ratio   = ar_bini   / rev_bini * 100 if rev_bini > 0 else 0.0
    paid_ratio = paid_bini / rev_bini * 100 if rev_bini > 0 else 0.0

    rev_ytd      = df_ytd["Total_Revenue"].sum()
    rev_prev_ytd = df_prev_ytd["Total_Revenue"].sum()
    pct_ytd      = delta_pct(rev_ytd, rev_prev_ytd) if rev_prev_ytd else np.nan
    has_prev_ytd = bool(rev_prev_ytd > 0)

    # Daily commercial condition: report headline must follow DoD, not unfinished MTD MoM.
    if pct_dod >= THRESHOLD_NAIK:   kondisi, badge_color = "EKSPANSI",  M["green"]
    elif pct_dod <= THRESHOLD_TURUN: kondisi, badge_color = "KONTRAKSI", M["red"]
    else:                            kondisi, badge_color = "STABIL",    M["amber"]

    headline = f"Analisis Kinerja Komersial: Tren {kondisi} Harian Terdeteksi (DoD {pct_dod:+.1f}%)"

    # Actual target from Target 2026.xlsx
    target_pack = load_target_2026(PRODUCT_PIPAMAS)
    target_compare = build_target_comparisons(df, target_pack, date_max_norm)
    ici_compare = build_ici_actual_target_tables(df, target_pack.get("target_ici_vw_monthly", pd.DataFrame()), date_max_norm)

    # ICI MTD unit scorecard values. These use the same ICI actual-target logic
    # as the ICI unit chart: Warnamu is Weight; other ICI brands are Volume.
    ici_unit_monthly = ici_compare.get("monthly", pd.DataFrame())
    def _ici_unit_value(unit_type: str, col_name: str) -> float:
        if ici_unit_monthly is None or ici_unit_monthly.empty:
            return 0.0
        mask = (
            ici_unit_monthly["Month_Num"].astype(int).eq(int(period_bini.month))
            & ici_unit_monthly["Target_Unit_Type"].astype(str).str.upper().eq(unit_type)
        )
        return float(pd.to_numeric(ici_unit_monthly.loc[mask, col_name], errors="coerce").fillna(0.0).sum()) if col_name in ici_unit_monthly.columns else 0.0

    ici_volume_actual_mtd = _ici_unit_value("VOLUME", "Actual_Qty")
    ici_volume_target_mtd = _ici_unit_value("VOLUME", "Target_Qty")
    ici_weight_actual_mtd = _ici_unit_value("WEIGHT", "Actual_Qty")
    ici_weight_target_mtd = _ici_unit_value("WEIGHT", "Target_Qty")
    ici_volume_achievement_pct = ici_volume_actual_mtd / ici_volume_target_mtd * 100 if ici_volume_target_mtd > 0 else np.nan
    ici_weight_achievement_pct = ici_weight_actual_mtd / ici_weight_target_mtd * 100 if ici_weight_target_mtd > 0 else np.nan

    ts_monthly = target_compare["monthly_vs_target"].copy()
    ts_monthly = ts_monthly.rename(columns={"YearMonth": "Period"})

    # Page 2 specific monthly chart: Total Sales excludes IC/ICI.
    ts_monthly_page2 = target_compare.get("monthly_vs_target_non_ici", target_compare["monthly_vs_target"]).copy()
    ts_monthly_page2 = ts_monthly_page2.rename(columns={"YearMonth": "Period"})

    page2_current_row = target_compare.get("monthly_vs_target_non_ici", pd.DataFrame())
    if page2_current_row is None or page2_current_row.empty:
        page2_current_row = target_compare["monthly_vs_target"].copy()
    page2_current = page2_current_row[page2_current_row["YearMonth"].eq(period_bini)].copy() if "YearMonth" in page2_current_row.columns else pd.DataFrame()
    page2_previous = page2_current_row[page2_current_row["YearMonth"].eq(period_blalu)].copy() if "YearMonth" in page2_current_row.columns else pd.DataFrame()
    page2_rev_bini = float(page2_current["Total_Revenue"].sum()) if not page2_current.empty else np.nan
    page2_rev_blalu = float(page2_previous["Total_Revenue"].sum()) if not page2_previous.empty else np.nan
    page2_target_rev_mo = float(page2_current["Target_Revenue"].sum()) if not page2_current.empty else np.nan
    page2_pct_m = delta_pct(page2_rev_bini, page2_rev_blalu) if pd.notna(page2_rev_bini) and pd.notna(page2_rev_blalu) else np.nan
    page2_target_gap = page2_rev_bini - page2_target_rev_mo if pd.notna(page2_rev_bini) and pd.notna(page2_target_rev_mo) else np.nan

    # Current month target must come from Target 2026.xlsx only.
    # Do not estimate target from previous month, because that can create a misleading Target Gap.
    target_monthly_df = target_compare["monthly_vs_target"][["YearMonth", "Target_Revenue"]].copy()
    target_rev_mo = _target_for_month(
        target_monthly_df,
        period_bini,
        np.nan,
    )

    # Make sure the Target Gap is the same source as the monthly target line chart.
    # This reads the current running month row from monthly_vs_target, which is built from Target 2026.xlsx.
    current_target_row = target_compare["monthly_vs_target"][target_compare["monthly_vs_target"]["YearMonth"].eq(period_bini)]
    target_actual_rev_mo = np.nan
    if not current_target_row.empty:
        target_rev_mo = float(current_target_row["Target_Revenue"].sum())
        target_actual_rev_mo = float(current_target_row["Total_Revenue"].sum())

    # Running/pulse target is allocated from monthly target by calendar-day proportion.
    # If target is unavailable, keep it as N/A instead of using previous-period estimation.
    target_rev_pulse = _target_for_date_window(
        target_monthly_df,
        df_pulse["Date_Only"].min() if not df_pulse.empty else date_max_norm,
        df_pulse["Date_Only"].max() if not df_pulse.empty else date_max_norm,
        np.nan,
    )

    target_basket    = avg_trx_pulse_prev * 1.05
    target_trx       = trx_pulse_prev  * 1.05
    # Target gap follows the same scope as the Monthly Revenue vs Actual Target chart:
    # actual and target both follow the BQ view branch scope.
    target_gap       = target_actual_rev_mo - target_rev_mo if pd.notna(target_actual_rev_mo) and pd.notna(target_rev_mo) and target_rev_mo > 0 else np.nan
    target_attainment = target_actual_rev_mo / target_rev_mo * 100 if pd.notna(target_actual_rev_mo) and pd.notna(target_rev_mo) and target_rev_mo > 0 else np.nan

    ts_weekly = df.groupby("YearWeek")["Total_Revenue"].sum().reset_index().rename(columns={"YearWeek":"Period","Total_Revenue":"Total_Revenue"})
    ts_weekly["Label"] = ts_weekly["Period"].apply(lambda p: f"W{p.start_time.isocalendar()[1]}\n{p.start_time.strftime('%d/%m')}")

    ts_quarterly = df.groupby("YearQuarter")["Total_Revenue"].sum().reset_index().rename(columns={"YearQuarter":"Period","Total_Revenue":"Total_Revenue"})
    ts_quarterly["Label"]  = ts_quarterly["Period"].astype(str)
    ts_quarterly["Growth"] = ts_quarterly["Total_Revenue"].pct_change() * 100

    pareto_branch, n80_br, pct80_br = pareto_analysis(df_bini, "Branch")
    pareto_sku,    n80_sk, pct80_sk = pareto_analysis(df_bini, "sku")
    pulse_branch = dim_compare(df_pulse, df_pulse_prev, "Branch")
    pulse_sales  = dim_compare(df_pulse, df_pulse_prev, "Salesman")
    pulse_sku    = dim_compare(df_pulse, df_pulse_prev, "sku")
    label_bini   = period_bini.strftime("%b %Y")
    label_blalu  = period_blalu.strftime("%b %Y")

    metrics = {
        "date_min": date_min, "date_max": date_max, "now_str": now_str,
        "label_bini": label_bini, "label_blalu": label_blalu,
        "rev_bini": rev_bini, "rev_blalu": rev_blalu,
        "rev_mini": rev_pulse, "rev_mlalu": rev_pulse_prev,
        "pct_m": pct_m, "pct_w": pct_pulse,
        "trx_mini": trx_pulse, "trx_mlalu": trx_pulse_prev,
        "avg_trx_mini": avg_trx_pulse, "avg_trx_mlalu": avg_trx_pulse_prev,
        "ar_bini": ar_bini, "ar_blalu": ar_blalu, "ar_ratio": ar_ratio,
        "paid_bini": paid_bini, "paid_blalu": paid_blalu, "paid_ratio": paid_ratio,
        "has_status_source": has_status_source,
        "rev_ytd": rev_ytd, "rev_prev_ytd": rev_prev_ytd, "pct_ytd": pct_ytd, "has_prev_ytd": has_prev_ytd,
        "ytd_current_period":  f"{y_start:%d %b %Y} - {date_max_norm:%d %b %Y}",
        "ytd_previous_period": f"{prev_y_start:%d %b %Y} - {prev_y_end:%d %b %Y}",
        "pulse_is_wow": pulse_is_wow, "pulse_label": pulse_label, "pulse_name": pulse_name,
        "pulse_title": pulse_title, "pulse_period_current": pulse_period_current,
        "pulse_period_previous": pulse_period_previous,
        "rev_pulse": rev_pulse, "rev_pulse_prev": rev_pulse_prev, "pct_pulse": pct_pulse,
        "rev_dod_current": rev_dod_current, "rev_dod_previous": rev_dod_previous, "pct_dod": pct_dod,
        "dod_current_date": date_max_norm, "dod_previous_date": prev_date_dod,
        "trx_pulse": trx_pulse, "trx_pulse_prev": trx_pulse_prev,
        "trx_dod_current": trx_dod_current, "trx_dod_previous": trx_dod_previous,
        "avg_trx_dod_current": avg_trx_dod_current, "avg_trx_dod_previous": avg_trx_dod_previous,
        "has_qoq_complete": has_qoq_complete,
        "qoq_current_label": qoq_current_label, "qoq_previous_label": qoq_previous_label,
        "qoq_current_date_range": qoq_current_date_range, "qoq_previous_date_range": qoq_previous_date_range,
        "rev_qoq_current": rev_qoq_current, "rev_qoq_previous": rev_qoq_previous, "pct_qoq_complete": pct_qoq_complete,
        "has_completed_mom": has_completed_mom,
        "mom_completed_current_label": mom_completed_current_label, "mom_completed_previous_label": mom_completed_previous_label,
        "mom_completed_current_date_range": mom_completed_current_date_range, "mom_completed_previous_date_range": mom_completed_previous_date_range,
        "rev_mom_completed_current": rev_mom_completed_current, "rev_mom_completed_previous": rev_mom_completed_previous, "pct_mom_completed": pct_mom_completed,
        "avg_trx_pulse": avg_trx_pulse, "avg_trx_pulse_prev": avg_trx_pulse_prev,
        "kondisi": kondisi, "badge_color": badge_color, "status_overall": kondisi, "headline": headline,
        "target_rev_mo": target_rev_mo, "target_rev_wk": target_rev_pulse, "target_rev_pulse": target_rev_pulse,
        "target_basket": target_basket, "target_trx": target_trx,
        "target_gap": target_gap, "target_attainment": target_attainment,
        "target_actual_rev_mo": target_actual_rev_mo,
        "page2_rev_bini": page2_rev_bini,
        "page2_rev_blalu": page2_rev_blalu,
        "page2_target_rev_mo": page2_target_rev_mo,
        "page2_pct_m": page2_pct_m,
        "page2_target_gap": page2_target_gap,
        "target_scope_note": "Monthly actual vs target follows dashboard scope: IC/ICI included; actual excludes Agen/Project/Dist; target excludes Project/Dist case-insensitively. Page 2 Total Sales excludes IC/ICI.",
        "target_pack": target_pack,
        "target_monthly": target_pack.get("target_monthly", pd.DataFrame()),
        "target_detail": target_pack.get("target_detail", pd.DataFrame()),
        "target_salesman_monthly": target_pack.get("target_salesman_monthly", pd.DataFrame()),
        "target_sku_monthly": target_pack.get("target_sku_monthly", pd.DataFrame()),
        "target_ici_vw_monthly": target_pack.get("target_ici_vw_monthly", pd.DataFrame()),
        "ici_actual_target_monthly": ici_compare.get("monthly", pd.DataFrame()),
        "ici_brand_actual_target": ici_compare.get("brand", pd.DataFrame()),
        "ici_measure_columns": ici_compare.get("measure_columns", {}),
        "ici_volume_actual_mtd": ici_volume_actual_mtd,
        "ici_volume_target_mtd": ici_volume_target_mtd,
        "ici_volume_achievement_pct": ici_volume_achievement_pct,
        "ici_weight_actual_mtd": ici_weight_actual_mtd,
        "ici_weight_target_mtd": ici_weight_target_mtd,
        "ici_weight_achievement_pct": ici_weight_achievement_pct,
        "salesman_vs_target": target_compare.get("salesman_vs_target", pd.DataFrame()),
        "sku_vs_target": target_compare.get("sku_vs_target", pd.DataFrame()),
        "ts_monthly": ts_monthly, "ts_monthly_page2": ts_monthly_page2, "ts_weekly": ts_weekly, "ts_quarterly": ts_quarterly,
        "wow_branch": pulse_branch, "mom_branch": dim_compare(df_bini, df_blalu, "Branch"),
        "wow_sales":  pulse_sales,  "pulse_branch": pulse_branch, "pulse_sales": pulse_sales,
        "sales_category_pulse": dim_compare(df_pulse, df_pulse_prev, "Sales_Category"),
        "sales_channel_pulse": dim_compare(df_pulse, df_pulse_prev, "Sales_Channel"),
        "sales_channel_sales_pulse": dim_compare_multi(df_pulse, df_pulse_prev, ["Sales_Channel", "Salesman"]),
        "pulse_sku": pulse_sku,
        "mom_sku": dim_compare(df_bini, df_blalu, "sku"),
        "pareto_branch": pareto_branch, "n80_br": n80_br, "pct80_br": pct80_br,
        "pareto_sku":    pareto_sku,    "n80_sk": n80_sk, "pct80_sk": pct80_sk,
        "eff_bini": salesman_efficiency(df_bini),
        "df_bini": df_bini, "df_blalu": df_blalu,
        "df_today": df_today, "df_prev_day": df_prev_day,
        "df_qoq_current": df_qoq_current, "df_qoq_previous": df_qoq_previous,
        "df_mom_completed_current": df_mom_completed_current, "df_mom_completed_previous": df_mom_completed_previous,
        "df_pulse": df_pulse, "df_pulse_prev": df_pulse_prev,
    }
    print("[OK] Metrics berhasil dihitung")
    return metrics

# =============================================================================
# 5. INLINE SVG CHARTS
# =============================================================================

SVG_FONT = "Arial, DejaVu Sans, sans-serif"

def _svg_text(text, x, y, size=14, weight="400", fill=None, anchor="start", extra=""):
    fill = fill or M["ink"]
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SVG_FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {extra}>{_safe(text)}</text>'

def _svg_tspan_lines(lines, x, y, size=13, fill=None, anchor="middle", line_gap=14):
    fill = fill or M["slate"]
    tspans = []
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else line_gap
        tspans.append(f'<tspan x="{x:.1f}" dy="{dy}">{_safe(line)}</tspan>')
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SVG_FONT}" font-size="{size}" fill="{fill}" text-anchor="{anchor}">' + "".join(tspans) + '</text>'

def _linear(value, vmin, vmax, out_min, out_max):
    if vmax == vmin: return (out_min + out_max) / 2
    return out_min + (float(value) - vmin) / (vmax - vmin) * (out_max - out_min)

def _nice_min_max(values, include_zero=True, pad=0.10):
    vals = [float(v) for v in values if pd.notna(v)]
    if not vals:
        return 0.0, 1.0

    vmin, vmax = min(vals), max(vals)

    # For positive-only business charts such as revenue, target, volume, and weight,
    # keep the Y-axis starting from zero. The previous padding logic could create
    # negative ticks even when all values were positive, which made charts look ambiguous.
    if include_zero and vmin >= 0:
        if math.isclose(vmax, 0):
            return 0.0, 1.0
        margin = abs(vmax) * pad
        return 0.0, vmax + margin

    if include_zero:
        vmin, vmax = min(vmin, 0.0), max(vmax, 0.0)

    if math.isclose(vmin, vmax):
        if vmax == 0:
            return 0.0, 1.0
        margin = abs(vmax) * pad
        return vmin - margin, vmax + margin

    margin = (vmax - vmin) * pad
    return vmin - margin, vmax + margin

def _tick_values(vmin, vmax, n=5):
    if vmax == vmin: return [vmin]
    return list(np.linspace(vmin, vmax, n))

def _unit_label(max_abs):
    _, unit, _ = rupiah_scale(max_abs)
    return unit

def _empty_svg(title, subtitle="Data tidak tersedia", width=980, height=360):
    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_svg_text(title,22,34,16,"700",M["blue"])}
      <rect x="22" y="70" width="{width-44}" height="{height-100}" rx="16" fill="{M["soft"]}" stroke="{M["line"]}"/>
      {_svg_text(subtitle,width/2,height/2,16,"600",M["slate"],"middle")}
    </svg>'''

def svg_monthly_combo(ts_monthly, title="Monthly Revenue vs Actual Target", actual_label="Total Sales", target_label="Target Sales"):
    if ts_monthly.empty:
        return _empty_svg(title)

    df = ts_monthly.copy().reset_index(drop=True)

    # Backward compatibility: older data may only have Total_Revenue.
    if "Target_Revenue" not in df.columns:
        df["Target_Revenue"] = 0.0
    if "Label" not in df.columns:
        if "Period" in df.columns:
            df["Label"] = df["Period"].apply(lambda p: pd.Period(p, freq="M").strftime("%m-%Y"))
        else:
            df["Label"] = [str(i + 1) for i in range(len(df))]

    df["Total_Revenue"] = pd.to_numeric(df["Total_Revenue"], errors="coerce").fillna(0.0)
    df["Target_Revenue"] = pd.to_numeric(df["Target_Revenue"], errors="coerce").fillna(0.0)

    width, height = 980, 620
    x0, y0, cw, ch = 86, 94, 840, 238
    gb_y, gb_h = 485, 82

    actual_values = df["Total_Revenue"].astype(float).tolist()
    target_values = df["Target_Revenue"].astype(float).tolist()
    all_values = actual_values + target_values
    max_abs = max(max(all_values), 1.0)
    vmin, vmax = _nice_min_max(all_values, include_zero=True, pad=0.08)
    ticks = _tick_values(vmin, vmax, 5)

    n = len(df)
    xs = [x0 + (cw * i / max(1, n - 1)) for i in range(n)]
    actual_ys = [_linear(v, vmin, vmax, y0 + ch, y0) for v in actual_values]
    target_ys = [_linear(v, vmin, vmax, y0 + ch, y0) for v in target_values]

    grid = []
    for tv in ticks:
        yy = _linear(tv, vmin, vmax, y0 + ch, y0)
        grid.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+cw}" y2="{yy:.1f}" stroke="{M["line"]}" stroke-width="1"/>')
        grid.append(_svg_text(fmt_axis_value(tv, max_abs), x0 - 12, yy + 5, 13, "500", M["slate"], "end"))

    actual_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, actual_ys))
    target_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, target_ys))

    area = (
        f"M {xs[0]:.1f},{y0+ch:.1f} "
        + " ".join(f"L {x:.1f},{y:.1f}" for x, y in zip(xs, actual_ys))
        + f" L {xs[-1]:.1f},{y0+ch:.1f} Z"
    )

    labels = []
    for i, row in df.iterrows():
        actual = float(row["Total_Revenue"])
        target = float(row["Target_Revenue"])
        label_lines = str(row["Label"]).split(" ")

        # X-axis labels
        labels.append(_svg_tspan_lines(label_lines, xs[i], y0 + ch + 31, 12, M["slate"], "middle", 13))

        # Actual point + label. Only months up to the current invoice month are shown.
        labels.append(f'<circle cx="{xs[i]:.1f}" cy="{actual_ys[i]:.1f}" r="4.8" fill="{M["white"]}" stroke="{M["blue"]}" stroke-width="3"/>')
        label_y = max(y0 + 18, actual_ys[i] - 9)
        label_text = fmt_axis_value(actual, max_abs)
        if actual >= 1e9:
            label_text += "B"
        elif actual >= 1e6:
            label_text += "M"
        labels.append(_svg_text(label_text, xs[i], label_y, 11, "700", M["blue"], "middle"))

        # Target point marker, smaller so it does not dominate the actual line.
        if target > 0:
            labels.append(f'<rect x="{xs[i]-3.2:.1f}" y="{target_ys[i]-3.2:.1f}" width="6.4" height="6.4" rx="1.5" fill="{M["red"]}" opacity="0.95"/>')

    # Growth bars use actual revenue only.
    growth = df["Growth"].fillna(0).astype(float).tolist() if "Growth" in df.columns else [0.0] * len(df)
    gmin, gmax = _nice_min_max(growth, include_zero=True, pad=0.15)
    gmax_abs = max(abs(gmin), abs(gmax), 1)
    zero_y = _linear(0, -gmax_abs, gmax_abs, gb_y + gb_h, gb_y)

    bars = []
    bar_w = min(64, cw / max(1, n) * 0.42)
    for i, g in enumerate(growth):
        gy = _linear(g, -gmax_abs, gmax_abs, gb_y + gb_h, gb_y)
        y_top = min(gy, zero_y)
        h = max(2, abs(zero_y - gy))
        color = M["green"] if g >= 0 else M["red"]
        bars.append(f'<rect x="{xs[i]-bar_w/2:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="3" fill="{color}" opacity="0.88"/>')
        if i > 0 and actual_values[i] != 0:
            txt_y = y_top - 7 if g >= 0 else y_top + h + 15
            bars.append(_svg_text(fmt_pct(g), xs[i], txt_y, 10, "700", color, "middle"))

    g_ticks = [-gmax_abs, 0, gmax_abs]
    g_axis = []
    for gt in g_ticks:
        yy = _linear(gt, -gmax_abs, gmax_abs, gb_y + gb_h, gb_y)
        g_axis.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+cw}" y2="{yy:.1f}" stroke="{M["line"]}" stroke-width="1" stroke-dasharray="3 4"/>')
        g_axis.append(_svg_text(f"{gt:+.0f}%", x0 - 12, yy + 5, 12, "500", M["slate"], "end"))

    legend_y = 60
    # Dynamic legend placement prevents long labels from colliding.
    legend_line_1_x1 = 365
    legend_line_1_x2 = legend_line_1_x1 + 36
    legend_text_1_x = legend_line_1_x2 + 10
    label1_width = max(74, min(180, len(str(actual_label)) * 6.6))
    legend_line_2_x1 = legend_text_1_x + label1_width + 26
    legend_line_2_x2 = legend_line_2_x1 + 36
    legend_text_2_x = legend_line_2_x2 + 10

    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_svg_text(title, 22, 34, 17, "800", M["blue"])}
      {_svg_text(_unit_label(max_abs), 22, 80, 12, "600", M["slate"])}

      <line x1="{legend_line_1_x1}" y1="{legend_y-1}" x2="{legend_line_1_x2}" y2="{legend_y-1}" stroke="{M["blue"]}" stroke-width="4" stroke-linecap="round"/>
      {_svg_text(actual_label, legend_text_1_x, legend_y+4, 12, "700", M["slate"])}
      <line x1="{legend_line_2_x1}" y1="{legend_y-1}" x2="{legend_line_2_x2}" y2="{legend_y-1}" stroke="{M["red"]}" stroke-width="4" stroke-dasharray="8 5" stroke-linecap="round"/>
      {_svg_text(target_label, legend_text_2_x, legend_y+4, 12, "700", M["slate"])}

      {"".join(grid)}
      <line x1="{x0}" y1="{y0+ch}" x2="{x0+cw}" y2="{y0+ch}" stroke="{M["line"]}" stroke-width="1.3"/>
      <path d="{area}" fill="{M["blue"]}" opacity="0.13"/>
      <polyline points="{actual_points}" fill="none" stroke="{M["blue"]}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>
      <polyline points="{target_points}" fill="none" stroke="{M["red"]}" stroke-width="4" stroke-dasharray="10 7" stroke-linejoin="round" stroke-linecap="round"/>
      {"".join(labels)}

      {_svg_text("Actual Monthly Growth", 22, gb_y - 22, 14, "800", M["slate"])}
      {"".join(g_axis)}
      <line x1="{x0}" y1="{zero_y:.1f}" x2="{x0+cw}" y2="{zero_y:.1f}" stroke="{M["slate"]}" stroke-width="1"/>
      {"".join(bars)}
    </svg>'''


def svg_weekly_pulse(ts_weekly):
    if ts_weekly.empty: return _empty_svg("Weekly Revenue Pulse")
    df = ts_weekly.tail(12).copy().reset_index(drop=True)
    width, height = 980, 455
    x0, y0, cw, ch = 82, 70, 850, 285
    values  = df["Total_Revenue"].astype(float).tolist()
    max_abs = max(max(values), 1.0)
    vmin, vmax = _nice_min_max(values, include_zero=True, pad=0.12)
    ticks = _tick_values(vmin, vmax, 5)
    n     = len(df)
    step  = cw / max(1, n)
    bar_w = step * 0.58
    xs    = [x0 + step*i + step/2 for i in range(n)]
    zero_y= _linear(0, vmin, vmax, y0+ch, y0)
    grid  = []
    for tv in ticks:
        yy = _linear(tv, vmin, vmax, y0+ch, y0)
        grid.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+cw}" y2="{yy:.1f}" stroke="{M["line"]}" stroke-width="1"/>')
        grid.append(_svg_text(fmt_axis_value(tv, max_abs), x0-12, yy+5, 13, "500", M["slate"], "end"))
    bars = []
    label_idx = set(pd.Series(values).nlargest(min(3, len(values))).index.tolist())
    if values: label_idx.add(len(values)-1)
    for i, v in enumerate(values):
        yy    = _linear(v, vmin, vmax, y0+ch, y0)
        y_top = min(yy, zero_y)
        bh    = max(2, abs(zero_y - yy))
        bars.append(f'<rect x="{xs[i]-bar_w/2:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{M["blue"]}" opacity="0.90"/>')
        lines = str(df.loc[i,"Label"]).split("\n")
        bars.append(_svg_tspan_lines(lines, xs[i], y0+ch+28, 12, M["slate"], "middle", 13))
        if i in label_idx:
            bars.append(_svg_text(fmt_rp_smart(v), xs[i], max(y0+18, y_top-8), 12, "700", M["ink"], "middle"))
    if len(values) >= 2:
        last_change = delta_pct(values[-1], values[-2])
        note = f"Minggu terakhir vs minggu sebelumnya: {fmt_pct(last_change)}"
    else:
        note = "Revenue mingguan berdasarkan invoice sales."
    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_svg_text("Weekly Revenue - Last 12 Weeks",22,36,17,"800",M["blue"])}
      {_svg_text(_unit_label(max_abs),22,61,12,"600",M["slate"])}
      {_svg_text(note,22,84,12,"700",M["slate"])}
      {"".join(grid)}
      <line x1="{x0}" y1="{y0+ch}" x2="{x0+cw}" y2="{y0+ch}" stroke="{M["line"]}" stroke-width="1.3"/>
      {"".join(bars)}
    </svg>'''

def _prepare_delta(df_dim, label_col, limit):
    if df_dim.empty or "Delta" not in df_dim.columns:
        return pd.DataFrame(columns=[label_col,"Delta","Pct"])
    out = df_dim.copy()
    out["AbsDelta"] = out["Delta"].abs()
    out = out.nlargest(limit, "AbsDelta").sort_values("Delta", ascending=True).reset_index(drop=True)
    return out

def svg_delta_bar(df_dim, label_col, title, limit=7):
    df = _prepare_delta(df_dim, label_col, limit)
    if df.empty: return _empty_svg(title)
    width, height = 980, 420
    x0, y0, cw, ch = 250, 70, 660, 285
    values  = df["Delta"].astype(float).tolist()
    max_abs = max(max(abs(v) for v in values), 1.0)
    n       = len(df)
    row_h   = ch / max(n, 1)
    zero_x  = x0 + cw / 2
    scale   = (cw/2) / (max_abs * 1.20)
    ticks   = [-max_abs, -max_abs/2, 0, max_abs/2, max_abs]
    grid    = []
    for t in ticks:
        xx = zero_x + t * scale
        grid.append(f'<line x1="{xx:.1f}" y1="{y0-8}" x2="{xx:.1f}" y2="{y0+ch+8}" stroke="{M["line"]}" stroke-width="1"/>')
        grid.append(_svg_text(fmt_axis_value(t, max_abs), xx, y0+ch+32, 12, "500", M["slate"], "middle"))
    grid.append(f'<line x1="{zero_x:.1f}" y1="{y0-10}" x2="{zero_x:.1f}" y2="{y0+ch+10}" stroke="{M["slate"]}" stroke-width="1.5"/>')
    bars = []
    for i, row in df.iterrows():
        y_mid   = y0 + row_h*i + row_h/2
        value   = float(row["Delta"])
        bar_len = abs(value) * scale
        x_bar   = zero_x if value >= 0 else zero_x - bar_len
        color   = M["green"] if value >= 0 else M["red"]
        bars.append(_svg_text(truncate_text(row[label_col], 22), x0-18, y_mid+5, 14, "600", M["ink"], "end"))
        bars.append(f'<rect x="{x_bar:.1f}" y="{y_mid-10:.1f}" width="{bar_len:.1f}" height="20" rx="4" fill="{color}"/>')
        if value >= 0:
            label_x, anchor, label_fill = x_bar + bar_len + 10, "start", M["ink"]
        else:
            if bar_len >= 72: label_x, anchor, label_fill = zero_x - 10, "end", M["white"]
            else:              label_x, anchor, label_fill = x_bar - 10, "end", M["ink"]
        bars.append(_svg_text(fmt_rp_smart(value), label_x, y_mid+5, 13, "800", label_fill, anchor))
        pct_txt = f"{arrow(row['Pct'])} {fmt_pct(row['Pct'])}"
        bars.append(_svg_text(pct_txt, width-26, y_mid+5, 12, "700", color, "end"))
        bars.append(f'<line x1="{x0-8}" y1="{y_mid+row_h/2-1:.1f}" x2="{width-24}" y2="{y_mid+row_h/2-1:.1f}" stroke="{M["line"]}" stroke-width="0.8"/>')
    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_svg_text(title,22,36,17,"800",M["teal"])}
      {_svg_text(_unit_label(max_abs),x0,56,12,"600",M["slate"])}
      {_svg_text("%",width-28,56,12,"700",M["slate"],"end")}
      {"".join(grid)}{"".join(bars)}
    </svg>'''

def svg_efficiency(df_eff, limit=8):
    if df_eff.empty: return _empty_svg("Top Salesman Efficiency Score")
    df = df_eff.head(limit).sort_values("Score", ascending=True).reset_index(drop=True)
    width, height = 980, 420
    x0, y0, cw, ch = 230, 68, 680, 285
    n    = len(df)
    row_h= ch / max(n, 1)
    grid = []
    for t in [0,20,40,60,80,100]:
        xx = x0 + cw * t / 100
        grid.append(f'<line x1="{xx:.1f}" y1="{y0-8}" x2="{xx:.1f}" y2="{y0+ch+8}" stroke="{M["line"]}" stroke-width="1"/>')
        grid.append(_svg_text(str(t), xx, y0+ch+32, 12, "500", M["slate"], "middle"))
    bars = []
    for i, row in df.iterrows():
        y_mid = y0 + row_h*i + row_h/2
        score = float(row["Score"])
        bw    = cw * score / 100
        bars.append(_svg_text(truncate_text(row["Salesman"], 18), x0-18, y_mid+5, 14, "600", M["ink"], "end"))
        bars.append(f'<rect x="{x0:.1f}" y="{y_mid-10:.1f}" width="{bw:.1f}" height="20" rx="4" fill="{M["blue2"]}"/>')
        bars.append(_svg_text(f"{score:.1f}", x0+bw+10, y_mid+5, 13, "800", M["ink"], "start"))
        bars.append(f'<line x1="{x0-8}" y1="{y_mid+row_h/2-1:.1f}" x2="{width-24}" y2="{y_mid+row_h/2-1:.1f}" stroke="{M["line"]}" stroke-width="0.8"/>')
    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_svg_text("Top Salesman Efficiency Score",22,36,17,"800",M["teal"])}
      {_svg_text("Skor efektivitas (0-100)",x0,y0+ch+56,12,"600",M["slate"])}
      {"".join(grid)}{"".join(bars)}
    </svg>'''

def _donut_path(cx, cy, r_outer, r_inner, start_angle, end_angle):
    large_arc = 1 if (end_angle - start_angle) % (2*math.pi) > math.pi else 0
    x1 = cx + r_outer * math.cos(start_angle); y1 = cy + r_outer * math.sin(start_angle)
    x2 = cx + r_outer * math.cos(end_angle);   y2 = cy + r_outer * math.sin(end_angle)
    x3 = cx + r_inner * math.cos(end_angle);   y3 = cy + r_inner * math.sin(end_angle)
    x4 = cx + r_inner * math.cos(start_angle); y4 = cy + r_inner * math.sin(start_angle)
    return (f"M {x1:.2f} {y1:.2f} A {r_outer:.2f} {r_outer:.2f} 0 {large_arc} 1 {x2:.2f} {y2:.2f} "
            f"L {x3:.2f} {y3:.2f} A {r_inner:.2f} {r_inner:.2f} 0 {large_arc} 0 {x4:.2f} {y4:.2f} Z")

def _donut_single(df_in, title, x_origin, y_origin, width=445):
    div_rev = df_in.groupby("Sales Div.")["Total_Revenue"].sum().nlargest(4)
    if div_rev.empty or div_rev.sum() == 0:
        return (f'<rect x="{x_origin}" y="{y_origin}" width="{width}" height="290" rx="16" fill="{M["soft"]}"/>'
                f'<text x="{x_origin+width/2}" y="{y_origin+145}" text-anchor="middle" font-size="14" fill="{M["slate"]}">Data tidak tersedia</text>')
    colors = [M["navy"], M["blue"], M["sky"], M["amber"]]
    total  = float(div_rev.sum())
    cx, cy = x_origin + width*0.40, y_origin + 155
    ro, ri = 108, 63
    angle  = -math.pi / 2
    parts  = [_svg_text(title, x_origin+22, y_origin+34, 16, "800", M["teal"])]
    for idx, (label, val) in enumerate(div_rev.items()):
        frac       = float(val) / total
        next_angle = angle + frac * 2 * math.pi
        path       = _donut_path(cx, cy, ro, ri, angle, next_angle)
        parts.append(f'<path d="{path}" fill="{colors[idx%len(colors)]}" stroke="#FFFFFF" stroke-width="3"/>')
        mid = angle + (next_angle - angle) / 2
        tx  = cx + (ro+ri)/2 * math.cos(mid)
        ty  = cy + (ro+ri)/2 * math.sin(mid) + 5
        if frac >= 0.08:
            parts.append(_svg_text(f"{frac*100:.0f}%", tx, ty, 15, "800", M["white"], "middle"))
        lx, ly = x_origin + width*0.72, y_origin + 82 + idx*42
        parts.append(f'<rect x="{lx}" y="{ly-12}" width="16" height="16" rx="3" fill="{colors[idx%len(colors)]}"/>')
        parts.append(_svg_text(truncate_text(label, 14), lx+26, ly+1, 13, "700", M["ink"]))
        parts.append(_svg_text(fmt_rp_smart(val), lx+26, ly+19, 12, "600", M["slate"]))
        angle = next_angle
    parts.append(_svg_text("Division", cx, cy-3, 14, "700", M["slate"], "middle"))
    parts.append(_svg_text("Mix", cx, cy+18, 18, "800", M["ink"], "middle"))
    return "".join(parts)

def svg_division_mix(df_current, df_previous, label_current, label_previous):
    width, height = 980, 390
    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_donut_single(df_current,  "Division Mix " + label_current,  15,  18, 455)}
      {_donut_single(df_previous, "Division Mix " + label_previous, 510, 18, 455)}
    </svg>'''

def svg_pareto(df_p, title, n80, pct80):
    if df_p.empty: return _empty_svg(title)
    df = df_p.head(8).copy().reset_index(drop=True)
    width, height = 980, 480
    x0, y0, cw, ch = 82, 70, 850, 285
    values  = df["revenue"].astype(float).tolist()
    max_abs = max(max(values), 1.0)
    vmin, vmax = _nice_min_max(values, include_zero=True, pad=0.12)
    ticks = _tick_values(vmin, vmax, 5)
    n     = len(df)
    step  = cw / max(n, 1)
    bar_w = step * 0.58
    xs    = [x0 + step*i + step/2 for i in range(n)]
    zero_y= _linear(0, vmin, vmax, y0+ch, y0)
    grid  = []
    for tv in ticks:
        yy = _linear(tv, vmin, vmax, y0+ch, y0)
        grid.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+cw}" y2="{yy:.1f}" stroke="{M["line"]}" stroke-width="1"/>')
        grid.append(_svg_text(fmt_axis_value(tv, max_abs), x0-12, yy+5, 13, "500", M["slate"], "end"))
    pct_grid = []
    for p in [0,25,50,75,100]:
        yy = _linear(p, 0, 100, y0+ch, y0)
        pct_grid.append(_svg_text(f"{p}%", x0+cw+16, yy+5, 12, "600", M["slate"], "start"))
    bars = []
    for i, row in df.iterrows():
        v  = float(row["revenue"])
        yy = _linear(v, vmin, vmax, y0+ch, y0)
        bh = max(2, abs(zero_y - yy))
        bars.append(f'<rect x="{xs[i]-bar_w/2:.1f}" y="{yy:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{M["blue"]}" opacity="0.90"/>')
        bars.append(_svg_tspan_lines([truncate_text(row["entity"],10)], xs[i], y0+ch+28, 12, M["slate"], "middle", 13))
        if i < 3: bars.append(_svg_text(fmt_rp_smart(v), xs[i], max(y0+18, yy-8), 12, "800", M["ink"], "middle"))
    line_points = " ".join(f"{xs[i]:.1f},{_linear(float(df.loc[i,'cumulative_pct']),0,100,y0+ch,y0):.1f}" for i in range(n))
    markers = [f'<circle cx="{xs[i]:.1f}" cy="{_linear(float(df.loc[i,"cumulative_pct"]),0,100,y0+ch,y0):.1f}" r="4.8" fill="{M["amber"]}" stroke="#FFFFFF" stroke-width="2"/>' for i in range(n)]
    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_svg_text(title,22,36,17,"800",M["purple"])}
      {_svg_text(f"80% revenue = {n80} entitas ({pct80:.1f}%)",22,58,13,"800",M["slate"])}
      {_svg_text(_unit_label(max_abs),22,82,12,"600",M["slate"])}
      {"".join(grid)}{"".join(pct_grid)}
      <line x1="{x0}" y1="{y0+ch}" x2="{x0+cw}" y2="{y0+ch}" stroke="{M["line"]}" stroke-width="1.3"/>
      {"".join(bars)}
      <polyline points="{line_points}" fill="none" stroke="{M["amber"]}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
      {"".join(markers)}
      <line x1="{x0+cw-155}" y1="38" x2="{x0+cw-120}" y2="38" stroke="{M["amber"]}" stroke-width="3"/>
      {_svg_text("Cumulative %",x0+cw-110,43,12,"700",M["slate"])}
    </svg>'''

def svg_operational_placeholder(k):
    width, height = 980, 330
    rev = fmt_rp_smart(k["rev_bini"])
    target = fmt_rp_smart(k.get("target_rev_mo", 0))
    gap = fmt_rp_smart(k.get("target_gap", 0))
    attainment = k.get("target_attainment", np.nan)
    attainment_txt = "-" if pd.isna(attainment) else f"{attainment:.1f}%"
    return f'''<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
      <rect width="{width}" height="{height}" fill="#FFFFFF"/>
      {_svg_text("Commercial Execution Summary",22,38,17,"800",M["blue"])}
      <rect x="24" y="72" width="286" height="160" rx="18" fill="{M["soft"]}" stroke="{M["line"]}"/>
      {_svg_text("Revenue Bulan Berjalan",48,112,14,"800",M["slate"])}
      {_svg_text(rev,48,158,30,"800",M["ink"])}
      <rect x="345" y="72" width="286" height="160" rx="18" fill="#EFF6FF" stroke="#BFDBFE"/>
      {_svg_text("Target Bulan Berjalan",369,112,14,"800",M["blue"])}
      {_svg_text(target,369,158,28,"800",M["blue"])}
      {_svg_text("Pencapaian "+attainment_txt,369,188,13,"700",M["slate"])}
      <rect x="666" y="72" width="286" height="160" rx="18" fill="#FFF7ED" stroke="#FED7AA"/>
      {_svg_text("Gap Aktual vs Target",690,112,14,"800",M["amber"])}
      {_svg_text(gap,690,158,28,"800",M["amber"])}
      {_svg_text("Prioritas: closing invoice terdekat",690,188,13,"700",M["slate"])}
      <rect x="24" y="258" width="928" height="46" rx="12" fill="#F8FAFC" stroke="{M["line"]}"/>
      {_svg_text("Panel ini hanya memakai data sales invoice, target penjualan, cabang, salesman, SKU, dan unit ICI.",48,286,13,"700",M["slate"])}
    </svg>'''


def fmt_qty_smart(value: float, unit: str = "") -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    av = abs(value)
    if av >= 1_000_000:
        txt = f"{value/1_000_000:.1f}".rstrip("0").rstrip(".") + " Jt"
    elif av >= 1_000:
        txt = f"{value/1_000:.1f}".rstrip("0").rstrip(".") + " Rb"
    else:
        txt = f"{value:,.0f}"
    return f"{txt} {unit}".strip()


def _ici_actual_target_monthly_current(ici_df: pd.DataFrame, date_max) -> pd.DataFrame:
    if ici_df is None or ici_df.empty:
        return pd.DataFrame(columns=["Month_Num", "Month_Name", "Target_Unit_Type", "Actual_Qty", "Target_Qty", "Target_Revenue", "Gap_Qty", "AchievementPct"])
    dfx = ici_df.copy()
    dfx["Month_Num"] = pd.to_numeric(dfx["Month_Num"], errors="coerce")
    dfx = dfx[dfx["Month_Num"].notna()].copy()
    dfx["Month_Num"] = dfx["Month_Num"].astype(int)
    cur_month = int(pd.Timestamp(date_max).month)
    dfx = dfx[dfx["Month_Num"] <= cur_month].copy()
    for col in ["Actual_Qty", "Target_Qty", "Target_Revenue", "Gap_Qty", "AchievementPct"]:
        if col in dfx.columns:
            dfx[col] = pd.to_numeric(dfx[col], errors="coerce").fillna(0.0)
        else:
            dfx[col] = 0.0
    return dfx.sort_values(["Month_Num", "Target_Unit_Type"])


def svg_ici_vw_targets(ici_df: pd.DataFrame, date_max) -> str:
    dfx = _ici_actual_target_monthly_current(ici_df, date_max)
    if dfx.empty:
        return _empty_svg("ICI Actual vs Target", "Target atau realisasi unit ICI belum tersedia")

    months = sorted(dfx["Month_Num"].unique().tolist())
    width, height = 980, 560
    x0, cw = 108, 780
    top_y, panel_h = 118, 130
    bot_y = 336

    def unit_frame(unit_type):
        return dfx[dfx["Target_Unit_Type"].astype(str).str.upper().eq(unit_type)].set_index("Month_Num")

    def values(frame, col):
        return [float(frame[col].get(m, 0.0)) if col in frame.columns else 0.0 for m in months]

    vol = unit_frame("VOLUME")
    wei = unit_frame("WEIGHT")
    vol_actual, vol_target = values(vol, "Actual_Qty"), values(vol, "Target_Qty")
    wei_actual, wei_target = values(wei, "Actual_Qty"), values(wei, "Target_Qty")
    xs = [x0 + (cw * i / max(1, len(months) - 1)) for i in range(len(months))]

    parts = [
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        _svg_text("ICI Actual vs Target - Volume and Weight", 22, 34, 17, "800", M["purple"]),
        _svg_text("Realisasi unit dibanding target unit sampai bulan berjalan", 22, 58, 12, "700", M["slate"]),
        f'<line x1="570" y1="38" x2="610" y2="38" stroke="{M["blue"]}" stroke-width="4" stroke-linecap="round"/>',
        _svg_text("Actual", 620, 43, 12, "700", M["slate"]),
        f'<line x1="720" y1="38" x2="760" y2="38" stroke="{M["red"]}" stroke-width="4" stroke-dasharray="8 6" stroke-linecap="round"/>',
        _svg_text("Target", 770, 43, 12, "700", M["slate"]),
    ]

    def draw_panel(y0, title, unit_label, actual_vals, target_vals, color_actual):
        vals = actual_vals + target_vals
        max_abs = max(max(vals), 1.0)
        vmin, vmax = _nice_min_max(vals, include_zero=True, pad=0.12)
        ticks = _tick_values(vmin, vmax, 4)
        # Panel title is placed above the plot area so it does not collide with y-axis labels.
        out = [_svg_text(title, x0, y0 - 18, 13, "800", color_actual)]
        for tv in ticks:
            yy = _linear(tv, vmin, vmax, y0 + panel_h, y0)
            out.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+cw}" y2="{yy:.1f}" stroke="{M["line"]}" stroke-width="1"/>')
            out.append(_svg_text(fmt_qty_smart(tv, unit_label), x0 - 12, yy + 5, 11, "500", M["slate"], "end"))
        out.append(f'<line x1="{x0}" y1="{y0+panel_h}" x2="{x0+cw}" y2="{y0+panel_h}" stroke="{M["line"]}" stroke-width="1.3"/>')
        def pts(vals2):
            return " ".join(f"{x:.1f},{_linear(v, vmin, vmax, y0+panel_h, y0):.1f}" for x, v in zip(xs, vals2))
        out.append(f'<polyline points="{pts(actual_vals)}" fill="none" stroke="{color_actual}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
        out.append(f'<polyline points="{pts(target_vals)}" fill="none" stroke="{M["red"]}" stroke-width="4" stroke-dasharray="10 7" stroke-linejoin="round" stroke-linecap="round"/>')
        for vals2, color, label_last in [(actual_vals, color_actual, True), (target_vals, M["red"], False)]:
            for i, val in enumerate(vals2):
                yy = _linear(val, vmin, vmax, y0 + panel_h, y0)
                out.append(f'<circle cx="{xs[i]:.1f}" cy="{yy:.1f}" r="4.4" fill="#FFFFFF" stroke="{color}" stroke-width="3"/>')
                if i == len(vals2) - 1 and val > 0:
                    out.append(_svg_text(fmt_qty_smart(val, unit_label), xs[i], max(y0 + 14, yy - 8 if label_last else yy + 16), 10, "800", color, "middle"))
        for i, m in enumerate(months):
            out.append(_svg_text(f"{m:02d}-{pd.Timestamp(date_max).year}", xs[i], y0 + panel_h + 24, 11, "600", M["slate"], "middle"))
        return out

    parts.extend(draw_panel(top_y, "Volume Control", "Lt", vol_actual, vol_target, M["blue"]))
    parts.extend(draw_panel(bot_y, "Weight Control", "Kg", wei_actual, wei_target, M["amber"]))
    parts.append('</svg>')
    return "".join(parts)


def ici_target_summary(k: dict) -> dict:
    dfx = _ici_actual_target_monthly_current(k.get("ici_actual_target_monthly", pd.DataFrame()), k.get("date_max"))
    cur_month = int(pd.Timestamp(k.get("date_max")).month)
    cur = dfx[dfx["Month_Num"].eq(cur_month)].copy() if not dfx.empty else pd.DataFrame()

    def unit_stat(unit_type, col):
        if cur.empty:
            return 0.0
        return float(cur[cur["Target_Unit_Type"].astype(str).str.upper().eq(unit_type)][col].sum()) if col in cur.columns else 0.0

    volume_actual = unit_stat("VOLUME", "Actual_Qty")
    volume_target = unit_stat("VOLUME", "Target_Qty")
    weight_actual = unit_stat("WEIGHT", "Actual_Qty")
    weight_target = unit_stat("WEIGHT", "Target_Qty")
    revenue = float(cur["Target_Revenue"].sum()) if not cur.empty and "Target_Revenue" in cur.columns else 0.0
    volume_ach = volume_actual / volume_target * 100 if volume_target > 0 else np.nan
    weight_ach = weight_actual / weight_target * 100 if weight_target > 0 else np.nan

    raw_brand = k.get("ici_brand_actual_target", pd.DataFrame())
    top_brand, top_gap_qty, top_unit = "-", 0.0, ""
    if raw_brand is not None and not raw_brand.empty:
        rr = raw_brand.copy()
        rr["Gap_Qty"] = pd.to_numeric(rr.get("Gap_Qty", 0), errors="coerce").fillna(0.0)
        rr["AbsGap"] = rr["Gap_Qty"].abs()
        rr = rr.sort_values("AbsGap", ascending=False)
        if not rr.empty:
            top_brand = str(rr.iloc[0].get("Brand", rr.iloc[0].get("Target_SKU", "-")))
            top_gap_qty = float(rr.iloc[0].get("Gap_Qty", 0) or 0)
            top_unit = "Kg" if str(rr.iloc[0].get("Target_Unit_Type", "")).upper() == "WEIGHT" else "Lt"

    return {
        "volume_actual": volume_actual, "volume_target": volume_target, "volume_ach": volume_ach,
        "weight_actual": weight_actual, "weight_target": weight_target, "weight_ach": weight_ach,
        "revenue": revenue, "top_brand": top_brand, "top_gap_qty": top_gap_qty, "top_unit": top_unit,
    }


def ici_target_table(k: dict) -> str:
    raw = k.get("ici_brand_actual_target", pd.DataFrame())
    if raw is None or raw.empty:
        return '<div class="card pad"><div class="kicker">ICI Unit Target</div><div class="small-note">Target atau realisasi unit ICI belum tersedia.</div></div>'
    dfx = raw.copy()
    for col in ["Actual_Qty", "Target_Qty", "Gap_Qty", "AchievementPct", "Target_Revenue"]:
        dfx[col] = pd.to_numeric(dfx.get(col, 0), errors="coerce").fillna(0.0)
    dfx["AbsGap"] = dfx["Gap_Qty"].abs()
    dfx = dfx.sort_values("AbsGap", ascending=False).head(8)
    rows = []
    for _, row in dfx.iterrows():
        unit_label = "Kg" if str(row.get("Target_Unit_Type", "")).upper() == "WEIGHT" else "Lt"
        ach = row.get("AchievementPct", np.nan)
        ach_txt = f"{ach:.1f}%" if pd.notna(ach) and np.isfinite(ach) else "-"
        rows.append(
            f'<tr><td class="metric">{_safe(truncate_text(row.get("Brand", row.get("Target_SKU", "-")), 26))}</td>'
            f'<td>{_safe(row.get("Target_Unit_Type", "-"))}</td>'
            f'<td class="right">{_safe(fmt_qty_smart(row.get("Actual_Qty", 0), unit_label))}</td>'
            f'<td class="right">{_safe(fmt_qty_smart(row.get("Target_Qty", 0), unit_label))}</td>'
            f'<td class="right">{_safe(fmt_qty_smart(row.get("Gap_Qty", 0), unit_label))}</td>'
            f'<td class="right">{_safe(ach_txt)}</td></tr>'
        )
    return (f'<div class="card"><table class="mini-table">'
            f'<thead><tr><th>Brand</th><th>Unit</th><th class="right">Actual</th><th class="right">Target</th><th class="right">Gap</th><th class="right">Ach.</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')

def build_visuals(k):
    print("\n[3/7] Membuat inline HTML/SVG charts...")
    # Daily report: SKU velocity uses DoD, not MoM.
    # Gainers intentionally shows the best movers even when all SKUs are negative,
    # so the chart never disappears on a broadly weak day.
    sku_source = k.get("pulse_sku", pd.DataFrame())
    sku_losers  = sku_source[sku_source["Delta"] < 0].sort_values("Delta", ascending=True).head(8) if sku_source is not None and not sku_source.empty and "Delta" in sku_source.columns else pd.DataFrame()
    sku_gainers = sku_source.sort_values("Delta", ascending=False).head(8) if sku_source is not None and not sku_source.empty and "Delta" in sku_source.columns else pd.DataFrame()
    visuals = {
        "monthly":       svg_monthly_combo(
            k.get("ts_monthly_page2", k["ts_monthly"]),
            title="Monthly Revenue vs Actual Target (Non-ICI, exclude Agen & Project)",
            actual_label="Actual Non-ICI",
            target_label="Target Non-ICI",
        ),
        "weekly":        svg_weekly_pulse(k["ts_weekly"]),
        "branch_wow":    svg_delta_bar(k["pulse_branch"], "Branch", f"Branch Correction - {k['pulse_label']}", limit=7),
        "branch_mom":    svg_delta_bar(k["mom_branch"],   "Branch", "Branch Correction - Completed Month", limit=7),
        "sales_delta":   svg_delta_bar(k["pulse_sales"],  "Salesman", f"Sales Force Delta - {k['pulse_label']}", limit=8),
        "sales_eff":     svg_efficiency(k["eff_bini"], limit=8),
        "division":      svg_division_mix(k["df_bini"], k["df_blalu"], k["label_bini"], k["label_blalu"]),
        "pareto_branch": svg_pareto(k["pareto_branch"], "Revenue Concentration - Branch", k["n80_br"], k["pct80_br"]),
        "pareto_sku":    svg_pareto(k["pareto_sku"],    "Revenue Concentration - SKU",    k["n80_sk"], k["pct80_sk"]),
        "sku_losers":    svg_delta_bar(sku_losers,  "sku", "Top SKU Losers - DoD",   limit=8),
        "sku_gainers":   svg_delta_bar(sku_gainers, "sku", "Best SKU Movers - DoD",  limit=8),
        "operational_status": svg_operational_placeholder(k),
        "ici_vw":        svg_ici_vw_targets(k.get("ici_actual_target_monthly", pd.DataFrame()), k.get("date_max")),
    }
    print("[OK] Inline SVG charts berhasil dibuat")
    return visuals

# =============================================================================
# 6. AI INSIGHT LAYER - SECTIONAL GENERATION
# =============================================================================

AI_INSIGHT_ENABLED      = False
AI_ALLOW_TEMPLATE_FALLBACK = True    # Template dinamis aktif; AI tidak digunakan
AI_CACHE_ENABLED        = False
AI_CACHE_VERSION        = "v26_ici_actual_unit_whatsapp"
AI_TIMEOUT_SECONDS      = 45
AI_MAX_TOTAL_SECONDS    = 180        # total budget across all sections
AI_USE_JSON_SCHEMA      = True
AI_USE_RESPONSE_HEALING = True

OPENROUTER_API_KEY_ENV   = "OPENROUTER_API_KEY"
OPENROUTER_AI_MODEL_ENV  = "OPENROUTER_AI_MODEL"
OPENROUTER_BASE_URL      = "https://openrouter.ai/api/v1"
OPENROUTER_CHAT_URL      = f"{OPENROUTER_BASE_URL}/chat/completions"

# Model priority: env override first, then preferred list
def _resolve_models() -> List[str]:
    override = os.getenv(OPENROUTER_AI_MODEL_ENV, "").strip()
    base = [
        "openai/gpt-oss-20b:free",
        "openai/gpt-oss-120b:free",
        "openrouter/free",
        "nvidia/nemotron-nano-9b-v2:free",
        "google/gemma-4-31b-it:free",
    ]
    if override:
        return [override] + [m for m in base if m != override]
    return base

# ---------------------------------------------------------------------------
# Sectional definitions - each section requests only 2-5 fields
# ---------------------------------------------------------------------------
AI_SECTIONS = [
    {
        "name": "board",
        "fields": ["board_subtitle", "board_summary", "board_decision"],
        "include_directives": False,
        "context_keys": [
            "company","condition","headline","pulse_label",
            "month_to_date_revenue","previous_month_revenue","monthly_mom_pct",
            "pulse_revenue","pulse_pct","pulse_transactions","avg_basket","avg_basket_pct",
            "target_gap",
        ],
    },
    {
        "name": "monthly",
        "fields": ["monthly_subtitle", "monthly_readout", "monthly_action"],
        "include_directives": False,
        "context_keys": [
            "company","condition","month_to_date_revenue","previous_month_revenue",
            "monthly_mom_pct","target_monthly_revenue","target_gap",
        ],
    },
    {
        "name": "weekly",
        "fields": ["weekly_subtitle", "weekly_readout", "weekly_action"],
        "include_directives": False,
        "context_keys": [
            "company","condition","pulse_label","pulse_current_period","pulse_previous_period",
            "pulse_revenue","previous_pulse_revenue","pulse_pct",
            "pulse_transactions","previous_pulse_transactions","transaction_pulse_pct",
            "avg_basket","avg_basket_pct",
        ],
    },
    {
        "name": "branch",
        "fields": ["branch_subtitle", "branch_readout", "branch_action"],
        "include_directives": False,
        "context_keys": [
            "company","condition","pulse_label",
            "top_negative_branch_mom","top_positive_branch_mom","branch_mom_records",
        ],
    },
    {
        "name": "sales_delta",
        "fields": ["sales_delta_subtitle", "sales_delta_readout", "sales_delta_action"],
        "include_directives": False,
        "context_keys": [
            "company","condition","pulse_label","sales_code_rule",
            "top_negative_sales_pulse","top_positive_sales_pulse","sales_pulse_records",
            "sales_category_pulse_records",
        ],
    },
    {
        "name": "sales_eff",
        "fields": ["sales_eff_subtitle", "sales_eff_readout", "sales_eff_action"],
        "include_directives": False,
        "context_keys": ["company","condition","top_sales_efficiency","sales_code_rule"],
    },
    {
        "name": "portfolio",
        "fields": ["portfolio_subtitle", "portfolio_readout", "portfolio_action"],
        "include_directives": False,
        "context_keys": [
            "company","condition","month_to_date_revenue","previous_month_revenue",
        ],
    },
    {
        "name": "concentration",
        "fields": ["concentration_subtitle", "concentration_readout", "concentration_action"],
        "include_directives": False,
        "context_keys": [
            "company","condition","pareto_branch_80_count","pareto_sku_80_count",
            "month_to_date_revenue",
        ],
    },
    {
        "name": "product",
        "fields": ["product_subtitle", "product_readout", "product_action"],
        "include_directives": False,
        "context_keys": ["company","condition","top_sku_loser_mom","top_sku_gainer_mom","sku_mom_records"],
    },
    {
        "name": "directive",
        "fields": ["directive_recap"],
        "include_directives": True,
        "context_keys": [
            "company","condition","month_to_date_revenue","monthly_mom_pct","pulse_label",
            "pulse_revenue","pulse_pct","target_gap",
            "pareto_branch_80_count","pareto_sku_80_count",
            "top_negative_branch_mom","top_sku_loser_mom",
            "top_negative_sales_pulse","sales_code_rule",
        ],
    },
]

ALL_INSIGHT_FIELDS = (
    [f for sec in AI_SECTIONS for f in sec["fields"]] + ["ai_source_note"]
)

# ---------------------------------------------------------------------------
# Technical term sanitization - must never appear in PDF narration
# ---------------------------------------------------------------------------
_BANNED_TECH_TERMS = [
    r"\bai\b", r"\bfallback\b", r"\btemplate\b", r"\bjson\b", r"\bapi\b",
    r"\bopenrouter\b", r"\bmodel\b", r"\bprompt\b", r"\bscript\b", r"\bcache\b",
    r"\bfunction\b", r"\bif/else\b", r"\bjumat logic\b", r"friday logic",
    r"wow pulse as", r"qoq pulse as", r"ar logic", r"use wow", r"use qoq",
    r"response_format", r"status != paid", r"status = paid",
    r"jika belum jumat", r"hanya ditampilkan",
]
_BANNED_TECH_RE = re.compile("|".join(_BANNED_TECH_TERMS), re.IGNORECASE)

_GENERIC_PHRASES = {
    "diversifikasi", "mengoptimalkan", "optimasi logistik",
    "perubahan revenue", "ketergantungan", "stabilitas operasi",
    "meningkatkan kualitas", "meningkatkan efisiensi",
}

def _contains_banned_tech(text: str) -> bool:
    return bool(_BANNED_TECH_RE.search(text or ""))

def _is_generic(text: str) -> bool:
    norm = re.sub(r"\s+", " ", str(text or "")).strip().lower().rstrip(" .:-")
    return norm in _GENERIC_PHRASES

def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w%+.-]+\b", str(text or "")))

def _normalize_text(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "").strip())
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text

def _validate_field(key: str, value: str) -> Tuple[bool, str]:
    """Return (is_ok, cleaned_value). If not ok, reason is in second return position."""
    if not isinstance(value, str) or not value.strip():
        return False, "kosong"
    value = _normalize_text(value, 170 if key.endswith("subtitle") else 800)
    if _contains_banned_tech(value):
        return False, "mengandung istilah teknis"
    if _is_generic(value):
        return False, "terlalu generik"
    wc = _word_count(value)
    if key.endswith("subtitle") and (wc < 8 or len(value) < 40):
        return False, f"subtitle terlalu pendek ({wc} kata)"
    if (key.endswith("readout") or key.endswith("action") or key in {"board_summary","board_decision","directive_recap"}) and (wc < 30 or len(value) < 160):
        return False, f"readout/action terlalu pendek ({wc} kata)"
    return True, value

def _validate_directives(raw_list) -> Tuple[bool, list, str]:
    if not isinstance(raw_list, list):
        return False, [], "bukan list"
    directives = []
    for item in raw_list[:5]:
        if not isinstance(item, dict):
            continue
        directive = _normalize_text(item.get("directive",""), 90)
        detail    = _normalize_text(item.get("detail",""), 450)
        outcome   = _normalize_text(item.get("business_outcome",""), 90)
        combined  = f"{directive} {detail} {outcome}"
        if _contains_banned_tech(combined):
            continue
        if not directive or not detail:
            continue
        if _word_count(detail) < 15 or len(detail) < 80:
            continue
        directives.append({"directive": directive, "detail": detail, "business_outcome": outcome or "Management action"})
    if len(directives) < 5:
        return False, directives, f"hanya {len(directives)} dari 5 directives lolos validasi"
    return True, directives[:5], "OK"

# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------
def _as_float(v, default=0.0) -> float:
    try:
        if v is None or pd.isna(v): return default
        return float(v)
    except Exception: return default

def _records(df, label_col, limit=5, sort_by_abs=True):
    if df is None or df.empty: return []
    cols = [c for c in [label_col,"Delta","Pct","revenue","cumulative_pct","Score"] if c in df.columns]
    out  = df.copy()
    if sort_by_abs and "Delta" in out.columns:
        out = out.assign(_abs=out["Delta"].abs()).sort_values("_abs", ascending=False)
    clean = []
    for _, row in out.head(limit).iterrows():
        item = {}
        for c in cols:
            v = row[c]
            if isinstance(v, (np.integer, np.floating)): v = float(v)
            item[c] = v
        clean.append(item)
    return clean

def _top_negative(df, label_col):
    if df is None or df.empty or "Delta" not in df.columns: return "-", 0.0, 0.0
    row = df.sort_values("Delta", ascending=True).iloc[0]
    return str(row[label_col]), _as_float(row["Delta"]), _as_float(row.get("Pct",0))

def _top_positive(df, label_col):
    if df is None or df.empty or "Delta" not in df.columns: return "-", 0.0, 0.0
    row = df.sort_values("Delta", ascending=False).iloc[0]
    return str(row[label_col]), _as_float(row["Delta"]), _as_float(row.get("Pct",0))

def _json_default(obj):
    if isinstance(obj, (np.integer, np.floating)): return float(obj)
    if isinstance(obj, (pd.Timestamp, datetime)): return str(obj)
    return str(obj)

def _build_full_payload(k: dict) -> dict:
    neg_br,  neg_br_d,  neg_br_p  = _top_negative(k.get("mom_branch"),   "Branch")
    pos_br,  pos_br_d,  pos_br_p  = _top_positive(k.get("mom_branch"),   "Branch")
    neg_sal, neg_sal_d, neg_sal_p = _top_negative(k.get("pulse_sales"),  "Salesman")
    pos_sal, pos_sal_d, pos_sal_p = _top_positive(k.get("pulse_sales"),  "Salesman")
    sku_df   = k.get("mom_sku", pd.DataFrame())
    sku_lose = sku_df[sku_df["Delta"] < 0].sort_values("Delta", ascending=True)  if not sku_df.empty else sku_df
    sku_gain = sku_df[sku_df["Delta"] > 0].sort_values("Delta", ascending=False) if not sku_df.empty else sku_df
    neg_sku, neg_sku_d, neg_sku_p = _top_negative(sku_lose, "sku") if not sku_lose.empty else ("-", 0, 0)
    pos_sku, pos_sku_d, pos_sku_p = _top_positive(sku_gain, "sku") if not sku_gain.empty else ("-", 0, 0)
    top_eff  = k["eff_bini"].iloc[0].to_dict() if k.get("eff_bini") is not None and not k["eff_bini"].empty else {}

    return {
        "company":                    COMPANY_NAME,
        "report_title":               report_title(k),
        "period":                     date_range_text(k),
        "condition":                  k["kondisi"],
        "headline":                   k["headline"],
        "pulse_label":                k.get("pulse_label"),
        "pulse_current_period":       k.get("pulse_period_current"),
        "pulse_previous_period":      k.get("pulse_period_previous"),
        "month_to_date_revenue":      fmt_rp_smart(k["rev_bini"]),
        "previous_month_revenue":     fmt_rp_smart(k["rev_blalu"]),
        "monthly_mom_pct":            round(_as_float(k["pct_m"]), 1),
        "target_monthly_revenue":     fmt_rp_smart(k["target_rev_mo"]),
        "target_gap":                 fmt_rp_smart(k.get("target_gap", np.nan)),
        "pulse_revenue":              fmt_rp_smart(k["rev_pulse"]),
        "previous_pulse_revenue":     fmt_rp_smart(k["rev_pulse_prev"]),
        "pulse_pct":                  round(_as_float(k["pct_pulse"]), 1),
        "pulse_transactions":         int(k["trx_pulse"]),
        "previous_pulse_transactions":int(k["trx_pulse_prev"]),
        "transaction_pulse_pct":      round(delta_pct(k["trx_pulse"], k["trx_pulse_prev"]), 1),
        "avg_basket":                 fmt_rp_smart(k["avg_trx_pulse"]),
        "avg_basket_pct":             round(delta_pct(k["avg_trx_pulse"], k["avg_trx_pulse_prev"]), 1),
        "ytd_current_revenue":        fmt_rp_smart(k["rev_ytd"]),
        "ytd_previous_year_revenue":  fmt_rp_smart(k["rev_prev_ytd"]) if k.get("has_prev_ytd") else "tidak tersedia",
        "sales_code_rule":            "Kode salesman dengan suffix 30-39 = Sales Project; suffix 50-59 = Sales Agen. Contoh: PISLP39 = Sales Project, PISLP53 = Sales Agen. Gunakan kategori ini saat menyebut salesman.",
        "top_negative_branch_mom":    {"name": neg_br,  "delta": fmt_rp_smart(neg_br_d),  "pct": round(neg_br_p, 1)},
        "top_positive_branch_mom":    {"name": pos_br,  "delta": fmt_rp_smart(pos_br_d),  "pct": round(pos_br_p, 1)},
        "top_negative_sales_pulse":   {"name": neg_sal, "category": sales_category_from_code(neg_sal), "delta": fmt_rp_smart(neg_sal_d), "pct": round(neg_sal_p, 1)},
        "top_positive_sales_pulse":   {"name": pos_sal, "category": sales_category_from_code(pos_sal), "delta": fmt_rp_smart(pos_sal_d), "pct": round(pos_sal_p, 1)},
        "top_sku_loser_mom":          {"name": neg_sku, "delta": fmt_rp_smart(neg_sku_d), "pct": round(neg_sku_p, 1)},
        "top_sku_gainer_mom":         {"name": pos_sku, "delta": fmt_rp_smart(pos_sku_d), "pct": round(pos_sku_p, 1)},
        "pareto_branch_80_count":     int(k["n80_br"]),
        "pareto_sku_80_count":        int(k["n80_sk"]),
        "top_sales_efficiency":       {"salesman": top_eff.get("Salesman","-"), "score": float(top_eff.get("Score",0) or 0)},
        "branch_mom_records":         _records(k.get("mom_branch"),  "Branch",   6),
        "sales_pulse_records":        _records(k.get("pulse_sales"), "Salesman", 6),
        "sales_category_pulse_records": _records(k.get("sales_category_pulse"), "Sales_Category", 6),
        "sales_channel_pulse_records": _records(k.get("sales_channel_pulse"), "Sales_Channel", 6),
        "sales_channel_sales_pulse_records": _records(k.get("sales_channel_sales_pulse"), "Salesman", 12),
        "sku_mom_records":            _records(k.get("mom_sku"), "sku", 8),
    }

def _section_payload(full_payload: dict, context_keys: List[str]) -> dict:
    return {k: full_payload[k] for k in context_keys if k in full_payload}

# ---------------------------------------------------------------------------
# OpenRouter call helpers
# ---------------------------------------------------------------------------
def _section_schema(fields: List[str], include_directives: bool) -> dict:
    props    = {f: {"type": "string"} for f in fields}
    required = list(fields)
    if include_directives:
        props["board_directives"] = {
            "type": "array", "minItems": 5, "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "directive":        {"type": "string"},
                    "detail":           {"type": "string"},
                    "business_outcome": {"type": "string"},
                },
                "required": ["directive","detail","business_outcome"],
                "additionalProperties": False,
            },
        }
        required.append("board_directives")
    return {"type":"object","properties":props,"required":required,"additionalProperties":False}

def _section_prompt(section_name: str, fields: List[str], include_directives: bool, payload: dict) -> str:
    requested = list(fields) + (["board_directives"] if include_directives else [])
    field_rules = (
        "Aturan penulisan:\n"
        "- *_subtitle: 1 kalimat insight 10-22 kata, bukan label/judul.\n"
        "- *_readout: 2 kalimat 35-70 kata, menyebut minimal 1 angka, menjelaskan implikasi bisnis.\n"
        "- *_action: 2 kalimat 35-70 kata, menyebut tindakan manajemen spesifik dan area fokus.\n"
        "- directive_recap: 3-4 kalimat ringkasan anomali dan prioritas tindakan.\n"
    )
    directive_rules = (
        "board_directives: 5 item, masing-masing punya directive (judul pendek), detail (2 kalimat operasional, wajib menyebut minimal 1 angka), business_outcome. Tidak boleh menyebut PIC atau due date.\n"
        if include_directives else ""
    )
    return (
        f"Tulis insight eksekutif bahasa Indonesia untuk Board of Directors {COMPANY_NAME}.\n"
        f"Section: {section_name}\n"
        f"Field yang harus diisi: {json.dumps(requested, ensure_ascii=False)}\n"
        f"{field_rules}"
        f"{directive_rules}"
        "PENTING: Jangan menyebut istilah teknis seperti AI, cache, API, model, script, fallback, template, JSON, atau logic internal.\n"
        "PENTING: Gunakan aturan klasifikasi salesman: suffix 30-39 = Sales Project, suffix 50-59 = Sales Agen.\n"
        "Contoh: PISLP53 = Sales Agen, bukan Sales Project.\n"
        "Jangan mengarang angka di luar payload.\n"
        f"Payload metrik: {json.dumps(payload, ensure_ascii=False, default=_json_default)}\n"
        "Keluaran wajib JSON object valid sesuai response_format, tanpa markdown, tanpa pengantar."
    )

def _post_openrouter(api_key: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req  = urllib.request.Request(
        OPENROUTER_CHAT_URL, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  REPORT_DASHBOARD_URL,
            "X-Title":       f"{COMPANY_NAME} Executive Report",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {body_err[:800]}") from exc

def _is_rate_limit(msg: str) -> bool:
    m = str(msg or "").lower()
    return "429" in m or "rate limit" in m or "free-models-per-day" in m

def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text: raise ValueError("Response kosong")
    text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict): return parsed
        raise ValueError(f"Root bukan dict: {type(parsed).__name__}")
    except Exception as e1:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                parsed = json.loads(text[s:e+1])
                if isinstance(parsed, dict): return parsed
            except Exception as e2:
                raise ValueError(f"Parse gagal: {e2}. Preview: {text[:500]}") from e2
        raise ValueError(f"Tidak ada JSON object. {e1}. Preview: {text[:500]}") from e1

def _call_model_for_section(api_key: str, model: str, section: dict, full_payload: dict) -> dict:
    """Call one model for one section. Returns parsed JSON dict or raises."""
    ctx     = _section_payload(full_payload, section["context_keys"])
    prompt  = _section_prompt(section["name"], section["fields"], section["include_directives"], ctx)
    schema  = _section_schema(section["fields"], section["include_directives"])
    schema_name = f"section_{section['name']}"

    body = {
        "model":       model,
        "temperature": 0.12,
        "max_tokens":  1600 if not section["include_directives"] else 2400,
        "reasoning":   {"exclude": True},
        "messages": [
            {"role": "system", "content": (
                "Anda adalah senior analyst. Jawab hanya dengan JSON object valid sesuai response_format. "
                "Jangan gunakan markdown, jangan tulis pengantar, dan jangan tampilkan proses berpikir."
            )},
            {"role": "user", "content": prompt},
        ],
    }
    if AI_USE_JSON_SCHEMA:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        }
    else:
        body["response_format"] = {"type": "json_object"}
    if AI_USE_RESPONSE_HEALING:
        body["plugins"] = [{"id": "response-healing"}]

    # Try json_schema first, fall back to json_object for schema compatibility issues
    for attempt_mode in (["json_schema","json_object"] if AI_USE_JSON_SCHEMA else ["json_object"]):
        if attempt_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        try:
            resp = _post_openrouter(api_key, body)
        except RuntimeError as exc:
            if _is_rate_limit(str(exc)): raise
            if attempt_mode == "json_schema" and any(x in str(exc).lower() for x in ["schema","response_format","json_schema","unsupported"]):
                continue
            raise
        if "error" in resp:
            raise RuntimeError(f"OpenRouter error: {resp['error']}")
        choices = resp.get("choices") or []
        if not choices:
            raise RuntimeError("Tidak ada choices dalam response")
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(p.get("text","") if isinstance(p,dict) else str(p) for p in content)
        content = str(content).strip()
        if not content:
            raise RuntimeError("Content kosong")
        return _extract_json(content)
    raise RuntimeError("Semua mode gagal untuk section ini")


def sales_entity_label(salesman) -> str:
    """Readable subject label that respects sales hierarchy."""
    code = str(salesman or "-").strip().upper()
    category = sales_category_from_code(code)
    if category == "Supervisor":
        return f"area koordinasi {code} (Supervisor)"
    if category == "Cosales":
        return f"dukungan {code} (Cosales)"
    if category in {"Sales Project", "Sales Agen"}:
        return f"{code} ({category})"
    if category.startswith("Sales "):
        return f"{code} ({category})"
    return code


def sales_intervention_focus(salesman) -> str:
    """Action object that avoids treating supervisors as ordinary salesmen."""
    code = str(salesman or "-").strip().upper()
    category = sales_category_from_code(code)
    if category == "Supervisor":
        return f"area di bawah koordinasi {code}"
    if category == "Cosales":
        return f"dukungan cosales {code} terhadap pipeline prioritas"
    if category == "Sales Project":
        return f"pipeline project milik {code}"
    if category == "Sales Agen":
        return f"pipeline agen milik {code}"
    return f"pipeline milik {code}"


def sales_playbook_subject(salesman) -> str:
    """Benchmark subject that adapts to hierarchy role."""
    code = str(salesman or "-").strip().upper()
    category = sales_category_from_code(code)
    if category == "Supervisor":
        return f"pola koordinasi {code}"
    if category == "Cosales":
        return f"pola dukungan {code}"
    return f"pola eksekusi {code}"

# ---------------------------------------------------------------------------
# Fully dynamic insight pack - no static narrative fields
# ---------------------------------------------------------------------------
def _direction_word(value: float, positive_word: str = "menguat", negative_word: str = "melemah", flat_word: str = "stabil") -> str:
    value = _as_float(value)
    if value > 0: return positive_word
    if value < 0: return negative_word
    return flat_word

def _pressure_axis(k: dict) -> tuple[str, float, float]:
    trx_delta = delta_pct(k.get("trx_pulse", 0), k.get("trx_pulse_prev", 0))
    basket_delta = delta_pct(k.get("avg_trx_pulse", 0), k.get("avg_trx_pulse_prev", 0))
    axis = "volume transaksi" if abs(trx_delta) >= abs(basket_delta) else "nilai transaksi rata-rata"
    return axis, trx_delta, basket_delta

def _top_entity(df, label_col: str, mode: str = "positive") -> tuple[str, float, float]:
    if mode == "negative":
        return _top_negative(df, label_col)
    return _top_positive(df, label_col)

def _top_division(df_in: pd.DataFrame) -> tuple[str, float, float]:
    if df_in is None or df_in.empty or "Sales Div." not in df_in.columns:
        return "-", 0.0, 0.0
    g = df_in.groupby("Sales Div.")["Total_Revenue"].sum().sort_values(ascending=False)
    if g.empty or g.sum() == 0:
        return "-", 0.0, 0.0
    name = str(g.index[0])
    value = float(g.iloc[0])
    share = value / float(g.sum()) * 100
    return name, value, share

def _top_pareto_entity(df_p: pd.DataFrame) -> tuple[str, float, float]:
    if df_p is None or df_p.empty:
        return "-", 0.0, 0.0
    row = df_p.iloc[0]
    return str(row.get("entity", "-")), _as_float(row.get("revenue", 0)), _as_float(row.get("cumulative_pct", 0))


def _pct_change_list(values: list[float]) -> list[float]:
    """Return percentage changes between consecutive values."""
    out = []
    for i in range(1, len(values)):
        prev = _as_float(values[i - 1])
        cur = _as_float(values[i])
        out.append(delta_pct(cur, prev) if prev else 0.0)
    return out


def _direction_consistency(changes: list[float], threshold: float = 1.0) -> tuple[int, int, int]:
    """Return count of positive, negative, and flat movements."""
    pos = sum(1 for x in changes if x > threshold)
    neg = sum(1 for x in changes if x < -threshold)
    flat = len(changes) - pos - neg
    return pos, neg, flat


def _slope_pct(values: list[float]) -> float:
    """Simple normalized slope as percent of mean value."""
    clean = [float(v) for v in values if pd.notna(v)]
    if len(clean) < 2:
        return 0.0
    x = np.arange(len(clean), dtype=float)
    slope = float(np.polyfit(x, np.array(clean, dtype=float), 1)[0])
    base = abs(float(np.mean(clean))) or 1.0
    return slope / base * 100


def _volatility_pct(values: list[float]) -> float:
    """Coefficient of variation to detect unstable arah tren."""
    clean = [abs(float(v)) for v in values if pd.notna(v)]
    if len(clean) < 2:
        return 0.0
    mean = float(np.mean(clean)) or 1.0
    return float(np.std(clean)) / mean * 100


def _pattern_label(changes: list[float], slope_pct_value: float, volatility_pct_value: float) -> str:
    recent = [float(x) for x in changes[-3:]]
    pos, neg, flat = _direction_consistency(recent, threshold=1.0)
    if len(recent) >= 3 and neg == 3:
        return "koreksi beruntun"
    if len(recent) >= 3 and pos == 3:
        return "ekspansi beruntun"
    if len(recent) >= 2 and recent[-2] < -1 and recent[-1] > 1:
        return "rebound awal"
    if len(recent) >= 2 and recent[-2] > 1 and recent[-1] < -1:
        return "pembalikan negatif"
    if volatility_pct_value >= 22:
        return "fluktuatif"
    if slope_pct_value > 2:
        return "uptrend bertahap"
    if slope_pct_value < -2:
        return "downtrend bertahap"
    return "sideways terkendali"


def _trend_pattern_analysis(k: dict) -> dict:
    """
    Data-driven arah tren engine.
    It detects main indicators from monthly and weekly time series:
    - consecutive expansion/correction
    - reversal/rebound
    - 3-week direction
    - volatility
    - divergence between monthly and operational pulse
    """
    monthly_df = k.get("ts_monthly", pd.DataFrame()).copy()
    weekly_df = k.get("ts_weekly", pd.DataFrame()).copy()

    if monthly_df is not None and not monthly_df.empty:
        m_values = monthly_df["Total_Revenue"].astype(float).tail(6).tolist()
        m_labels = monthly_df["Label"].astype(str).tail(6).tolist()
        if "Growth" in monthly_df.columns:
            m_changes = [float(x) for x in monthly_df["Growth"].dropna().tail(5).tolist()]
        else:
            m_changes = _pct_change_list(m_values)
    else:
        m_values, m_labels, m_changes = [], [], []

    if weekly_df is not None and not weekly_df.empty:
        w_values = weekly_df["Total_Revenue"].astype(float).tail(8).tolist()
        w_labels = weekly_df["Label"].astype(str).tail(8).tolist()
        w_changes = _pct_change_list(w_values)
        ma3 = pd.Series(w_values).rolling(3, min_periods=1).mean().tolist()
        ma3_delta = delta_pct(ma3[-1], ma3[-2]) if len(ma3) >= 2 and ma3[-2] else 0.0
    else:
        w_values, w_labels, w_changes, ma3, ma3_delta = [], [], [], [], 0.0

    m_slope = _slope_pct(m_values)
    w_slope = _slope_pct(w_values)
    m_vol = _volatility_pct(m_values)
    w_vol = _volatility_pct(w_values)
    monthly_pattern = _pattern_label(m_changes, m_slope, m_vol)
    weekly_pattern = _pattern_label(w_changes, w_slope, w_vol)

    pct_m = _as_float(k.get("pct_m"))
    pct_w = _as_float(k.get("pct_w"))
    pct_dod = _as_float(k.get("pct_dod", pct_w))
    pressure_axis, trx_delta, basket_delta = _pressure_axis(k)

    if pct_m < 0 and pct_w < 0:
        hidden_signal = "tekanan berlapis antara tren bulanan dan ritme operasional berjalan"
        risk_level = "tinggi"
    elif pct_m < 0 and pct_w > 0:
        hidden_signal = "indikasi recovery pendek di tengah koreksi bulanan"
        risk_level = "menengah"
    elif pct_m > 0 and pct_w < 0:
        hidden_signal = "perlambatan awal setelah momentum bulanan positif"
        risk_level = "menengah"
    elif pct_m > 0 and pct_w > 0:
        hidden_signal = "momentum penguatan yang masih terkonfirmasi dari tren pendek"
        risk_level = "rendah"
    else:
        hidden_signal = "fase stabil yang perlu dipantau dari perubahan volume dan basket size"
        risk_level = "moderat"

    if w_vol >= 25:
        hidden_signal += ", dengan volatilitas mingguan yang relatif tinggi"
        risk_level = "tinggi" if risk_level != "rendah" else "menengah"

    latest_month_label = m_labels[-1] if m_labels else k.get("label_bini", "periode berjalan")
    prev_month_label = m_labels[-2] if len(m_labels) >= 2 else k.get("label_blalu", "periode pembanding")
    latest_week_label = w_labels[-1].replace("\n", " ") if w_labels else k.get("pulse_period_current", "periode berjalan")
    prev_week_label = w_labels[-2].replace("\n", " ") if len(w_labels) >= 2 else k.get("pulse_period_previous", "periode pembanding")

    monthly_signal = (
        f"Pola bulanan menunjukkan {monthly_pattern}: {latest_month_label} berada di {fmt_rp_smart(k.get('rev_bini', 0))} "
        f"dibanding {prev_month_label} dengan perubahan {fmt_pct(pct_m)}. Slope enam periode terakhir sekitar {m_slope:+.1f}% "
        f"dari rata-rata periode, sehingga arah bulanan perlu dibaca sebagai sinyal {monthly_pattern}, bukan hanya angka bulanan terakhir."
    )
    weekly_signal = (
        f"Pola mingguan menunjukkan {weekly_pattern}: {latest_week_label} berada di {fmt_rp_smart(k.get('rev_pulse', 0))} "
        f"dibanding {prev_week_label} dengan perubahan {fmt_pct(pct_w)}. Tren 3 minggu bergerak {fmt_pct(ma3_delta)}, "
        f"menunjukkan arah {'membaik' if ma3_delta > 0 else 'melemah' if ma3_delta < 0 else 'relatif stabil'} berdasarkan perubahan revenue mingguan."
    )
    hidden_readout = (
        f"Indikasi utama utama adalah {hidden_signal}. Tekanan paling kuat datang dari {pressure_axis}, "
        f"karena volume berubah {fmt_pct(trx_delta)} sementara basket size berubah {fmt_pct(basket_delta)}. "
        f"Level risiko tren saat ini terbaca {risk_level}, sehingga keputusan recovery perlu menggabungkan pola bulanan, ritme mingguan, dan kualitas transaksi."
    )
    action = (
        f"Tindak lanjut pola tren perlu memprioritaskan area yang bisa mengubah arah {weekly_pattern} lebih cepat: customer repeat order, stok siap jual, "
        f"dan pipeline dengan closing paling dekat. Jika tren 3 minggu belum membaik, intervensi jangan hanya mengejar nominal invoice, tetapi juga memperbaiki {pressure_axis}."
    )

    return {
        "monthly_pattern": monthly_pattern,
        "weekly_pattern": weekly_pattern,
        "hidden_signal": hidden_signal,
        "risk_level": risk_level,
        "monthly_slope_pct": m_slope,
        "weekly_slope_pct": w_slope,
        "monthly_volatility_pct": m_vol,
        "weekly_volatility_pct": w_vol,
        "ma3_delta_pct": ma3_delta,
        "pressure_axis": pressure_axis,
        "trend_pattern_subtitle": f"Pola tersembunyi: {hidden_signal} dengan risiko tren {risk_level}.",
        "trend_pattern_readout": hidden_readout,
        "trend_pattern_action": action,
        "monthly_pattern_readout": monthly_signal,
        "weekly_pattern_readout": weekly_signal,
    }

def _sales_category_summary(k: dict) -> tuple[str, float, float, str, float, float]:
    cat_df = k.get("sales_category_pulse", pd.DataFrame())
    cat_down, cat_down_d, cat_down_p = _top_negative(cat_df, "Sales_Category")
    cat_up, cat_up_d, cat_up_p = _top_positive(cat_df, "Sales_Category")
    return cat_down, cat_down_d, cat_down_p, cat_up, cat_up_d, cat_up_p

def _status_focus(k: dict) -> str:
    pct_m = _as_float(k.get("pct_m"))
    if pct_m < THRESHOLD_TURUN:
        return "pemulihan revenue dan pengamanan volume transaksi"
    if pct_m > THRESHOLD_NAIK:
        return "penguncian momentum dan replikasi area yang tumbuh"
    return "stabilisasi revenue dan penguatan eksekusi harian"

def _board_directives_dynamic(k: dict, ctx: dict) -> list:
    # All directive details depend on current metric values, top entities, and current condition.
    gap = k.get("target_gap", np.nan)
    focus = _status_focus(k)
    return [
        {
            "directive": f"Recover {k['label_bini']} Revenue Base",
            "detail": (
                f"Revenue {k['label_bini']} berada di {fmt_rp_smart(k['rev_bini'])} dengan gap target {fmt_rp_smart(gap)}. "
                f"Prioritas komersial perlu diarahkan pada {focus}, terutama melalui repeat order dan pipeline yang paling dekat menjadi invoice, sambil memantau pola tren pendek agar koreksi tidak berlanjut ke periode berikutnya."
            ),
            "business_outcome": f"DoD {fmt_pct(_as_float(k.get('pct_dod', k.get('pct_w', 0))))}",
        },
        {
            "directive": f"Stabilize {ctx['neg_br']} and Replicate {ctx['pos_br']}",
            "detail": (
                f"{ctx['neg_br']} menjadi tekanan DoD terbesar sebesar {fmt_rp_smart(ctx['neg_br_d'])}, sementara {ctx['pos_br']} memberi penguatan {fmt_rp_smart(ctx['pos_br_d'])}. "
                f"Review stok, customer aktif, dan aktivitas lapangan perlu dibedakan agar area terkoreksi segera mendapat intervensi yang paling relevan."
            ),
            "business_outcome": f"Branch gap {fmt_rp_smart(ctx['neg_br_d'])}",
        },
        {
            "directive": f"Focus Field Recovery on {ctx['neg_sal']}",
            "detail": (
                f"{ctx['neg_sal']} ({ctx['neg_sal_cat']}) mencatat koreksi {fmt_rp_smart(ctx['neg_sal_d'])}, sedangkan {ctx['pos_sal']} ({ctx['pos_sal_cat']}) menguat {fmt_rp_smart(ctx['pos_sal_d'])}. "
                f"Intervensi lapangan perlu memprioritaskan pipeline aktif, hambatan pricing atau stok, dan replikasi pola follow-up dari performer yang masih tumbuh."
            ),
            "business_outcome": f"Sales pulse {fmt_pct(_as_float(k['pct_pulse']))}",
        },
        {
            "directive": "Close Target Gap with Daily Invoice Actions",
            "detail": (
                f"Gap aktual terhadap target bulan berjalan berada di {fmt_rp_smart(gap)}. "
                f"Monitoring harian perlu diarahkan pada pipeline yang paling dekat menjadi invoice, hambatan stok atau pricing, dan customer aktif bernilai besar."
            ),
            "business_outcome": f"Target gap {fmt_rp_smart(gap)}",
        },
        {
            "directive": f"Secure {ctx['top_branch_pareto']} and {ctx['top_sku_pareto']}",
            "detail": (
                f"Sekitar 80% revenue terkonsentrasi pada {k['n80_br']} cabang dan {k['n80_sk']} SKU, dengan kontribusi utama dari {ctx['top_branch_pareto']} dan {ctx['top_sku_pareto']}. "
                f"Prioritas stok, program penjualan, dan pengamanan customer perlu difokuskan pada kontributor utama sambil menumbuhkan contributor lapis kedua."
            ),
            "business_outcome": f"Pareto {k['n80_br']} branch / {k['n80_sk']} SKU",
        },
    ]

def fallback_insight_pack(k: dict) -> dict:
    """
    Fully dynamic narrative pack.
    Every insight field includes current metrics, top entities, movement direction, or business condition.
    No field is a fixed paragraph that would remain identical across future reports.
    """
    condition = k["kondisi"]
    pct_m = _as_float(k.get("pct_m"))
    pct_w = _as_float(k.get("pct_w"))
    pct_dod = _as_float(k.get("pct_dod", pct_w))
    pulse_label = k.get("pulse_label", "QoQ")
    pressure_axis, trx_delta, basket_delta = _pressure_axis(k)
    gap = k.get("target_gap", np.nan)
    gap_word = "shortfall" if pd.notna(gap) and gap < 0 else "buffer"
    trend_word = _direction_word(pct_dod, "menguat", "terkoreksi", "stabil")
    pulse_word = _direction_word(pct_w, "menguat", "melemah", "stabil")
    trx_word = _direction_word(trx_delta, "naik", "turun", "stabil")
    basket_word = _direction_word(basket_delta, "naik", "turun", "stabil")
    focus = _status_focus(k)
    trend_pattern = _trend_pattern_analysis(k)

    neg_br, neg_br_d, neg_br_p = _top_negative(k.get("pulse_branch"), "Branch")
    pos_br, pos_br_d, pos_br_p = _top_positive(k.get("pulse_branch"), "Branch")
    neg_sal, neg_sal_d, neg_sal_p = _top_negative(k.get("pulse_sales"), "Salesman")
    pos_sal, pos_sal_d, pos_sal_p = _top_positive(k.get("pulse_sales"), "Salesman")
    neg_sal_cat = sales_category_from_code(neg_sal)
    pos_sal_cat = sales_category_from_code(pos_sal)
    neg_sal_label = sales_entity_label(neg_sal)
    pos_sal_label = sales_entity_label(pos_sal)
    neg_sal_focus = sales_intervention_focus(neg_sal)
    pos_sal_focus = sales_intervention_focus(pos_sal)
    cat_down, cat_down_d, cat_down_p, cat_up, cat_up_d, cat_up_p = _sales_category_summary(k)

    sku_df = k.get("pulse_sku", pd.DataFrame())
    sku_lose = sku_df[sku_df["Delta"] < 0].sort_values("Delta", ascending=True) if sku_df is not None and not sku_df.empty and "Delta" in sku_df.columns else pd.DataFrame()
    sku_gain = sku_df[sku_df["Delta"] > 0].sort_values("Delta", ascending=False) if sku_df is not None and not sku_df.empty and "Delta" in sku_df.columns else pd.DataFrame()
    neg_sku, neg_sku_d, neg_sku_p = _top_negative(sku_lose, "sku") if not sku_lose.empty else ("-", 0.0, 0.0)
    pos_sku, pos_sku_d, pos_sku_p = _top_positive(sku_gain, "sku") if not sku_gain.empty else ("-", 0.0, 0.0)

    top_eff = k["eff_bini"].iloc[0] if k.get("eff_bini") is not None and not k["eff_bini"].empty else None
    top_eff_name = str(top_eff["Salesman"]) if top_eff is not None else "-"
    top_eff_score = float(top_eff["Score"]) if top_eff is not None else 0.0
    top_eff_cat = sales_category_from_code(top_eff_name)
    top_eff_subject = sales_playbook_subject(top_eff_name)
    avg_eff_score = float(k["eff_bini"]["Score"].mean()) if k.get("eff_bini") is not None and not k["eff_bini"].empty else 0.0

    cur_div, cur_div_rev, cur_div_share = _top_division(k.get("df_bini"))
    prev_div, prev_div_rev, prev_div_share = _top_division(k.get("df_blalu"))
    div_shift = cur_div if cur_div == prev_div else f"{prev_div} ke {cur_div}"

    top_branch_pareto, top_branch_rev, top_branch_cum = _top_pareto_entity(k.get("pareto_branch"))
    top_sku_pareto, top_sku_rev, top_sku_cum = _top_pareto_entity(k.get("pareto_sku"))

    ctx = {
        "neg_br": neg_br, "neg_br_d": neg_br_d, "neg_br_p": neg_br_p,
        "pos_br": pos_br, "pos_br_d": pos_br_d, "pos_br_p": pos_br_p,
        "neg_sal": neg_sal, "neg_sal_d": neg_sal_d, "neg_sal_p": neg_sal_p, "neg_sal_cat": neg_sal_cat,
        "pos_sal": pos_sal, "pos_sal_d": pos_sal_d, "pos_sal_p": pos_sal_p, "pos_sal_cat": pos_sal_cat,
        "top_branch_pareto": top_branch_pareto, "top_sku_pareto": top_sku_pareto,
    }

    return {
        "board_subtitle": (
            f"Per {k['date_max']:%d %b %Y}, kondisi {condition.lower()} dengan DoD {fmt_pct(pct_dod)} dan pola {trend_pattern['monthly_pattern']} menempatkan fokus pada {focus}."
        ),
        "board_summary": (
            f"Revenue harian mencapai {fmt_rp_smart(k.get('rev_dod_current', 0))}, {trend_word} {fmt_pct(pct_dod)} dibanding previous data day sebesar {fmt_rp_smart(k.get('rev_dod_previous', 0))}. "
            f"Pulse {pulse_label} berada di {fmt_rp_smart(k['rev_pulse'])} atau {fmt_pct(pct_w)}, dengan tekanan terbesar saat ini berada pada {pressure_axis}. "
            f"Pola tersembunyi yang terbaca adalah {trend_pattern['hidden_signal']}, sehingga risiko tren berada pada level {trend_pattern['risk_level']}."
        ),
        "board_decision": (
            f"Keputusan direksi perlu memprioritaskan {focus}, karena gap target bulan berjalan berada di {fmt_rp_smart(gap)}. "
            f"Area tindakan utama adalah {neg_br} sebagai cabang terkoreksi, {neg_sal_label} sebagai watchlist eksekusi, dan {neg_sku} sebagai SKU dengan koreksi terbesar. "
            f"Keputusan perlu mengikuti tren 3 minggu yang bergerak {fmt_pct(trend_pattern['ma3_delta_pct'])} agar intervensi tidak terlambat menunggu laporan bulanan berikutnya."
        ),
        "monthly_subtitle": (
            f"Momentum harian {trend_word} {fmt_pct(pct_dod)} dengan pola {trend_pattern['monthly_pattern']} dan {gap_word} target bulanan {fmt_rp_smart(gap)}."
        ),
        "monthly_readout": (
            f"Revenue harian tercatat {fmt_rp_smart(k.get('rev_dod_current', 0))}, sementara previous data day berada di {fmt_rp_smart(k.get('rev_dod_previous', 0))}. "
            f"Dibanding target internal {fmt_rp_smart(k['target_rev_mo'])}, posisi saat ini menghasilkan {gap_word} {fmt_rp_smart(gap)}, sehingga arah {condition.lower()} perlu dibaca bersama kontribusi {neg_br} dan pergerakan SKU {neg_sku}. "
            f"Analisis pola menunjukkan slope enam periode terakhir {trend_pattern['monthly_slope_pct']:+.1f}% dengan volatilitas {trend_pattern['monthly_volatility_pct']:.1f}%."
        ),
        "monthly_action": (
            f"Intervensi bulan berjalan perlu diarahkan pada pipeline yang paling cepat menjadi invoice, terutama di {neg_br} dengan koreksi {fmt_rp_smart(neg_br_d)} dan SKU {neg_sku} yang turun {fmt_rp_smart(neg_sku_d)}. "
            f"Jika gap {fmt_rp_smart(gap)} belum mengecil, prioritas harian sebaiknya dipindahkan ke repeat order, customer aktif bernilai besar, dan pengamanan stok untuk {pos_sku}."
        ),
        "weekly_subtitle": (
            f"Pulse {pulse_label} periode {k.get('pulse_period_current','-')} {pulse_word} {fmt_pct(pct_w)} dengan pola {trend_pattern['weekly_pattern']} dan volume {trx_word} {fmt_pct(trx_delta)}."
        ),
        "weekly_readout": (
            f"Revenue pulse berada di {fmt_rp_smart(k['rev_pulse'])} dibanding periode pembanding {fmt_rp_smart(k['rev_pulse_prev'])}, sehingga perubahan {fmt_pct(pct_w)} menunjukkan ritme operasional yang {pulse_word}. "
            f"Transaksi {trx_word} {fmt_pct(trx_delta)} menjadi {k.get('trx_pulse', 0):,.0f} trx, sementara basket size {basket_word} {fmt_pct(basket_delta)} menjadi {fmt_rp_smart(k.get('avg_trx_pulse', 0))}. "
            f"Tren 3 minggu bergerak {fmt_pct(trend_pattern['ma3_delta_pct'])}, sehingga arah revenue mingguan terbaca sebagai {trend_pattern['weekly_pattern']}."
        ),
        "weekly_action": (
            f"Ritme harian perlu diarahkan pada {pressure_axis}, khususnya melalui follow-up customer aktif di {neg_br} dan {neg_sal_focus}. "
            f"Penguatan pada {pos_sal_label} sebesar {fmt_rp_smart(pos_sal_d)} dapat dijadikan pembanding pola kunjungan, prioritas customer, dan kesiapan stok minggu berjalan. "
            f"Jika pola {trend_pattern['weekly_pattern']} belum membaik, prioritas harian perlu diarahkan ke faktor yang paling menekan yaitu {pressure_axis}."
        ),
        "branch_subtitle": (
            f"Kontras {neg_br} {fmt_pct(neg_br_p)} dan {pos_br} {fmt_pct(pos_br_p)} menunjukkan recovery belum merata antar area."
        ),
        "branch_readout": (
            f"Cabang dengan koreksi DoD terbesar adalah {neg_br} sebesar {fmt_rp_smart(neg_br_d)} ({fmt_pct(neg_br_p)}), sedangkan penguatan terbaik berasal dari {pos_br} sebesar {fmt_rp_smart(pos_br_d)} ({fmt_pct(pos_br_p)}). "
            f"Pola ini menunjukkan perbedaan kualitas eksekusi area, bukan sekadar perubahan total demand perusahaan."
        ),
        "branch_action": (
            f"{neg_br} perlu menjadi prioritas validasi stok, daftar customer aktif, dan hambatan closing karena kontribusinya menekan revenue sebesar {fmt_rp_smart(neg_br_d)}. "
            f"Pendekatan {pos_br} yang masih tumbuh {fmt_pct(pos_br_p)} perlu dibaca sebagai referensi aktivitas, mix produk, dan pola follow-up yang dapat direplikasi secara selektif."
        ),
        "sales_delta_subtitle": (
            f"Pergerakan {neg_sal} dan {pos_sal} menunjukkan kualitas konversi pipeline berbeda antar kanal lapangan."
        ),
        "sales_delta_readout": (
            f"Koreksi running terbesar terbaca pada {neg_sal_label} sebesar {fmt_rp_smart(neg_sal_d)} ({fmt_pct(neg_sal_p)}), sementara penguatan terbesar terbaca pada {pos_sal_label} sebesar {fmt_rp_smart(pos_sal_d)} ({fmt_pct(pos_sal_p)}). "
            f"Secara kanal, tekanan terbesar terlihat pada {cat_down} sebesar {fmt_rp_smart(cat_down_d)}, sedangkan penahan koreksi berasal dari {cat_up} sebesar {fmt_rp_smart(cat_up_d)}."
        ),
        "sales_delta_action": (
            f"Branch Manager dan Supervisor perlu mengarahkan intervensi pada {neg_sal_focus}, dengan fokus pada peluang closing terdekat, hambatan stok atau pricing, dan follow-up customer prioritas. "
            f"Pola penguatan pada {pos_sal_focus} yang membaik {fmt_pct(pos_sal_p)} perlu diterjemahkan menjadi agenda kunjungan dan daftar customer yang bisa direplikasi minggu ini."
        ),
        "sales_eff_subtitle": (
            f"Benchmark efisiensi saat ini dipegang {top_eff_name} ({top_eff_cat}) dengan skor {top_eff_score:.1f} dibanding rata-rata {avg_eff_score:.1f}."
        ),
        "sales_eff_readout": (
            f"{top_eff_name} ({top_eff_cat}) menjadi benchmark dengan skor {top_eff_score:.1f}, di atas rata-rata top list {avg_eff_score:.1f}. "
            f"Skor ini menunjukkan kombinasi kontribusi revenue dan nilai transaksi rata-rata, sehingga relevan untuk membaca kualitas eksekusi, bukan hanya besaran invoice."
        ),
        "sales_eff_action": (
            f"{top_eff_subject.capitalize()} perlu diterjemahkan menjadi pola kunjungan, tipe customer prioritas, dan urutan follow-up yang bisa diadopsi oleh area atau personel dengan koreksi terbesar seperti {neg_sal_label}. "
            f"Pendampingan lapangan sebaiknya diarahkan pada gap antara skor benchmark {top_eff_score:.1f} dan rata-rata {avg_eff_score:.1f}, agar transfer praktik berjalan lebih terukur."
        ),
        "portfolio_subtitle": (
            f"Bauran divisi {k['label_bini']} dipimpin {cur_div} dengan share {cur_div_share:.1f}% dan arah dominan {div_shift}."
        ),
        "portfolio_readout": (
            f"Kontributor divisi terbesar pada {k['label_bini']} adalah {cur_div} senilai {fmt_rp_smart(cur_div_rev)} atau {cur_div_share:.1f}% dari revenue bulan berjalan. "
            f"Pada periode sebelumnya kontributor utama adalah {prev_div} dengan share {prev_div_share:.1f}%, sehingga pergeseran {div_shift} perlu dibaca terhadap kualitas margin, ketersediaan stok, dan risiko slow moving."
        ),
        "portfolio_action": (
            f"Manajemen perlu memastikan kontribusi {cur_div} tidak hanya mengejar nominal {fmt_rp_smart(cur_div_rev)}, tetapi juga menjaga margin, stok siap jual, dan kualitas pembayaran. "
            f"Jika share {cur_div_share:.1f}% terlalu dominan, sales plan perlu menumbuhkan divisi lapis kedua agar risiko portofolio tidak terkunci pada satu sumber revenue."
        ),
        "concentration_subtitle": (
            f"Revenue terkonsentrasi pada {k['n80_br']} cabang dan {k['n80_sk']} SKU, dengan jangkar utama {top_branch_pareto} dan {top_sku_pareto}."
        ),
        "concentration_readout": (
            f"Sekitar 80% revenue cabang dibentuk oleh {k['n80_br']} cabang, sementara 80% revenue SKU dibentuk oleh {k['n80_sk']} SKU utama. "
            f"Kontributor terbesar adalah {top_branch_pareto} senilai {fmt_rp_smart(top_branch_rev)} dan {top_sku_pareto} senilai {fmt_rp_smart(top_sku_rev)}, sehingga gangguan pada entitas utama ini dapat langsung memengaruhi capaian bulanan."
        ),
        "concentration_action": (
            f"Prioritas stok dan program penjualan perlu mengamankan {top_branch_pareto} serta SKU {top_sku_pareto}, karena keduanya menjadi jangkar konsentrasi revenue periode ini. "
            f"Di saat yang sama, cabang di luar top {k['n80_br']} dan SKU di luar top {k['n80_sk']} perlu didorong agar risiko ketergantungan tidak semakin sempit."
        ),
        "product_subtitle": (
            f"SKU {neg_sku} turun {fmt_rp_smart(neg_sku_d)}, sementara {pos_sku} menjadi best mover {fmt_rp_smart(pos_sku_d)} pada pergerakan DoD."
        ),
        "product_readout": (
            f"SKU dengan koreksi terbesar adalah {neg_sku} sebesar {fmt_rp_smart(neg_sku_d)} ({fmt_pct(neg_sku_p)}), sedangkan penguatan terbesar berasal dari {pos_sku} sebesar {fmt_rp_smart(pos_sku_d)} ({fmt_pct(pos_sku_p)}). "
            f"Perbedaan arah ini perlu dipisahkan antara demand yang melemah, shifting ke substitusi, issue ketersediaan stok, atau perubahan prioritas customer."
        ),
        "product_action": (
            f"SKU {neg_sku} perlu masuk daftar intervensi stok, bundling, dan review forecast karena koreksinya mencapai {fmt_rp_smart(neg_sku_d)}. "
            f"Untuk SKU {pos_sku}, pastikan availability dan titik pesan ulang tetap aman agar penguatan {fmt_pct(pos_sku_p)} tidak terputus oleh stock-out."
        ),
        "directive_recap": (
            f"Anomali utama periode ini adalah revenue harian {trend_word} {fmt_pct(pct_dod)} dan revenue periode {pulse_label} {pulse_word} {fmt_pct(pct_w)}. "
            f"Tekanan paling terlihat pada {neg_br}, {neg_sal_label}, serta SKU {neg_sku}. "
            f"Indikasi utama menunjukkan {trend_pattern['hidden_signal']}; agenda tindakan perlu menghubungkan recovery {fmt_rp_smart(gap)}, pengamanan {top_branch_pareto}, dan percepatan closing invoice agar keputusan komersial tidak hanya mengejar nominal revenue."
        ),
        "trend_pattern_subtitle": trend_pattern["trend_pattern_subtitle"],
        "trend_pattern_readout": trend_pattern["trend_pattern_readout"],
        "trend_pattern_action": trend_pattern["trend_pattern_action"],
        "monthly_pattern_readout": trend_pattern["monthly_pattern_readout"],
        "weekly_pattern_readout": trend_pattern["weekly_pattern_readout"],
        "board_directives": _board_directives_dynamic(k, ctx),
        "ai_source_note": f"Narasi otomatis berbasis data aktual per {k['date_max']:%d %b %Y}; seluruh insight memakai metrik, pola tren, dan pergerakan periode berjalan.",
    }

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def _cache_path(k: dict) -> Path:
    date_token = pd.Timestamp(k["date_max"]).strftime("%Y-%m-%d")
    return Path(OUTPUT_DIR) / f"ai_insight_cache_{AI_CACHE_VERSION}_{date_token}.json"

def _load_cache(k: dict) -> dict | None:
    if not AI_CACHE_ENABLED: return None
    path = _cache_path(k)
    if not path.exists(): return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict): return None
        if data.get("cache_version") != AI_CACHE_VERSION:
            print(f"[AI] Cache diabaikan - versi berbeda ({data.get('cache_version')})")
            return None
        cached = data.get("insights", {})
        if not isinstance(cached, dict): return None
        text_fields = [f for sec in AI_SECTIONS for f in sec["fields"]]
        missing = [f for f in text_fields if not str(cached.get(f,"")).strip()]
        if missing:
            print(f"[AI] Cache tidak lengkap - missing: {missing[:5]}")
            return None
        if not isinstance(cached.get("board_directives"), list) or len(cached["board_directives"]) < 5:
            print("[AI] Cache tidak memiliki board_directives lengkap")
            return None
        # Sanity check: no banned tech terms in cached text
        for f in text_fields:
            if _contains_banned_tech(cached.get(f,"")):
                print(f"[AI] Cache ditolak - field {f} mengandung istilah teknis")
                return None
        cached["ai_source_note"] = str(cached.get("ai_source_note","")) + " | loaded from cache"
        print(f"[AI] Cache berhasil dimuat: {path.name}")
        return cached
    except Exception as exc:
        print(f"[AI] Cache gagal dibaca: {exc}")
        return None

def _save_cache(k: dict, pack: dict) -> None:
    if not AI_CACHE_ENABLED: return
    try:
        path = _cache_path(k)
        data = {
            "cache_version": AI_CACHE_VERSION,
            "created_at":    datetime.now().isoformat(timespec="seconds"),
            "report_date":   pd.Timestamp(k["date_max"]).strftime("%Y-%m-%d"),
            "insights": {key: val for key, val in pack.items() if not str(key).startswith("_")},
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[AI] Cache disimpan: {path.name}")
    except Exception as exc:
        print(f"[AI] Cache gagal disimpan: {exc}")

# ---------------------------------------------------------------------------
# Main sectional AI generation
# ---------------------------------------------------------------------------
def generate_ai_insight_pack(k: dict) -> dict:
    """
    Generate AI insights section by section.
    Each section requests only 2-5 fields, making free models far more reliable.
    Per-section retry: if model A fails a section, model B is tried.
    If AI_ALLOW_TEMPLATE_FALLBACK=False and a section fails all models,
    RuntimeError is raised naming the failing section.
    """
    if not AI_INSIGHT_ENABLED:
        if not AI_ALLOW_TEMPLATE_FALLBACK:
            raise RuntimeError("AI_INSIGHT_ENABLED=False dan AI_ALLOW_TEMPLATE_FALLBACK=False. Aktifkan salah satu.")
        print("[OK] Menggunakan narasi dinamis berbasis data aktual.")
        return fallback_insight_pack(k)

    cached = _load_cache(k)
    if cached:
        return cached

    api_key = os.getenv(OPENROUTER_API_KEY_ENV, "").strip()
    if not api_key:
        if not AI_ALLOW_TEMPLATE_FALLBACK:
            raise RuntimeError(f"{OPENROUTER_API_KEY_ENV} tidak ditemukan dan AI_ALLOW_TEMPLATE_FALLBACK=False.")
        print(f"[AI] {OPENROUTER_API_KEY_ENV} tidak ada. Menggunakan narasi dinamis berbasis data aktual.")
        return fallback_insight_pack(k)

    models      = _resolve_models()
    full_payload= _build_full_payload(k)
    fallback    = fallback_insight_pack(k)
    pack        = {}                          # accumulate section results here
    section_errors: List[str] = []
    started     = time.time()

    print(f"\n[AI] Sectional generation aktif. {len(AI_SECTIONS)} sections, models: {', '.join(models)}")

    for section in AI_SECTIONS:
        sec_name    = section["name"]
        fields      = section["fields"]
        inc_dir     = section["include_directives"]
        elapsed     = time.time() - started
        if elapsed >= AI_MAX_TOTAL_SECONDS:
            msg = f"Time budget habis ({elapsed:.0f}s) sebelum section '{sec_name}' selesai."
            if not AI_ALLOW_TEMPLATE_FALLBACK:
                raise RuntimeError(msg + " Naikkan AI_MAX_TOTAL_SECONDS atau gunakan model lebih cepat.")
            print(f"[AI] {msg} Menggunakan narasi dinamis berbasis data aktual untuk section ini.")
            for f in fields: pack.setdefault(f, fallback.get(f,""))
            if inc_dir: pack.setdefault("board_directives", fallback.get("board_directives",[]))
            continue

        sec_ok = False
        for model in models:
            try:
                print(f"[AI] [{sec_name}] Mencoba model: {model}")
                raw = _call_model_for_section(api_key, model, section, full_payload)
                # Validate each field
                field_problems = []
                for f in fields:
                    ok, result = _validate_field(f, raw.get(f,""))
                    if ok:
                        pack[f] = result
                    else:
                        field_problems.append(f"{f}: {result}")
                # Validate directives
                dir_problem = None
                if inc_dir:
                    dir_ok, directives, dir_reason = _validate_directives(raw.get("board_directives",[]))
                    if dir_ok:
                        pack["board_directives"] = directives
                    else:
                        dir_problem = f"board_directives: {dir_reason}"
                if not field_problems and not dir_problem:
                    print(f"[AI] [{sec_name}] OK dengan model {model}")
                    sec_ok = True
                    break
                else:
                    issues = field_problems + ([dir_problem] if dir_problem else [])
                    print(f"[AI] [{sec_name}] Model {model} - validasi gagal: {'; '.join(issues[:5])}")
            except RuntimeError as exc:
                msg = str(exc)
                print(f"[AI] [{sec_name}] Model {model} gagal: {msg[:300]}")
                if _is_rate_limit(msg):
                    print("[AI] Rate limit tercapai. Menghentikan percobaan model berikutnya.")
                    break
                continue

        if not sec_ok:
            err_msg = f"Section '{sec_name}' gagal pada semua model."
            section_errors.append(err_msg)
            if not AI_ALLOW_TEMPLATE_FALLBACK:
                raise RuntimeError(
                    err_msg + " Solusi: gunakan model lebih kuat via os.environ['OPENROUTER_AI_MODEL'], "
                    "atau set AI_ALLOW_TEMPLATE_FALLBACK=True untuk menggunakan narasi template. "
                    "Fields yang dibutuhkan: " + ", ".join(fields)
                )
            print(f"[AI] {err_msg} Menggunakan narasi dinamis berbasis data aktual untuk section ini.")
            for f in fields:
                pack.setdefault(f, fallback.get(f,""))
            if inc_dir:
                pack.setdefault("board_directives", fallback.get("board_directives",[]))

    # Fill in ai_source_note
    model_used = os.getenv(OPENROUTER_AI_MODEL_ENV,"").strip() or models[0] if models else "unknown"
    pack["ai_source_note"] = (
        f"Narasi dihasilkan secara seksional menggunakan {model_used} via OpenRouter. "
        f"Sections: {len(AI_SECTIONS)}. "
        + (f"Section dengan narasi template: {'; '.join(section_errors)}" if section_errors else "Semua section AI berhasil.")
    )

    _save_cache(k, pack)
    return pack

# =============================================================================
# 7. HTML/CSS CONSTANTS
# =============================================================================

CSS_STYLE = r"""
:root {
  --ink: #0B1220; --navy: #0F172A; --blue: #1D4ED8; --blue2: #2563EB;
  --sky: #38BDF8; --cyan: #0891B2; --teal: #0D9488; --purple: #6D28D9;
  --red: #DC2626; --green: #16A34A; --amber: #D97706; --slate: #475569;
  --muted: #94A3B8; --line: #E2E8F0; --soft: #F8FAFC; --white: #FFFFFF;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: Arial, 'DejaVu Sans', sans-serif; font-size: 9.6pt; color: var(--ink); background: #fff; line-height: 1.35; }
@page { size: A4 portrait; margin: 0; }
.page { width: 210mm; height: 297mm; page-break-after: always; page-break-inside: avoid; overflow: hidden; background: #FFFFFF; position: relative; }
.page-header { position: absolute; left: 0; right: 0; top: 0; height: 14mm; background: var(--navy); color: #fff; display: flex; align-items: center; justify-content: space-between; padding: 0 9mm; border-top: 3px solid var(--blue2); }
.header-left .company { font-size: 7pt; letter-spacing: .12em; text-transform: uppercase; font-weight: 800; color: #E2E8F0; }
.header-left .meta { margin-top: 1.2mm; font-size: 6.3pt; color: #AAB6C8; }
.header-right { display: flex; align-items: center; gap: 7mm; }
.trend-badge { min-width: 25mm; text-align: center; border-radius: 4px; padding: 2.4mm 4mm; font-size: 7pt; line-height: 1.05; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }
.badge-green { background: var(--green); } .badge-amber { background: var(--amber); } .badge-red { background: var(--red); }
.page-count { color: #AAB6C8; font-size: 6.5pt; line-height: 1.2; }
.content { position: absolute; left: 0; right: 0; top: 14mm; bottom: 7mm; padding: 8mm 9mm 6mm; display: block; overflow: hidden; }
.content > * { margin-bottom: 4mm; } .content > *:last-child { margin-bottom: 0; }
.page-footer { position: absolute; left: 0; right: 0; bottom: 0; height: 7mm; border-top: 1px solid var(--line); color: var(--muted); font-size: 6.3pt; display: flex; align-items: center; justify-content: center; }
.kicker { color: var(--blue); text-transform: uppercase; font-size: 7pt; letter-spacing: .10em; font-weight: 800; margin-bottom: 1mm; }
.title { font-size: 18pt; line-height: 1.05; font-weight: 800; color: var(--ink); letter-spacing: -0.02em; }
.subtitle { margin-top: 1.5mm; color: var(--slate); font-size: 9pt; }
.card { background: #fff; border: 1px solid var(--line); border-radius: 12px; }
.pad { padding: 4.5mm; }
.chart-card { padding: 3mm; }
.chart-title { font-size: 7pt; color: var(--slate); text-transform: uppercase; letter-spacing: .09em; font-weight: 800; margin-bottom: 1mm; }
.svg-box { width: 100%; overflow: hidden; }
.svg-box svg { width: 100%; height: 100%; display: block; }
.h-72{height:72mm;} .h-76{height:76mm;} .h-82{height:82mm;} .h-86{height:86mm;} .h-88{height:88mm;} .h-94{height:94mm;} .h-102{height:102mm;} .h-104{height:104mm;} .h-112{height:112mm;} .h-118{height:118mm;} .h-120{height:120mm;} .h-128{height:128mm;} .h-130{height:130mm;} .h-142{height:142mm;} .h-152{height:152mm;}
.kpi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; }
.kpi-card { border: 1px solid var(--line); border-top: 3px solid var(--blue); border-radius: 10px; padding: 3.2mm; height: 28mm; background: #fff; overflow: hidden; }
.kpi-card.red{border-top-color:var(--red);} .kpi-card.green{border-top-color:var(--green);} .kpi-card.teal{border-top-color:var(--teal);} .kpi-card.amber{border-top-color:var(--amber);}
.kpi-label { color: var(--muted); text-transform: uppercase; letter-spacing: .07em; font-size: 6.5pt; font-weight: 800; }
.kpi-value { font-size: 18pt; font-weight: 800; color: var(--ink); margin-top: 1.5mm; line-height: 1; }
.kpi-delta { font-size: 7.2pt; font-weight: 800; margin-top: 1.5mm; }
.up{color:var(--green);} .down{color:var(--red);} .flat{color:var(--amber);}
.insight { border-left: 4px solid var(--blue); background: #EFF6FF; border-radius: 10px; padding: 4mm 4.5mm; font-size: 9pt; color: #263548; }
.insight .label { text-transform: uppercase; letter-spacing: .09em; font-size: 7pt; font-weight: 900; color: var(--ink); margin-bottom: 1.5mm; }
.insight.amber{border-color:var(--amber);background:#FFFBEB;} .insight.teal{border-color:var(--teal);background:#ECFDF5;} .insight.purple{border-color:var(--purple);background:#F5F3FF;} .insight.red{border-color:var(--red);background:#FEF2F2;}
.score-table,.mini-table,.directive-table { width: 100%; border-collapse: collapse; font-size: 8.4pt; }
.score-table th,.mini-table th,.directive-table th { background: var(--navy); color: white; text-align: left; font-size: 6.7pt; text-transform: uppercase; letter-spacing: .06em; padding: 2.5mm 3mm; }
.score-table td,.mini-table td,.directive-table td { border-bottom: 1px solid var(--line); padding: 2.5mm 3mm; vertical-align: top; }
.score-table tr:nth-child(even) td,.mini-table tr:nth-child(even) td,.directive-table tr:nth-child(even) td { background: #F8FAFC; }
.right{text-align:right!important;} .center{text-align:center!important;} .metric{font-weight:700;}
.status-pill { display: inline-block; border-radius: 99px; padding: 1mm 2.5mm; font-size: 6.5pt; font-weight: 800; }
.status-on{background:#DCFCE7;color:var(--green);} .status-off{background:#FEE2E2;color:var(--red);} .status-na{background:#E2E8F0;color:var(--slate);}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:4mm;} .grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:3mm;}
.signal-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:3mm;}
.signal { background: var(--navy); color: white; border-radius: 12px; padding: 3.4mm; height: 32mm; overflow: hidden; }
.signal .label { font-size: 6.6pt; text-transform: uppercase; letter-spacing: .08em; color: #93C5FD; font-weight: 900; margin-bottom: 1.2mm; }
.signal .value { font-size: 13.5pt; line-height: 1.08; font-weight: 800; margin-top: 1mm; letter-spacing: -0.03em; overflow-wrap: break-word; word-break: normal; }
.signal .text { font-size: 6.8pt; line-height: 1.25; color: #CBD5E1; margin-top: 1.5mm; }
.flex-spread{display:flex;justify-content:space-between;gap:4mm;align-items:flex-end;}
.small-note{font-size:7.2pt;color:var(--slate);}
.number-cell{font-size:17pt;font-weight:800;color:var(--blue);text-align:center;width:12mm;}
.glossary{display:grid;grid-template-columns:1fr 1fr;gap:2mm 6mm;font-size:7.4pt;color:var(--slate);}
.cover { background: radial-gradient(circle at 72% 20%, #1E3A8A 0%, #10213F 32%, #08111F 72%); color: white; padding: 20mm 16mm; display: flex; flex-direction: column; justify-content: space-between; }
.cover .brand{letter-spacing:.17em;text-transform:uppercase;color:#AAB6C8;font-size:8pt;font-weight:800;}
.cover .main-title{font-size:34pt;font-weight:800;line-height:.98;margin-top:24mm;letter-spacing:-0.04em;}
.cover .accent{color:#60A5FA;}
.cover .cover-badge{margin-top:9mm;width:95mm;border-radius:999px;background:var(--red);padding:3mm 6mm;font-size:8pt;font-weight:900;text-transform:uppercase;letter-spacing:.08em;}
.cover .headline{margin-top:9mm;max-width:130mm;color:#CBD5E1;font-size:11pt;line-height:1.5;}
.cover-panel{width:100%;border:1px solid rgba(255,255,255,.14);border-radius:18px;background:rgba(255,255,255,.06);padding:7mm;}
.cover-panel .row{border-bottom:1px solid rgba(255,255,255,.12);padding:4mm 0;}
.cover-panel .row:last-child{border-bottom:0;}
.cover-panel .label{color:#93A4BD;font-size:7pt;text-transform:uppercase;letter-spacing:.12em;font-weight:800;}
.cover-panel .value{color:#F8FAFC;font-size:10pt;margin-top:1mm;}
.watermark{position:absolute;right:-15mm;bottom:42mm;font-size:42pt;opacity:.035;transform:rotate(-22deg);font-weight:900;letter-spacing:.10em;}
.story-block { border: 1px solid #D7E3F5; border-left: 4px solid #1D4ED8; border-radius: 12px; background: #EFF6FF; padding: 3.4mm 4mm; color: #0F172A; min-height: 28mm; overflow: hidden; }
.story-block .label { text-transform: uppercase; letter-spacing: .09em; font-size: 7pt; font-weight: 900; color: #1D4ED8; margin-bottom: 1.4mm; }
.story-block p { margin: 0; font-size: 8.35pt; line-height: 1.42; color: #0F172A; }
.story-stack{display:grid;gap:3mm;}
.content-balanced{display:grid;grid-template-columns:1.65fr .85fr;gap:4mm;align-items:stretch;}
.text-chart-split{display:grid;grid-template-columns:1.45fr .75fr;gap:4mm;align-items:stretch;}
.compact-signal-row{display:grid;grid-template-columns:repeat(3,1fr);gap:3mm;}
.compact-signal-row.single-column{grid-template-columns:1fr!important;}
.page2-compact{grid-template-columns:1.55fr .85fr;gap:3mm;}
.page2-compact .story-block{min-height:22mm;padding:2.8mm 3.5mm;}
.page2-compact .story-block p{font-size:7.75pt;line-height:1.33;}
.page2-signals{grid-template-columns:1fr!important;gap:2.2mm;}
.page2-signals .signal{padding:3mm;min-height:20mm;}
.page2-signals .signal .value{font-size:14pt;}
.compact-story-stack{gap:2.2mm;}
.page1-compact > *{margin-bottom:2.2mm;} .page1-compact > *:last-child{margin-bottom:0;}
.page1-compact .kpi-grid{grid-template-columns:repeat(4,1fr);gap:2mm;}
.page1-compact .kpi-card{height:22mm;padding:2.2mm 2.4mm;border-radius:9px;}
.page1-compact .kpi-label{font-size:5.9pt;line-height:1.15;}
.page1-compact .kpi-value{font-size:12.8pt;margin-top:1.1mm;white-space:nowrap;}
.page1-compact .kpi-delta{font-size:6.4pt;margin-top:1.1mm;}
.page1-compact .score-table{font-size:7.05pt;}
.page1-compact .score-table th{font-size:5.85pt;padding:1.35mm 1.6mm;}
.page1-compact .score-table td{padding:1.35mm 1.6mm;line-height:1.18;}
.page1-compact .status-pill{font-size:5.8pt;padding:.7mm 1.5mm;}
.page1-narrative-grid{gap:2.5mm;}
.page1-narrative-grid .story-block{height:34mm;min-height:0;padding:2.8mm 3.2mm;}
.page1-narrative-grid .story-block p{font-size:7.35pt;line-height:1.28;}
.page1-signal-row{gap:2.5mm;}
.page1-signal-row .signal{height:24mm;padding:2.6mm;}
.page1-signal-row .signal .label{font-size:5.9pt;margin-bottom:.9mm;}
.page1-signal-row .signal .value{font-size:11.5pt;margin-top:.5mm;}
.page1-signal-row .signal .text{font-size:6.25pt;line-height:1.18;margin-top:.9mm;}
.page2-compact .story-block{min-height:19mm;padding:2.45mm 3mm;}
.page2-compact .story-block p{font-size:7.25pt;line-height:1.25;}
.page2-signals .signal{height:18.5mm;min-height:18.5mm;padding:2.5mm;}
.page2-signals .signal .label{font-size:5.9pt;margin-bottom:.7mm;}
.page2-signals .signal .value{font-size:12.8pt;}
.page2-signals .signal .text{font-size:6.15pt;line-height:1.15;margin-top:.8mm;}
.ai-note{margin-top:2mm;font-size:6.4pt;color:#64748B;line-height:1.25;}
.callout-link{font-size:7.8pt;color:#64748B;font-weight:700;}
.callout-link a{color:#64748B!important;text-decoration:none!important;font-weight:700;}
.dashboard-link,.cover .dashboard-link a,.cover a{color:#E2E8F0!important;text-decoration:none!important;font-weight:700;}
"""

# =============================================================================
# 8. HTML COMPONENT HELPERS
# =============================================================================

def page_wrap(k: dict, number: int, content: str) -> str:
    return f"""
    <section class="page">
      <header class="page-header">
        <div class="header-left">
          <div class="company">{_safe(COMPANY_NAME)}</div>
          <div class="meta">Periode Data: {date_range_text(k)} | Generated: {_safe(k['now_str'])}</div>
        </div>
        <div class="header-right">
          <div class="trend-badge {trend_badge_class(k['kondisi'])}">Trend<br>{_safe(k['kondisi'])}</div>
          <div class="page-count">Halaman<br>{number} dari {CONTENT_PAGES}</div>
        </div>
      </header>
      <main class="content">{content}</main>
      <footer class="page-footer">{_safe(REPORT_CLASSIFICATION)} - {_safe(COMPANY_NAME)} - Confidential</footer>
    </section>"""

def cover_page(k: dict) -> str:
    return f"""
    <section class="page cover">
      <div>
        <div class="brand">{_safe(COMPANY_NAME)}</div>
        <div class="main-title">Daily Sales<br>Performance<br><span class="accent">Invoice</span></div>
        <div class="cover-badge">Kondisi Harian: {_safe(k['kondisi'])}</div>
        <div class="headline">{_safe(k['headline'])}</div>
        <div class="dashboard-link"><strong>Full Dashboard:</strong> <a href="{_safe(REPORT_DASHBOARD_URL)}">{_safe(REPORT_DASHBOARD_URL)}</a></div>
        <div class="headline" style="font-size:10pt;margin-top:7mm;">Disiapkan oleh <strong>{_safe(PREPARED_BY)}</strong><br>Ditujukan kepada <strong>{_safe(REPORT_AUDIENCE)}</strong></div>
      </div>
      <div class="cover-panel">
        <div class="row"><div class="label">Periode Data</div><div class="value">{date_range_text(k)}</div></div>
        <div class="row"><div class="label">Tanggal Generasi</div><div class="value">{_safe(k['now_str'])}</div></div>
        <div class="row"><div class="label">Klasifikasi</div><div class="value" style="color:#FCA5A5;font-weight:800;">{_safe(REPORT_CLASSIFICATION.upper())}</div></div>
        <div class="row"><div class="label">Ditujukan Kepada</div><div class="value">{_safe(REPORT_AUDIENCE)}</div></div>
      </div>
      <div class="watermark">CONFIDENTIAL</div>
      <div style="display:flex;justify-content:space-between;color:#718096;font-size:6.5pt;"><span>Dokumen ini bersifat rahasia dan hanya untuk keperluan internal manajemen.</span><span>© 2026 PT Pancamas Pipasakti</span></div>
    </section>"""

def chart_card(title: str, svg: str, height_class: str = "h-120") -> str:
    return f'<div class="card chart-card"><div class="chart-title">{_safe(title)}</div><div class="svg-box {height_class}">{svg}</div></div>'

def insight(title: str, body: str, tone: str = "") -> str:
    tone_cls = f" {tone}" if tone else ""
    return f'<div class="insight{tone_cls}"><div class="label">{_safe(title)}</div><div>{body}</div></div>'

def narrative_box(label: str, body: str) -> str:
    return f'<div class="story-block"><div class="label">{_safe(label)}</div><p>{body}</p></div>'

def kpi_card(label: str, value: str, delta: float, sub: str, tone: str = "") -> str:
    cls      = pct_class(delta)
    tone_cls = f" {tone}" if tone else ""
    return f'<div class="kpi-card{tone_cls}"><div class="kpi-label">{_safe(label)}</div><div class="kpi-value">{_safe(value)}</div><div class="kpi-delta {cls}">{arrow(delta)} {fmt_pct(delta)} {_safe(sub)}</div></div>'

def signal_card(label: str, value: str, text: str) -> str:
    return f'<div class="signal"><div class="label">{_safe(label)}</div><div class="value">{_safe(value)}</div><div class="text">{_safe(text)}</div></div>'

def status_label(actual, target, allow_na=False) -> str:
    if allow_na or target in [None, "-"] or pd.isna(target) or float(target) <= 0:
        return '<span class="status-pill status-na">N/A</span>'
    return '<span class="status-pill status-on">On Track</span>' if actual >= target else '<span class="status-pill status-off">Off Track</span>'

def scorecard_table(k: dict) -> str:
    pulse_label = k.get("pulse_label", "DoD")
    mom_rows = []
    if k.get("has_completed_mom"):
        mom_rows.append((
            f"Completed MoM ({k.get('mom_completed_current_label','-')} vs {k.get('mom_completed_previous_label','-')})",
            fmt_rp_smart(k.get("rev_mom_completed_current", 0)),
            fmt_rp_smart(k.get("rev_mom_completed_previous", 0)),
            k.get("pct_mom_completed", np.nan),
            '<span class="status-pill status-na">Info</span>',
        ))

    qoq_rows = []
    if k.get("has_qoq_complete"):
        qoq_rows.append((
            f"Completed QoQ ({k.get('qoq_current_label','-')} vs {k.get('qoq_previous_label','-')})",
            fmt_rp_smart(k.get("rev_qoq_current", 0)),
            fmt_rp_smart(k.get("rev_qoq_previous", 0)),
            k.get("pct_qoq_complete", np.nan),
            '<span class="status-pill status-na">Info</span>',
        ))

    rows = [
        (f"Daily Revenue ({pulse_label})", fmt_rp_smart(k["rev_dod_current"]), fmt_rp_smart(k["rev_dod_previous"]), k.get("pct_dod", 0), '<span class="status-pill status-na">vs Prev Day</span>'),
        (f"Revenue Bulan Berjalan ({k['label_bini']})", fmt_rp_smart(k["rev_bini"]), fmt_rp_smart(k["target_rev_mo"]), (k.get("target_attainment", np.nan) - 100) if pd.notna(k.get("target_attainment", np.nan)) else np.nan, status_label(k["rev_bini"], k["target_rev_mo"])),
        ("Rata-rata Nilai Transaksi (DoD)", fmt_rp_smart(k["avg_trx_dod_current"]), fmt_rp_smart(k["avg_trx_dod_previous"]), delta_pct(k["avg_trx_dod_current"], k["avg_trx_dod_previous"]), '<span class="status-pill status-na">vs Prev Day</span>'),
        ("Jumlah Invoice Aktif (DoD)", f"{k['trx_dod_current']:,.0f} Trx", f"{k['trx_dod_previous']:,.0f} Trx", delta_pct(k["trx_dod_current"], k["trx_dod_previous"]), '<span class="status-pill status-na">vs Prev Day</span>'),
        ("ICI Total Volume MTD", fmt_qty_smart(k.get("ici_volume_actual_mtd", 0), "Lt"), fmt_qty_smart(k.get("ici_volume_target_mtd", 0), "Lt"), (k.get("ici_volume_achievement_pct", np.nan) - 100) if pd.notna(k.get("ici_volume_achievement_pct", np.nan)) else np.nan, status_label(k.get("ici_volume_actual_mtd", 0), k.get("ici_volume_target_mtd", 0), allow_na=not (k.get("ici_volume_target_mtd", 0) > 0))),
        ("ICI Total Weight MTD", fmt_qty_smart(k.get("ici_weight_actual_mtd", 0), "Kg"), fmt_qty_smart(k.get("ici_weight_target_mtd", 0), "Kg"), (k.get("ici_weight_achievement_pct", np.nan) - 100) if pd.notna(k.get("ici_weight_achievement_pct", np.nan)) else np.nan, status_label(k.get("ici_weight_actual_mtd", 0), k.get("ici_weight_target_mtd", 0), allow_na=not (k.get("ici_weight_target_mtd", 0) > 0))),
    ]
    rows = rows[:1] + mom_rows + qoq_rows + rows[1:]
    body = []
    for metric, actual, target, delta_val, status in rows:
        cls = pct_class(delta_val)
        body.append(f'<tr><td class="metric">{_safe(metric)}</td><td class="right">{_safe(actual)}</td><td class="right">{_safe(target)}</td><td class="right {cls}">{arrow(delta_val)} {fmt_pct(delta_val)}</td><td class="center">{status}</td></tr>')
    return (f'<div class="card"><table class="score-table">'
            f'<thead><tr><th>Metrik Operasional</th><th class="right">Aktual</th><th class="right">Target / Pembanding</th><th class="right">Delta</th><th class="center">Status</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')

def mini_table(df: pd.DataFrame, label_col: str, title: str, limit: int = 6, sort_abs: bool = True) -> str:
    if df.empty: return ""
    dfx = df.copy()
    if sort_abs and "Delta" in dfx.columns:
        dfx["AbsDelta"] = dfx["Delta"].abs()
        dfx = dfx.nlargest(limit, "AbsDelta")
    else:
        dfx = dfx.head(limit)
    rows = []
    for _, row in dfx.iterrows():
        delta = float(row.get("Delta",0))
        pct   = float(row.get("Pct",0))
        cls   = pct_class(pct)
        rows.append(f'<tr><td class="metric">{_safe(truncate_text(row[label_col],30))}</td><td class="right">{_safe(fmt_rp_smart(delta))}</td><td class="right {cls}">{arrow(pct)} {fmt_pct(pct)}</td></tr>')
    return (f'<div class="card pad"><div class="kicker">{_safe(title)}</div>'
            f'<table class="mini-table"><thead><tr><th>Entity</th><th class="right">Delta</th><th class="right">%</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')

def _ins(k: dict, key: str) -> str:
    return _safe(k.get("insights",{}).get(key, fallback_insight_pack(k).get(key,"")))

def _ins_html(k: dict, key: str) -> str:
    return k.get("insights",{}).get(key, fallback_insight_pack(k).get(key,""))

def board_directives_table(k: dict) -> str:
    raw = k.get("insights",{}).get("board_directives") or fallback_insight_pack(k).get("board_directives",[])
    if not isinstance(raw, list): raw = []
    # Sanitize
    cleaned = []
    for item in raw[:5]:
        if not isinstance(item, dict): continue
        directive = _normalize_text(item.get("directive",""), 90)
        detail    = _normalize_text(item.get("detail",""), 450)
        outcome   = _normalize_text(item.get("business_outcome",""), 90)
        combined  = f"{directive} {detail} {outcome}"
        if _contains_banned_tech(combined) or not directive or not detail: continue
        cleaned.append({"no": str(len(cleaned)+1), "directive": directive, "detail": detail, "business_outcome": outcome or "Management action"})
    # Pad with fallback if needed
    if len(cleaned) < 5:
        for fb in fallback_insight_pack(k).get("board_directives",[]):
            if len(cleaned) >= 5: break
            exist_dirs = {d["directive"].lower() for d in cleaned}
            if fb["directive"].lower() not in exist_dirs:
                row = dict(fb); row["no"] = str(len(cleaned)+1)
                cleaned.append(row)
    body = "".join(
        f'<tr><td class="number-cell">{_safe(d["no"])}</td><td><div class="metric">{_safe(d["directive"])}</div><div class="small-note">{_safe(d["detail"])}</div></td><td>{_safe(d["business_outcome"])}</td></tr>'
        for d in cleaned
    )
    return (f'<div class="card"><table class="directive-table">'
            f'<thead><tr><th>No</th><th>Board Directive</th><th>Business Outcome</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')

# =============================================================================
# 9. PAGES
# =============================================================================

def page_1_snapshot(k: dict) -> str:
    content = f"""
      <div class="page1-compact">
        <div class="flex-spread">
          <div><div class="kicker">01 - Board Snapshot</div><div class="title">Commercial health overview</div><div class="subtitle">{_ins(k,'board_subtitle')}</div></div>
          <div class="small-note" style="text-align:right;">As of<br><strong>{k['date_max']:%d %b %Y}</strong></div>
        </div>
        <div class="callout-link"><strong>Full Dashboard:</strong> <a href="{_safe(REPORT_DASHBOARD_URL)}">{_safe(REPORT_DASHBOARD_URL)}</a></div>
        <div class="kpi-grid">
          {kpi_card('Daily Revenue', fmt_rp_smart(k['rev_dod_current']), k['pct_dod'], 'DoD', 'red')}
          {kpi_card('Revenue Bulan Berjalan', fmt_rp_smart(k['rev_bini']), (k.get('target_attainment', np.nan) - 100) if pd.notna(k.get('target_attainment', np.nan)) else np.nan, 'vs Target', 'red')}
          {kpi_card('Rata-rata Invoice', fmt_rp_smart(k['avg_trx_dod_current']), delta_pct(k['avg_trx_dod_current'], k['avg_trx_dod_previous']), 'DoD', 'green')}
          {kpi_card('Jumlah Invoice Harian', f"{k['trx_dod_current']:,.0f} Trx", delta_pct(k['trx_dod_current'], k['trx_dod_previous']), 'DoD', 'teal')}
        </div>
        {scorecard_table(k)}
        <div class="grid-2 page1-narrative-grid">
          {narrative_box('Executive Readout', _ins_html(k,'board_summary'))}
          {narrative_box('Decision Lens', _ins_html(k,'board_decision'))}
        </div>
        <div class="signal-row page1-signal-row">
          {signal_card('Primary Pressure', 'Volume', 'Volume transaksi menjadi titik tekan utama recovery.')}
          {signal_card('Target Gap', fmt_rp_smart(k.get('target_gap',0)), 'Selisih aktual terhadap target bulan berjalan.')}
          {signal_card('Management Focus', 'Recovery', 'Prioritaskan repeat order, stok siap jual, dan follow-up customer aktif.')}
        </div>
      </div>"""
    return page_wrap(k, 1, content)



def compact_pattern_value(pattern_text: str) -> str:
    """Return a short label for a pattern signal so dark signal cards never overflow."""
    text = str(pattern_text or "").lower()

    if "tekanan berlapis" in text:
        return "Tekanan Berlapis"
    if "rebound" in text:
        return "Rebound Awal"
    if "pembalikan negatif" in text:
        return "Pembalikan Negatif"
    if "ekspansi beruntun" in text:
        return "Ekspansi Beruntun"
    if "koreksi beruntun" in text:
        return "Koreksi Beruntun"
    if "fluktuatif" in text:
        return "Fluktuatif"
    if "downtrend" in text:
        return "Downtrend"
    if "uptrend" in text:
        return "Uptrend"
    if "perlambatan" in text:
        return "Perlambatan Awal"
    if "momentum penguatan" in text:
        return "Momentum Menguat"

    return "Pola Terpantau"


def compact_pattern_note(pattern_text: str, k: dict) -> str:
    """Return a concise dynamic note for the pattern card."""
    text = str(pattern_text or "").lower()
    pulse_label = str(k.get("pulse_label", "Pulse"))
    mom = fmt_pct(k.get("pct_m", 0))
    pulse = fmt_pct(k.get("pct_pulse", k.get("pct_w", 0)))

    if "tekanan berlapis" in text:
        return f"DoD {fmt_pct(k.get('pct_dod', 0))} dan {pulse_label} {pulse} sama-sama perlu dipantau."
    if "rebound" in text:
        return f"Ada sinyal pemulihan awal, tetapi konsistensi {pulse_label} masih perlu dijaga."
    if "pembalikan negatif" in text:
        return "Arah tren mulai melemah; validasi pipeline dan repeat order perlu dipercepat."
    if "ekspansi beruntun" in text:
        return "Momentum positif perlu diamankan agar tidak melemah pada periode berikutnya."
    if "koreksi beruntun" in text:
        return "Koreksi berulang perlu direspons pada area dan SKU prioritas."
    if "fluktuatif" in text:
        return "Pergerakan belum stabil; cek penyumbang deviasi terbesar."
    if "downtrend" in text:
        return "Arah tren melemah; recovery perlu difokuskan pada kontribusi terbesar."
    if "uptrend" in text:
        return "Arah tren membaik; momentum perlu dijaga lewat eksekusi harian."
    if "perlambatan" in text:
        return "Perlambatan mulai terlihat; kontrol pipeline perlu diperketat lebih awal."

    return f"Sinyal pola terbaca dari kombinasi DoD {fmt_pct(k.get('pct_dod', 0))} dan {pulse_label} {pulse}."
def qoq_signal_card(k: dict) -> str:
    """Show completed QoQ only when the latest completed quarter and comparison quarter exist."""
    if not k.get("has_qoq_complete"):
        return ""
    return signal_card(
        "Completed QoQ",
        fmt_pct(k.get("pct_qoq_complete", np.nan)),
        f"{k.get('qoq_current_label','-')} ({k.get('qoq_current_date_range','-')}) vs {k.get('qoq_previous_label','-')} ({k.get('qoq_previous_date_range','-')}).",
    )

def page_2_monthly(k: dict, v: dict) -> str:
    pattern_text = _ins(k, "monthly_pattern_readout")
    pattern_value = compact_pattern_value(pattern_text)
    pattern_note = compact_pattern_note(pattern_text, k)

    content = f"""
      <div>
        <div class="kicker">02 - Monthly Momentum</div>
        <div class="title">Revenue trajectory and daily pressure</div>
        <div class="subtitle">Daily movement is read with DoD; completed MoM appears only in the scorecard when the latest data date is day 1.</div>
      </div>

      {chart_card('Monthly trend', v['monthly'], 'h-104')}

      <div class="text-chart-split page2-compact">
        <div class="story-stack compact-story-stack">
          {narrative_box('Monthly Readout', _ins_html(k,'monthly_readout'))}
          {narrative_box('Arah Tren', _ins_html(k,'monthly_pattern_readout'))}
          {narrative_box('Management Action', _ins_html(k,'monthly_action'))}
        </div>

        <div class="compact-signal-row page2-signals">
          {signal_card('DoD Trend', fmt_pct(k.get('pct_dod', 0)), f"{k.get('dod_current_date'):%d %b %Y} vs {k.get('dod_previous_date'):%d %b %Y}.")}
          {qoq_signal_card(k)}
          {signal_card('Pattern Risk', pattern_value, pattern_note)}
          {signal_card('Target Gap', fmt_rp_smart(k.get('page2_target_gap', k.get('target_gap', np.nan))), 'Selisih aktual vs target non-ICI; exclude Agen & Project.')}
        </div>
      </div>
    """
    return page_wrap(k, 2, content)

def page_3_weekly(k: dict, v: dict) -> str:
    content = f"""
      <div><div class="kicker">03 - Revenue Mingguan</div><div class="title">{k.get('pulse_title','Quarter-to-date pulse')}</div><div class="subtitle">{_ins(k,'weekly_subtitle')}</div></div>
      {chart_card('Weekly revenue trend', v['weekly'], 'h-128')}
      <div class="grid-2">
        {narrative_box('Operational Readout', _ins_html(k,'weekly_readout'))}
        {narrative_box('Arah Tren', _ins_html(k,'weekly_pattern_readout'))}
        {narrative_box('Operational Action', _ins_html(k,'weekly_action'))}
        {narrative_box('Cara Baca Grafik', 'Grafik ini menampilkan revenue per minggu. Bandingkan bar minggu terakhir dengan minggu sebelumnya untuk melihat arah naik, turun, atau stabil.')}
      </div>"""
    return page_wrap(k, 3, content)

def page_4_branch(k: dict, v: dict) -> str:
    content = f"""
      <div><div class="kicker">04 - Regional Correction Map</div><div class="title">Branch movements: DoD</div><div class="subtitle">Branch movement difokuskan pada perubahan harian agar tindakan area lebih cepat dan tidak bias oleh perbandingan MTD vs full month.</div></div>
      {chart_card('Branch movement - DoD', v['branch_wow'], 'h-112')}
      <div class="grid-2">
        {narrative_box('Regional Readout', _ins_html(k,'branch_readout'))}
        {narrative_box('Regional Action', _ins_html(k,'branch_action'))}
      </div>"""
    return page_wrap(k, 4, content)

def channel_sales_insight_html(k: dict) -> str:
    """Build Retail, Project, and Agen insight cards for Page 5.

    Each card is data-driven and points to the most pressured and strongest
    supporting salesman in each channel.
    """
    channel_df = k.get("sales_channel_pulse", pd.DataFrame())
    sales_df = k.get("sales_channel_sales_pulse", pd.DataFrame())
    pulse_label = k.get("pulse_label", "periode berjalan")

    if channel_df is None or channel_df.empty or sales_df is None or sales_df.empty:
        return narrative_box(
            "Retail / Project / Agen Insight",
            "Data channel Retail, Project, dan Agen belum tersedia untuk membentuk insight per sales."
        )

    def channel_action(channel: str, pressured_sales: str) -> str:
        if channel == "Retail":
            return (
                f"Fokus Retail diarahkan ke repeat order, customer aktif, dan SKU fast-moving. "
                f"Untuk {pressured_sales}, validasi customer yang belum reorder, ketersediaan stok, dan peluang bundling yang bisa ditutup dalam minggu berjalan."
            )
        if channel == "Project":
            return (
                f"Fokus Project diarahkan ke pipeline quotation, jadwal PO, termin delivery, dan hambatan approval. "
                f"Untuk {pressured_sales}, cek project yang statusnya tertahan, estimasi closing, serta kebutuhan support pricing atau dokumen."
            )
        if channel == "Agen":
            return (
                f"Fokus Agen diarahkan ke reorder distributor, coverage area, plafon kredit, dan kesiapan stok. "
                f"Untuk {pressured_sales}, cek agen yang turun order, potensi switching ke kompetitor, serta kebutuhan program harga atau service level."
            )
        return f"Fokus tindakan diarahkan pada pipeline {pressured_sales}, customer aktif, dan peluang closing terdekat."

    cards = []

    for channel in ["Retail", "Project", "Agen"]:
        ch = channel_df[channel_df["Sales_Channel"].astype(str).eq(channel)].copy()
        sd = sales_df[sales_df["Sales_Channel"].astype(str).eq(channel)].copy()

        if ch.empty:
            cards.append(
                f"""
                <div class="card pad">
                  <div class="kicker">{_safe(channel)}</div>
                  <p>Belum ada data {channel} pada {pulse_label}.</p>
                </div>
                """
            )
            continue

        ch_row = ch.iloc[0]
        rev_a = float(ch_row.get("Rev_A", 0) or 0)
        rev_b = float(ch_row.get("Rev_B", 0) or 0)
        delta = float(ch_row.get("Delta", 0) or 0)
        pct = float(ch_row.get("Pct", 0) or 0)

        sd_neg = sd.sort_values("Delta", ascending=True).head(1)
        sd_pos = sd.sort_values("Delta", ascending=False).head(1)

        if not sd_neg.empty:
            neg_row = sd_neg.iloc[0]
            neg_sales = str(neg_row.get("Salesman", "-"))
            neg_delta = float(neg_row.get("Delta", 0) or 0)
            neg_pct = float(neg_row.get("Pct", 0) or 0)
        else:
            neg_sales, neg_delta, neg_pct = "-", 0.0, 0.0

        if not sd_pos.empty:
            pos_row = sd_pos.iloc[0]
            pos_sales = str(pos_row.get("Salesman", "-"))
            pos_delta = float(pos_row.get("Delta", 0) or 0)
            pos_pct = float(pos_row.get("Pct", 0) or 0)
        else:
            pos_sales, pos_delta, pos_pct = "-", 0.0, 0.0

        direction = "menguat" if delta > 0 else "terkoreksi" if delta < 0 else "stabil"

        body = (
            f"<strong>{channel}</strong> {direction} {fmt_pct(pct)} pada {pulse_label}, "
            f"dari {fmt_rp_smart(rev_b)} menjadi {fmt_rp_smart(rev_a)} "
            f"dengan delta {fmt_rp_smart(delta)}. "
            f"Tekanan terbesar berasal dari <strong>{_safe(neg_sales)}</strong> "
            f"sebesar {fmt_rp_smart(neg_delta)} ({fmt_pct(neg_pct)}), "
            f"sedangkan penguat terbesar berasal dari <strong>{_safe(pos_sales)}</strong> "
            f"sebesar {fmt_rp_smart(pos_delta)} ({fmt_pct(pos_pct)}). "
            f"{_safe(channel_action(channel, neg_sales))}"
        )

        cards.append(
            f"""
            <div class="card pad">
              <div class="kicker">{_safe(channel)} Channel</div>
              <div style="font-size:8.2pt;line-height:1.42;color:#334155;">{body}</div>
            </div>
            """
        )

    return f"""
      <div class="grid-3">
        {''.join(cards)}
      </div>
    """


def page_5_sales_delta(k: dict, v: dict) -> str:
    content = f"""
      <div><div class="kicker">05 - Sales Force Contribution</div><div class="title">Field execution delta - {k.get('pulse_label','QoQ')}</div><div class="subtitle">{_ins(k,'sales_delta_subtitle')}</div></div>
      {chart_card('Salesman delta - '+k.get('pulse_label','QoQ'), v['sales_delta'], 'h-128')}
      <div class="grid-2">
        {narrative_box('Sales Readout', _ins_html(k,'sales_delta_readout'))}
        {narrative_box('Sales Action', _ins_html(k,'sales_delta_action'))}
      </div>
      {channel_sales_insight_html(k)}
      {mini_table(k['pulse_sales'], 'Salesman', 'Salesman Watchlist', 5)}"""
    return page_wrap(k, 5, content)

def page_6_sales_efficiency(k: dict, v: dict) -> str:
    content = f"""
      <div><div class="kicker">06 - Sales Force Efficiency</div><div class="title">Top performer benchmark</div><div class="subtitle">{_ins(k,'sales_eff_subtitle')}</div></div>
      {chart_card('Top salesman efficiency score', v['sales_eff'], 'h-128')}
      <div class="grid-2">
        {narrative_box('Efficiency Readout', _ins_html(k,'sales_eff_readout'))}
        {narrative_box('Execution Action', _ins_html(k,'sales_eff_action'))}
      </div>
      <div class="signal-row">
        {signal_card('Top Performer', _safe(k['eff_bini'].iloc[0]['Salesman']) if not k['eff_bini'].empty else '-', 'Benchmark eksekusi lapangan bulan berjalan.')}
        {signal_card('Top Score', f"{k['eff_bini'].iloc[0]['Score']:.1f}" if not k['eff_bini'].empty else '-', 'Skor gabungan revenue dan rata-rata transaksi.')}
        {signal_card('Joint Visit', '5 hari', 'Cadence replikasi playbook untuk personel dengan skor rendah.')}
      </div>"""
    return page_wrap(k, 6, content)

def page_7_portfolio(k: dict, v: dict) -> str:
    content = f"""
      <div><div class="kicker">07 - Portfolio Mix</div><div class="title">Division contribution shift</div><div class="subtitle">{_ins(k,'portfolio_subtitle')}</div></div>
      {chart_card('Division mix comparison', v['division'], 'h-104')}
      <div class="grid-2">
        {narrative_box('Portfolio Readout', _ins_html(k,'portfolio_readout'))}
        {narrative_box('Portfolio Action', _ins_html(k,'portfolio_action'))}
      </div>
      <div class="signal-row">
        {signal_card('Current Month', k['label_bini'], 'Periode revenue berjalan.')}
        {signal_card('Previous Month', k['label_blalu'], 'Pembanding proporsi divisi.')}
        {signal_card('Target Gap', fmt_rp_smart(k.get('target_gap',0)), 'Selisih aktual terhadap target bulan berjalan.')}
      </div>"""
    return page_wrap(k, 7, content)

def page_8_concentration(k: dict, v: dict) -> str:
    content = f"""
      <div><div class="kicker">08 - Concentration Risk</div><div class="title">Pareto dependency: branch and SKU</div><div class="subtitle">{_ins(k,'concentration_subtitle')}</div></div>
      {chart_card('Branch concentration', v['pareto_branch'], 'h-76')}
      {chart_card('SKU concentration', v['pareto_sku'], 'h-76')}
      <div class="grid-2">
        {narrative_box('Concentration Readout', _ins_html(k,'concentration_readout'))}
        {narrative_box('Risk Action', _ins_html(k,'concentration_action'))}
      </div>"""
    return page_wrap(k, 8, content)

def page_9_product_velocity(k: dict, v: dict) -> str:
    content = f"""
      <div><div class="kicker">09 - Product Velocity</div><div class="title">SKU daily movers radar</div><div class="subtitle">{_ins(k,'product_subtitle')}</div></div>
      {chart_card('SKU losers', v['sku_losers'], 'h-76')}
      {chart_card('Best SKU movers', v['sku_gainers'], 'h-76')}
      <div class="grid-2">
        {narrative_box('Product Readout', _ins_html(k,'product_readout'))}
        {narrative_box('SKU Action', _ins_html(k,'product_action'))}
      </div>"""
    return page_wrap(k, 9, content)


def page_10_ici_target(k: dict, v: dict) -> str:
    summary = ici_target_summary(k)
    vol_ach = summary.get("volume_ach", np.nan)
    wei_ach = summary.get("weight_ach", np.nan)
    vol_ach_txt = f"{vol_ach:.1f}%" if pd.notna(vol_ach) and np.isfinite(vol_ach) else "-"
    wei_ach_txt = f"{wei_ach:.1f}%" if pd.notna(wei_ach) and np.isfinite(wei_ach) else "-"
    cols = k.get("ici_measure_columns", {}) or {}
    col_note = ""
    if not cols.get("volume_col") or not cols.get("weight_col"):
        col_note = " Catatan: pastikan kolom Volume dan Weight dari invoice tersedia agar realisasi unit terbaca penuh."

    readout = (
        f"Pada bulan berjalan, realisasi ICI untuk volume mencapai {fmt_qty_smart(summary['volume_actual'], 'Lt')} "
        f"dari target {fmt_qty_smart(summary['volume_target'], 'Lt')} ({vol_ach_txt}), sementara realisasi weight mencapai "
        f"{fmt_qty_smart(summary['weight_actual'], 'Kg')} dari target {fmt_qty_smart(summary['weight_target'], 'Kg')} ({wei_ach_txt}). "
        f"Deviasi unit terbesar saat ini berada pada {summary['top_brand']} sebesar {fmt_qty_smart(summary['top_gap_qty'], summary['top_unit'])}.{col_note}"
    )
    action = (
        "Kontrol ICI perlu membaca realisasi unit terhadap target unit, bukan hanya nominal invoice. "
        "Brand dengan gap volume atau weight terbesar perlu diprioritaskan untuk validasi stok, kesiapan pengiriman, dan percepatan konversi order agar pencapaian unit tidak tertutup oleh pergerakan value."
    )
    content = f"""
      <div>
        <div class="kicker">10 - ICI Target Control</div>
        <div class="title">Volume and weight actual vs target</div>
        <div class="subtitle">Realisasi ICI dibandingkan dengan target unit: Warnamu memakai weight, sedangkan brand lainnya memakai volume.</div>
      </div>
      {chart_card('ICI actual vs target unit', v.get('ici_vw', ''), 'h-120')}
      <div class="grid-2">
        {narrative_box('ICI Unit Readout', readout)}
        {narrative_box('ICI Control Action', action)}
      </div>
      {ici_target_table(k)}
    """
    return page_wrap(k, 10, content)

def page_11_directives(k: dict, v: dict) -> str:
    execution_text = (
        f"<strong>Target gap</strong> bulan berjalan berada di {fmt_rp_smart(k.get('target_gap',0))}. "
        "Prioritas manajemen adalah mempercepat pipeline yang paling dekat menjadi invoice, menyelesaikan hambatan stok atau pricing, "
        "dan memastikan follow-up customer aktif bernilai besar berjalan setiap hari."
    )
    content = f"""
      <div><div class="kicker">11 - Board Directives</div><div class="title">Decision register and operating cadence</div><div class="subtitle">{_ins(k,'trend_pattern_subtitle')}</div></div>
      {narrative_box('Executive Anomaly Recap', _ins_html(k,'directive_recap'))}
      {narrative_box('Trend Pattern Action', _ins_html(k,'trend_pattern_action'))}
      {board_directives_table(k)}
      <div class="grid-3">
        {insight('Operating Cadence', '<strong>Daily:</strong> cek revenue pulse, branch delta, salesman watchlist, SKU intervention list, serta ICI unit control. <strong>Weekly:</strong> review recovery progress, cross-buffering, collection watchlist, dan keputusan eskalasi.', 'teal')}
        {insight('Decision Follow-up', '<strong>Management follow-up:</strong> setiap directive perlu diterjemahkan menjadi action tracker internal berisi PIC, timeline, status eksekusi, dan hambatan utama. Isu kritikal tetap dieskalasikan ke agenda direksi.', 'purple')}
        {insight('Target Control Focus', cash_text, 'red')}
      </div>
    """
    return page_wrap(k, 11, content)


def page_12_glossary(k: dict, v: dict) -> str:
    glossary_items = [
        ("Revenue", "Nilai penjualan berdasarkan invoice sales; secara value menggunakan Net Price dari data invoice."),
        ("Target Sales", "Target penjualan aktual dari workbook target, disesuaikan dengan bulan berjalan."),
        ("Achievement", "Persentase pencapaian aktual terhadap target. Nilai di atas 100% berarti aktual melampaui target."),
        ("Delta / Gap", "Selisih antara aktual dan target atau antara periode berjalan dan periode pembanding."),
        ("MoM", "Month-over-month; bulan berjalan dibanding bulan sebelumnya."),
        ("WoW", "Week-over-week; minggu berjalan dibanding minggu sebelumnya."),
        ("QoQ", "Quarter-to-date berjalan dibanding periode ekuivalen pada kuartal sebelumnya."),
        ("YTD", "Year-to-date; akumulasi dari awal tahun sampai tanggal akhir data."),
        ("Tren 3 Minggu", "Perbandingan revenue tiga minggu terakhir untuk melihat apakah arah penjualan membaik, melemah, atau stabil."),
        ("Basket Size", "Rata-rata nilai transaksi; revenue dibagi jumlah transaksi invoice."),
        ("Transaction Volume", "Jumlah transaksi invoice yang terbentuk pada periode analisis."),
        ("Branch Movement", "Perubahan revenue per cabang dibanding periode pembanding."),
        ("Sales Force Delta", "Perubahan kontribusi revenue per person atau kanal sales dibanding periode pembanding."),
        ("Sales Efficiency Score", "Skor internal yang menggabungkan kontribusi revenue dan rata-rata transaksi."),
        ("Division Mix", "Komposisi kontribusi revenue berdasarkan divisi penjualan."),
        ("Pareto", "Analisis konsentrasi untuk melihat berapa entitas utama yang membentuk mayoritas revenue."),
        ("SKU Losers / Best Movers", "SKU dengan koreksi atau best movement DoD terbesar."),
        ("Cross-buffering", "Redistribusi stok antar area/cabang untuk menjaga ketersediaan barang prioritas."),
        ("ICI", "Divisi yang memiliki kontrol tambahan berbasis unit volume dan weight."),
        ("Volume Control", "Kontrol actual vs target ICI berbasis volume untuk brand selain Warnamu."),
        ("Weight Control", "Kontrol actual vs target ICI berbasis weight untuk Warnamu."),
        ("Sales Project", "Kanal sales project sesuai master sales internal."),
        ("Sales Agen", "Kanal sales agen sesuai master sales internal."),
        ("Supervisor", "Level koordinasi lapangan di bawah branch manager dan di atas cosales/salesman."),
        ("Cosales", "Peran support sales yang membantu proses penjualan dan koordinasi customer."),
    ]
    rows = "".join(
        f"<tr><td class='metric'>{_safe(term)}</td><td>{_safe(desc)}</td></tr>"
        for term, desc in glossary_items
    )
    content = f"""
      <div><div class="kicker">12 - Glossary</div><div class="title">Business terms used in this report</div><div class="subtitle">Daftar istilah ini dibuat agar pembaca report memiliki pemahaman yang sama terhadap metrik dan istilah operasional.</div></div>
      <div class="card"><table class="mini-table">
        <thead><tr><th style="width:34%;">Istilah</th><th>Penjelasan</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    """
    return page_wrap(k, 12, content)


def page_13_methodology(k: dict, v: dict) -> str:
    method_rows = [
        ("Periode data", f"Report memakai data invoice dari {date_range_text(k)} dengan tanggal akhir data {k['date_max']:%d %b %Y}."),
        ("Revenue actual", "Actual revenue dihitung dari Net Price pada sales invoice."),
        ("Target value", "Target value diambil dari sheet target reguler, dengan kolom Mo 01 sampai Mo 12 dipetakan ke bulan January sampai December."),
        ("Matching target reguler", "Target value dimatching berdasarkan bulan, salesman, divisi, dan SKU ketika field tersebut tersedia pada workbook target."),
        ("SKU target", "Target SKU memakai field breakdown SKU dari workbook target, lalu dinormalisasi agar bisa dibandingkan dengan SKU hasil mapping invoice."),
        ("ICI unit target", "Target ICI memakai sheet Target Cat (V_W), karena kontrol ICI tidak hanya membaca value tetapi juga target unit."),
        ("ICI actual unit", "Actual ICI tidak memakai Net Price untuk unit control. Warnamu dibandingkan memakai Weight, sedangkan brand ICI lainnya dibandingkan memakai Volume."),
        ("Monthly chart", "Monthly trend hanya menampilkan bulan sampai bulan berjalan. Khusus page 2, Total Sales dan Target Sales menggunakan scope non-ICI, sehingga Sales Div IC/ICI dikeluarkan dari chart tersebut."),
        ("Branch dan channel", "Branch dan channel sales menggunakan mapping internal berdasarkan kode salesman dan struktur organisasi."),
        ("Sales hierarchy", "Narasi sales mengikuti hierarki Branch Manager → Supervisor → Cosales → Salesman, sehingga supervisor diperlakukan sebagai level koordinasi, bukan field salesman biasa."),
        ("Arah Tren", "Pola tren dibaca dari kombinasi arah DoD, tren bulanan, perubahan mingguan, volatilitas, dan perubahan antar periode."),
        ("Rounding", "Nilai rupiah dan unit disingkat agar mudah dibaca pada PDF; perhitungan tetap menggunakan angka numerik asli."),
    ]
    rows = "".join(
        f"<tr><td class='metric'>{_safe(item)}</td><td>{_safe(desc)}</td></tr>"
        for item, desc in method_rows
    )
    source_note = _safe(k.get('insights',{}).get('ai_source_note','Dynamic data-driven narrative engine used; no external AI call required.'))
    content = f"""
      <div><div class="kicker">13 - Methodology</div><div class="title">Data logic and calculation notes</div><div class="subtitle">Ringkasan metode ini menjelaskan sumber data, matching target, dan cara membaca metrik utama report.</div></div>
      <div class="card"><table class="mini-table">
        <thead><tr><th style="width:34%;">Area</th><th>Metode</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
      <div class="ai-note">{source_note}</div>
    """
    return page_wrap(k, 13, content)



def sanitize_report_language(html_text: str) -> str:
    """Final wording guard so PDF wording stays clear for management/BOD."""
    replacements = {
        "Pulse": "Pergerakan",
        "pulse": "pergerakan",
        "underlying": "arah dasar",
        "Underlying": "Arah dasar",
        "hidden signal": "indikasi utama",
        "Hidden Signal": "Indikasi Utama",
        "sinyal tersembunyi": "indikasi utama",
        "Sinyal tersembunyi": "Indikasi utama",
        "MA" + "-3": "Tren 3 Minggu",
        "Moving " + "Average": "Tren 3 Minggu",
        "moving average": "tren 3 minggu",
        "Outstanding " + "AR": "",
        "AR " + "Ratio": "",
        "Paid Invoice": "",
        "Cash " + "Conversion": "Target Control",
        "Cash " + "Exposure": "Target Control",
        "Working Capital": "Commercial Execution",
    }
    out = html_text
    for old, new_value in replacements.items():
        out = out.replace(old, new_value)
    return out

# =============================================================================
# 10. BUILD HTML AND PDF
# =============================================================================

def build_html(k: dict, visuals: dict) -> str:
    pages = [
        cover_page(k),
        page_1_snapshot(k),
        page_2_monthly(k, visuals),
        page_3_weekly(k, visuals),
        page_4_branch(k, visuals),
        page_5_sales_delta(k, visuals),
        page_6_sales_efficiency(k, visuals),
        page_7_portfolio(k, visuals),
        page_8_concentration(k, visuals),
        page_9_product_velocity(k, visuals),
        page_10_ici_target(k, visuals),
        page_11_directives(k, visuals),
        page_12_glossary(k, visuals)
    ]
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8"/>
  <title>{_safe(report_title(k))} - {_safe(COMPANY_NAME)}</title>
  <style>{CSS_STYLE}</style>
</head>
<body>{"".join(pages)}</body>
</html>"""

def build_pdf(k: dict, visuals: dict) -> str:
    print("\n[5/7] Membangun HTML portrait v22...")
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_content = sanitize_report_language(build_html(k, visuals))
    output_html  = output_dir / report_filename(k, "html")
    output_pdf   = output_dir / report_filename(k, "pdf")
    output_html.write_text(html_content, encoding="utf-8")
    print(f"[OK] HTML saved: {output_html}")
    print("\n[6/7] Rendering PDF via WeasyPrint...")
    WeasyHTML(filename=str(output_html), base_url=str(output_dir.resolve())).write_pdf(str(output_pdf))
    print(f"[OK] PDF selesai: {output_pdf}")
    return str(output_pdf)


# =============================================================================
# 11. WHATSAPP EXECUTIVE SUMMARY
# =============================================================================

def build_whatsapp_summary(k: dict) -> str:
    date_txt = pd.Timestamp(k["date_max"]).strftime("%d %b %Y")
    condition = str(k.get("kondisi", "STABIL"))
    mom = fmt_pct(k.get("pct_m", 0))
    pulse_label = str(k.get("pulse_label", "Pulse"))
    pulse = fmt_pct(k.get("pct_pulse", k.get("pct_w", 0)))
    revenue = fmt_rp_smart(k.get("rev_bini", 0))
    target = fmt_rp_smart(k.get("target_rev_mo", 0))
    attainment = k.get("target_attainment", np.nan)
    attainment_txt = f"{attainment:.1f}%" if pd.notna(attainment) and np.isfinite(attainment) else "-"

    branch_focus = ""
    mom_branch = k.get("mom_branch", pd.DataFrame())
    if mom_branch is not None and not mom_branch.empty and "Delta" in mom_branch.columns:
        worst = mom_branch.sort_values("Delta", ascending=True).iloc[0]
        branch_focus = f" Area yang paling perlu perhatian adalah {worst.get('Branch', '-')} dengan koreksi {fmt_rp_smart(worst.get('Delta', 0))}."

    ar_txt = ""

    sentence_1 = (
        f"Update {date_txt}: kondisi komersial berada di fase {condition}, dengan revenue bulan berjalan {revenue} "
        f"atau {attainment_txt} dari target {target}; pergerakan DoD {mom} dan {pulse_label} {pulse}."
    )
    sentence_2 = f"{branch_focus}{ar_txt}".strip()
    if not sentence_2:
        sentence_2 = "Prioritas follow-up adalah menjaga pipeline yang paling dekat closing, validasi stok/pricing, dan recovery area penyumbang deviasi terbesar."
    return sentence_1 + "\n" + sentence_2


def write_whatsapp_summary(k: dict) -> str:
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_token = pd.Timestamp(k["date_max"]).strftime("%Y-%m-%d")
    path = output_dir / f"WhatsApp_Executive_Summary_{date_token}.txt"
    summary = build_whatsapp_summary(k)
    path.write_text(summary, encoding="utf-8")
    print("\n[WHATSAPP SUMMARY]")
    print(summary)
    print(f"[OK] WhatsApp summary saved: {path}")
    return str(path)

# =============================================================================
# 11. MAIN
# =============================================================================

def main() -> str:
    print("=" * 88)
    print("  EXECUTIVE REPORT v27 - ICI CHART + GLOSSARY/METHODOLOGY")
    print(f"  {COMPANY_NAME}")
    print("=" * 88)
    df      = load_data()
    metrics = calculate_metrics(df)
    print("\n[4/7] Membuat narasi dinamis berbasis data...")
    metrics["insights"] = generate_ai_insight_pack(metrics)
    visuals = build_visuals(metrics)
    pdf     = build_pdf(metrics, visuals)
    write_whatsapp_summary(metrics)
    print("\n[7/7] Selesai.")
    return pdf

if __name__ == "__main__":
    main()