#!/usr/bin/env python3
"""
StatStack — MLB data builder
Pulls from the Chadwick Bureau Lahman database (GitHub) and produces five ranked
JSON files — one per stat category — each with the top 1,000 all-time career leaders.

Usage:
    pip install pandas requests
    python build_data.py

Outputs (written to ./data/):
    hr.json         Career Home Runs      (batters)
    rbi.json        Career RBIs           (batters)
    hits.json       Career Hits           (batters)
    pitcher_k.json  Career Strikeouts     (pitchers)
    pitcher_w.json  Career Wins           (pitchers)

Run nightly (cron / GitHub Actions) to keep rankings current.
"""

import os
import json
import sys
import pandas as pd

LAHMAN_BASE = (
    "https://raw.githubusercontent.com/cbwinslow/baseballdatabank/master/core/"
)
OUT_DIR = "data"
TOP_N = 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_csv(filename: str) -> pd.DataFrame:
    url = LAHMAN_BASE + filename
    print(f"  Fetching {filename} ...", end=" ", flush=True)
    df = pd.read_csv(url, low_memory=False)
    print(f"{len(df):,} rows")
    return df


def build_name_map(people: pd.DataFrame) -> dict[str, str]:
    """Return playerID → 'First Last' mapping."""
    p = people.copy()
    p["nameFirst"] = p["nameFirst"].fillna("").str.strip()
    p["nameLast"] = p["nameLast"].fillna("").str.strip()
    p["full"] = (p["nameFirst"] + " " + p["nameLast"]).str.strip()
    return p.set_index("playerID")["full"].to_dict()


def career_leaders(
    df: pd.DataFrame,
    stat_col: str,
    names: dict[str, str],
    top_n: int = TOP_N,
    min_value: int = 1,
) -> list[dict]:
    """
    Aggregate career totals for stat_col, join names, sort descending,
    return top_n as a list of {"rank", "name", "value"} dicts.
    """
    totals = (
        df.groupby("playerID")[stat_col]
        .sum()
        .reset_index()
        .rename(columns={stat_col: "value"})
    )
    totals = totals[totals["value"] >= min_value].copy()
    totals["name"] = totals["playerID"].map(names)
    totals = totals.dropna(subset=["name"])
    totals = (
        totals.sort_values("value", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    totals["rank"] = totals.index + 1
    totals["value"] = totals["value"].astype(int)
    return totals[["rank", "name", "value"]].to_dict("records")


def save_json(records: list[dict], filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, separators=(",", ":"))
    top = records[0]
    print(f"  → {filepath}  ({len(records)} players  |  #1: {top['name']} {top['value']})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Downloading Lahman data from Chadwick Bureau...")
    batting  = load_csv("Batting.csv")
    pitching = load_csv("Pitching.csv")
    people   = load_csv("People.csv")

    names = build_name_map(people)

    print("\nBuilding batting leaders...")
    save_json(career_leaders(batting,  "HR",  names), f"{OUT_DIR}/hr.json")
    save_json(career_leaders(batting,  "RBI", names), f"{OUT_DIR}/rbi.json")
    save_json(career_leaders(batting,  "H",   names), f"{OUT_DIR}/hits.json")

    print("\nBuilding pitching leaders...")
    save_json(career_leaders(pitching, "SO",  names), f"{OUT_DIR}/pitcher_k.json")
    save_json(career_leaders(pitching, "W",   names), f"{OUT_DIR}/pitcher_w.json")

    print(f"\nDone. Five JSON files written to ./{OUT_DIR}/")
    print("Commit data/ and push to trigger a Cloudflare Pages deploy.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
