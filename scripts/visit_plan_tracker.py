# Tracker pipeline — transform "Visit Plan Report" for the Tracker section.
# Input file is passed as an argument (never hardcoded). Column layout is
# detected dynamically from the uploaded file (headers + content) — no
# worksheet name, column name, salesman or customer is ever assumed.
# BigQuery auth: explicit service account key. The key path is configured in
# ONE place — env var BQ_KEY_FILE (default: pipamas-v3-f08db75e6c67.json,
# looked up in the working directory, then next to the app root).

import argparse
import os
import re

import numpy as np
import pandas as pd

from google.cloud import bigquery
from google.oauth2 import service_account


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

PROJECT_ID = os.environ.get("BQ_PROJECT_ID", "pipamas-v3")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "data")
LOCATION = os.environ.get("BQ_LOCATION", "asia-southeast2")

TABLE_TRACKER = "visit_plan_tracker"
TABLE_TRACKER_SUMMARY = "visit_plan_tracker_summary"

_parser = argparse.ArgumentParser(description="Visit Plan Tracker")
_parser.add_argument("--visitplan", required=True, help="Visit Plan Report .xlsx")
_ARGS = _parser.parse_args()


# ============================================================
# DYNAMIC COLUMN DETECTION
# ============================================================

ROLE_HINTS = {
    # role -> header keywords (any language variant the reports use)
    "visit_date": ["visit date", "plan date", "tanggal", "date", "tgl"],
    "salesman": ["salesman", "sales", "employee", "karyawan", "pic"],
    "customer": ["customer", "cust", "outlet", "toko", "client", "klien"],
    "branch": ["branch", "cabang"],
    "status": ["status", "hasil", "realisasi", "result", "keterangan"],
    "purpose": ["purpose", "tujuan", "agenda", "activity", "aktivitas"],
}


def detect_columns(df: pd.DataFrame) -> dict:
    """Match each role to the best column by header keyword, then content."""
    mapping = {}
    taken = set()
    lowered = {c: str(c).strip().lower() for c in df.columns}
    for role, keywords in ROLE_HINTS.items():
        best, best_rank = None, None
        for col, low in lowered.items():
            if col in taken:
                continue
            for rank, kw in enumerate(keywords):
                if kw in low:
                    if best_rank is None or rank < best_rank:
                        best, best_rank = col, rank
                    break
        if best is not None:
            mapping[role] = best
            taken.add(best)

    # content-based fallback for the date column: pick the column that parses
    # as dates most often (headers alone are never trusted blindly)
    if "visit_date" not in mapping:
        best, best_ratio = None, 0.0
        for col in df.columns:
            if col in taken:
                continue
            parsed = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
            ratio = parsed.notna().mean()
            if ratio > 0.6 and ratio > best_ratio:
                best, best_ratio = col, ratio
        if best is not None:
            mapping["visit_date"] = best
    return mapping


def clean_bq_name(col: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]", "_", str(col).strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"c_{name}"
    return name


# ============================================================
# LOAD + TRANSFORM
# ============================================================

def main():
    print("=" * 79)
    print("VISIT PLAN TRACKER - BIGQUERY UPLOAD PIPELINE")
    print("=" * 79)

    print("\n[1/5] Membaca Visit Plan Report...")
    sheets = pd.read_excel(_ARGS.visitplan, sheet_name=None)
    # the data sheet is whichever worksheet holds the most rows
    sheet_name, df = max(sheets.items(), key=lambda kv: len(kv[1]))
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").reset_index(drop=True)
    print(f"Worksheet terpilih : {sheet_name}")
    print(f"Rows               : {len(df):,}")
    print(f"Kolom              : {list(df.columns)}")

    print("\n[2/5] Deteksi kolom secara dinamis...")
    mapping = detect_columns(df)
    for role, col in mapping.items():
        print(f"  {role:<12} <- {col}")
    if not mapping:
        print("  (tidak ada kolom yang terdeteksi — data diupload apa adanya)")

    print("\n[3/5] Normalisasi data...")
    out = df.copy()
    if "visit_date" in mapping:
        out["visit_date"] = pd.to_datetime(out[mapping["visit_date"]], errors="coerce", dayfirst=True)
    for role in ("salesman", "customer", "branch", "status", "purpose"):
        if role in mapping:
            out[role] = df[mapping[role]].astype(str).str.strip().replace({"nan": "", "None": ""})
    # keep every original column too, with BigQuery-safe names
    out.columns = [clean_bq_name(c) for c in out.columns]
    out = out.loc[:, ~out.columns.duplicated()]
    print(f"Rows setelah normalisasi: {len(out):,}")

    print("\n[4/5] Ringkasan tracker...")
    group_cols = [c for c in ("salesman", "visit_date", "branch") if c in out.columns]
    if group_cols:
        summary = out.groupby(group_cols, dropna=False).size().reset_index(name="planned_visits")
        if "status" in out.columns:
            status_counts = (
                out.assign(status=out["status"].replace("", "Unknown"))
                .groupby(group_cols + ["status"], dropna=False)
                .size()
                .reset_index(name="visits")
            )
            print("\nDistribusi status kunjungan:")
            print(out["status"].replace("", "Unknown").value_counts().to_string())
        else:
            status_counts = None
        print(f"\nBaris ringkasan: {len(summary):,}")
    else:
        summary, status_counts = None, None
        print("Kolom salesman/tanggal tidak terdeteksi — ringkasan dilewati.")

    print("\n[5/5] Upload ke BigQuery...")
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION, credentials=BQ_CREDENTIALS)
    try:
        client.get_dataset(f"{PROJECT_ID}.{DATASET_ID}")
    except Exception:
        ds = bigquery.Dataset(f"{PROJECT_ID}.{DATASET_ID}")
        ds.location = LOCATION
        client.create_dataset(ds)
        print(f"[OK] Dataset dibuat: {PROJECT_ID}.{DATASET_ID}")

    def upload(frame: pd.DataFrame, table: str):
        table_id = f"{PROJECT_ID}.{DATASET_ID}.{table}"
        job = client.load_table_from_dataframe(
            frame,
            table_id,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        )
        job.result()
        print(f"[OK] Uploaded: {table_id} ({len(frame):,} rows)")

    upload(out, TABLE_TRACKER)
    if summary is not None:
        upload(summary, TABLE_TRACKER_SUMMARY)
    if status_counts is not None:
        upload(status_counts, f"{TABLE_TRACKER_SUMMARY}_by_status")

    print("\n" + "=" * 79)
    print("DONE")
    print("=" * 79)
    print(f"Main table: {PROJECT_ID}.{DATASET_ID}.{TABLE_TRACKER}")


if __name__ == "__main__":
    main()
