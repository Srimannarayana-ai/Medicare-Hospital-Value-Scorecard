"""
Medicare Hospital Value Scorecard - data build script

Reads the CMS hospital CSVs from 01_raw, cleans and joins them on Facility ID,
then writes the hospital table, state averages, focus list, and the Excel file
used by the Power BI report.

Run from the project root:
    python scripts/build_scorecard.py
"""

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "01_raw"
CLEAN = ROOT / "02_clean"
OUT = ROOT / "03_outputs"
PBI_DATA = OUT / "PowerBI" / "Scorecard_Data.xlsx"

# CMS uses a few different "missing" labels
MISSING = {
    "Not Available",
    "N/A",
    "NA",
    "Not Applicable",
    "-",
    "",
    "nan",
    "None",
}


def to_num(series: pd.Series) -> pd.Series:
    """Turn a text column into numbers; treat CMS blanks as missing."""
    s = series.astype(str).str.strip()
    s = s.replace({m: np.nan for m in MISSING})
    return pd.to_numeric(s, errors="coerce")


def clean_id(series: pd.Series) -> pd.Series:
    """Standardize Facility ID so the joins line up across files."""
    s = series.astype(str).str.strip()
    s = s.replace({m: np.nan for m in MISSING})
    # Excel sometimes turns IDs into floats like 10001.0
    s = s.str.replace(r"\.0$", "", regex=True)
    return s


def period_from(df: pd.DataFrame) -> tuple[str, str]:
    """Grab Start/End Date from the first usable row (for documentation)."""
    start = end = ""
    if "Start Date" in df.columns:
        vals = df["Start Date"].dropna().astype(str).str.strip()
        vals = vals[~vals.isin(MISSING)]
        if len(vals):
            start = vals.iloc[0]
    if "End Date" in df.columns:
        vals = df["End Date"].dropna().astype(str).str.strip()
        vals = vals[~vals.isin(MISSING)]
        if len(vals):
            end = vals.iloc[0]
    return start, end


def load_general() -> pd.DataFrame:
    df = pd.read_csv(RAW / "Hospital_General_Information.csv", dtype=str, low_memory=False)
    df["Facility ID"] = clean_id(df["Facility ID"])
    keep = [
        "Facility ID",
        "Facility Name",
        "Address",
        "City/Town",
        "State",
        "ZIP Code",
        "County/Parish",
        "Hospital Type",
        "Hospital Ownership",
        "Emergency Services",
        "Hospital overall rating",
    ]
    df = df[keep].copy()
    df["Hospital overall rating"] = to_num(df["Hospital overall rating"])
    return df.dropna(subset=["Facility ID"]).drop_duplicates("Facility ID")


def load_mspb() -> tuple[pd.DataFrame, str, str]:
    # CMS file ships with a blank header on the first column (Facility ID)
    path = RAW / "Medicare_Hospital_Spending_Per_Patient-Hospital.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    cols = list(df.columns)
    if cols[0] is None or str(cols[0]).strip() == "" or str(cols[0]).startswith("Unnamed"):
        cols[0] = "Facility ID"
        df.columns = cols

    df["Facility ID"] = clean_id(df["Facility ID"])
    if "Measure ID" in df.columns:
        df = df[df["Measure ID"].astype(str).str.strip() == "MSPB-1"].copy()

    start, end = period_from(df)
    out = pd.DataFrame(
        {
            "Facility ID": df["Facility ID"],
            "MSPB": to_num(df["Score"]),
        }
    )
    out = out.dropna(subset=["Facility ID"]).groupby("Facility ID", as_index=False)["MSPB"].mean()
    return out, start, end


def load_hcahps() -> tuple[pd.DataFrame, str, str]:
    # File is large - only pull the columns / measures we need
    usecols = [
        "Facility ID",
        "HCAHPS Measure ID",
        "Patient Survey Star Rating",
        "Number of Completed Surveys",
        "Start Date",
        "End Date",
    ]
    df = pd.read_csv(RAW / "HCAHPS-Hospital.csv", dtype=str, usecols=usecols, low_memory=False)
    df["Facility ID"] = clean_id(df["Facility ID"])
    df = df[
        df["HCAHPS Measure ID"].isin(["H_HSP_RATING_STAR_RATING", "H_RECMND_STAR_RATING"])
    ].copy()

    start, end = period_from(df)
    df["star"] = to_num(df["Patient Survey Star Rating"])
    df["surveys"] = to_num(df["Number of Completed Surveys"])

    overall = df.loc[
        df["HCAHPS Measure ID"] == "H_HSP_RATING_STAR_RATING",
        ["Facility ID", "star", "surveys"],
    ].rename(columns={"star": "Experience_Star", "surveys": "Completed_Surveys"})

    recommend = df.loc[
        df["HCAHPS Measure ID"] == "H_RECMND_STAR_RATING",
        ["Facility ID", "star"],
    ].rename(columns={"star": "Recommend_Star"})

    out = overall.merge(recommend, on="Facility ID", how="outer")
    # Use recommend star only when overall hospital rating is missing
    out["Experience_Star"] = out["Experience_Star"].fillna(out["Recommend_Star"])
    return out.dropna(subset=["Facility ID"]).drop_duplicates("Facility ID"), start, end


def load_readmission() -> tuple[pd.DataFrame, str, str]:
    usecols = [
        "Facility ID",
        "Measure ID",
        "Score",
        "Compared to National",
        "Start Date",
        "End Date",
    ]
    df = pd.read_csv(
        RAW / "Unplanned_Hospital_Visits-Hospital.csv",
        dtype=str,
        usecols=usecols,
        low_memory=False,
    )
    df["Facility ID"] = clean_id(df["Facility ID"])
    df = df[df["Measure ID"].astype(str).str.strip() == "Hybrid_HWR"].copy()
    start, end = period_from(df)

    out = pd.DataFrame(
        {
            "Facility ID": df["Facility ID"],
            "Readmission_Rate": to_num(df["Score"]),
            "Readmission_vs_National": df["Compared to National"].astype(str).str.strip(),
        }
    )
    out.loc[out["Readmission_vs_National"].isin(MISSING), "Readmission_vs_National"] = np.nan
    out = out.dropna(subset=["Facility ID"]).groupby("Facility ID", as_index=False).agg(
        Readmission_Rate=("Readmission_Rate", "mean"),
        Readmission_vs_National=("Readmission_vs_National", "first"),
    )
    return out, start, end


def load_hai() -> tuple[pd.DataFrame, str, str]:
    usecols = ["Facility ID", "Measure ID", "Score", "Start Date", "End Date"]
    df = pd.read_csv(
        RAW / "Healthcare_Associated_Infections-Hospital.csv",
        dtype=str,
        usecols=usecols,
        low_memory=False,
    )
    df["Facility ID"] = clean_id(df["Facility ID"])

    # Only SIRs (skip confidence intervals / numerator rows)
    sir_ids = [f"HAI_{i}_SIR" for i in range(1, 7)]
    df = df[df["Measure ID"].isin(sir_ids)].copy()
    start, end = period_from(df)
    df["Score"] = to_num(df["Score"])

    pivot = df.pivot_table(
        index="Facility ID", columns="Measure ID", values="Score", aggfunc="mean"
    )
    for m in sir_ids:
        if m not in pivot.columns:
            pivot[m] = np.nan
    pivot = pivot[sir_ids].reset_index()
    pivot["HAI_SIR_Avg"] = pivot[sir_ids].mean(axis=1, skipna=True)
    pivot["HAI_SIR_Count"] = pivot[sir_ids].notna().sum(axis=1)
    return pivot[["Facility ID", "HAI_SIR_Avg", "HAI_SIR_Count"]], start, end


def scale_lower_is_better(s: pd.Series) -> pd.Series:
    """Flip and stretch a metric so higher = better (0-100)."""
    mn, mx = s.min(skipna=True), s.max(skipna=True)
    if pd.isna(mn) or pd.isna(mx) or mx == mn:
        return pd.Series(np.nan, index=s.index)
    return (mx - s) / (mx - mn) * 100.0


def census_region(state: str) -> str:
    regions = {
        "Northeast": {"CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"},
        "Midwest": {
            "IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD",
        },
        "South": {
            "DE", "FL", "GA", "MD", "NC", "SC", "VA", "DC", "WV",
            "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX",
        },
        "West": {
            "AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY",
            "AK", "CA", "HI", "OR", "WA",
        },
        "Territory": {"AS", "GU", "MP", "PR", "VI"},
    }
    for name, members in regions.items():
        if state in members:
            return name
    return "Other"


def build_master() -> tuple[pd.DataFrame, dict]:
    hospitals = load_general()
    mspb, mspb_s, mspb_e = load_mspb()
    hcahps, hc_s, hc_e = load_hcahps()
    readm, rd_s, rd_e = load_readmission()
    hai, hai_s, hai_e = load_hai()

    df = (
        hospitals.merge(mspb, on="Facility ID", how="left")
        .merge(hcahps, on="Facility ID", how="left")
        .merge(readm, on="Facility ID", how="left")
        .merge(hai, on="Facility ID", how="left")
    )

    df["Region"] = df["State"].map(
        lambda x: census_region(str(x).strip() if pd.notna(x) else "")
    )
    # Hospital Type stands in for size (Acute Care vs Critical Access, etc.)
    df["Size_Proxy"] = df["Hospital Type"]

    # Build a simple quality score (0-100), then value = quality / MSPB
    df["Exp_n"] = (df["Experience_Star"] / 5.0) * 100.0
    df["Read_n"] = scale_lower_is_better(df["Readmission_Rate"])
    df["HAI_n"] = scale_lower_is_better(df["HAI_SIR_Avg"])

    parts = df[["Exp_n", "Read_n", "HAI_n"]]
    df["Quality"] = parts.mean(axis=1, skipna=True)
    df["Quality_Components"] = parts.notna().sum(axis=1)

    df["Value_Score"] = np.where(
        (df["MSPB"].notna()) & (df["MSPB"] > 0) & (df["Quality"].notna()),
        df["Quality"] / df["MSPB"],
        np.nan,
    )

    # Who should a payer look at first?
    high_spend_low_exp = df["Experience_Star"].le(2) & df["MSPB"].gt(1.10)
    bottom_value = df["Value_Score"].notna() & (
        df["Value_Score"] <= df["Value_Score"].quantile(0.20)
    )
    df["Focus_Flag"] = np.where(
        high_spend_low_exp,
        "High spend / low experience",
        np.where(bottom_value, "Low value (bottom 20%)", "Ok / review later"),
    )

    meta = {
        "mspb_period": f"{mspb_s} to {mspb_e}",
        "hcahps_period": f"{hc_s} to {hc_e}",
        "readm_period": f"{rd_s} to {rd_e}",
        "hai_period": f"{hai_s} to {hai_e}",
        "hospital_count": int(df["Facility ID"].nunique()),
        "value_count": int(df["Value_Score"].notna().sum()),
        "focus_count": int((df["Focus_Flag"] != "Ok / review later").sum()),
    }
    return df, meta


def state_benchmarks(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby("State", dropna=True)
        .agg(
            Hospitals=("Facility ID", "count"),
            Avg_Experience=("Experience_Star", "mean"),
            Avg_Readmission=("Readmission_Rate", "mean"),
            Avg_HAI_SIR=("HAI_SIR_Avg", "mean"),
            Avg_MSPB=("MSPB", "mean"),
            Avg_Quality=("Quality", "mean"),
            Avg_Value=("Value_Score", "mean"),
        )
        .reset_index()
        .sort_values("Avg_Value", ascending=False)
    )
    for c in g.columns:
        if c not in {"State", "Hospitals"}:
            g[c] = g[c].round(3)
    return g


def focus_list(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "Facility ID",
        "Facility Name",
        "State",
        "Region",
        "Hospital Ownership",
        "Hospital Type",
        "Experience_Star",
        "Readmission_Rate",
        "HAI_SIR_Avg",
        "MSPB",
        "Quality",
        "Value_Score",
        "Focus_Flag",
    ]
    out = df.loc[df["Focus_Flag"] != "Ok / review later", cols].copy()
    return out.sort_values(["Focus_Flag", "Value_Score"], ascending=[True, True])


def write_powerbi_excel(df: pd.DataFrame, focus: pd.DataFrame, state: pd.DataFrame) -> None:
    """Slim workbook the .pbix file reads from (keep this path stable)."""
    PBI_DATA.parent.mkdir(parents=True, exist_ok=True)
    hv_cols = [
        "Facility ID",
        "Facility Name",
        "State",
        "Region",
        "Hospital Ownership",
        "Hospital Type",
        "Experience_Star",
        "Readmission_Rate",
        "HAI_SIR_Avg",
        "MSPB",
        "Quality",
        "Value_Score",
        "Focus_Flag",
        "City/Town",
        "ZIP Code",
    ]
    focus_cols = [
        "Facility ID",
        "Facility Name",
        "State",
        "Region",
        "Hospital Ownership",
        "Hospital Type",
        "Experience_Star",
        "Readmission_Rate",
        "HAI_SIR_Avg",
        "MSPB",
        "Quality",
        "Value_Score",
        "Focus_Flag",
    ]
    with pd.ExcelWriter(PBI_DATA, engine="openpyxl") as writer:
        df[hv_cols].to_excel(writer, sheet_name="hospital_value", index=False)
        focus[focus_cols].to_excel(writer, sheet_name="focus_list", index=False)
        state.to_excel(writer, sheet_name="state_benchmarks", index=False)


def main() -> None:
    CLEAN.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    print("Loading CMS files and building hospital table...")
    df, meta = build_master()
    state = state_benchmarks(df)
    focus = focus_list(df)

    df.to_csv(CLEAN / "hospital_value_master.csv", index=False)
    with pd.ExcelWriter(CLEAN / "Hospital_Value_Master.xlsx", engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="hospital_value", index=False)
        state.to_excel(writer, sheet_name="state_benchmarks", index=False)
        focus.to_excel(writer, sheet_name="focus_list", index=False)

    state.to_csv(OUT / "state_benchmarks.csv", index=False)
    focus.to_csv(OUT / "focus_hospitals.csv", index=False)
    write_powerbi_excel(df, focus, state)

    print("Done.")
    print(f"Hospitals in roster : {meta['hospital_count']}")
    print(f"With value score    : {meta['value_count']}")
    print(f"On focus list       : {meta['focus_count']}")
    print(f"MSPB period         : {meta['mspb_period']}")
    print(f"Clean table         : {CLEAN / 'Hospital_Value_Master.xlsx'}")
    print(f"Power BI data       : {PBI_DATA}")


if __name__ == "__main__":
    main()
