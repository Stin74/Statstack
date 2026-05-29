#!/usr/bin/env python3
"""
StatStack — NFL data builder
Pulls pre-aggregated season stats from nflverse-data (GitHub releases) and
produces eight ranked JSON files — one per stat category — each with the
top 1,000 all-time career leaders (1999–present).

Usage:
    pip install pandas requests
    python build_nfl_data.py

Outputs (written to ./data/):
    nfl_pass_yds.json     Career Passing Yards   (QBs)
    nfl_pass_td.json      Career Passing TDs     (QBs)
    nfl_pass_int.json     Career Interceptions Thrown (QBs — lower is notable)
    nfl_rush_yds.json     Career Rushing Yards
    nfl_rush_td.json      Career Rushing TDs
    nfl_rec_yds.json      Career Receiving Yards
    nfl_rec_td.json       Career Receiving TDs
    nfl_sacks.json        Career Sacks           (defense)
    nfl_def_int.json      Career Defensive INTs  (defense)

Run nightly alongside build_data.py to keep rankings current.
"""

import os
import json
import sys
import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/"
OUT_DIR = "data"
TOP_N = 1000
YEARS = range(1999, 2025)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_season_csvs(pattern: str) -> pd.DataFrame:
    """Download and concatenate per-season CSVs matching the URL pattern."""
    frames = []
    for year in YEARS:
        url = BASE + pattern.format(year=year)
        try:
            df = pd.read_csv(url, low_memory=False)
            # Keep only regular season
            if "season_type" in df.columns:
                df = df[df["season_type"] == "REG"]
            frames.append(df)
            print(".", end="", flush=True)
        except Exception:
            pass  # year not available — skip silently
    print()
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def career_leaders(
    df: pd.DataFrame,
    stat_col: str,
    name_col: str = "player_display_name",
    top_n: int = TOP_N,
    min_value: int = 1,
    position_filter: list[str] | None = None,
) -> list[dict]:
    """Aggregate career totals, sort descending, return top_n dicts."""
    if stat_col not in df.columns:
        raise KeyError(f"Column '{stat_col}' not found")

    sub = df.copy()
    if position_filter:
        sub = sub[sub["position_group"].isin(position_filter)]

    totals = (
        sub.groupby("player_display_name")[stat_col]
        .sum()
        .reset_index()
        .rename(columns={stat_col: "value", "player_display_name": "name"})
    )
    totals = totals[totals["value"] >= min_value]
    totals = (
        totals.sort_values("value", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    totals["rank"] = totals.index + 1
    totals["value"] = totals["value"].round().astype(int)
    return totals[["rank", "name", "value"]].to_dict("records")


def save_json(records: list[dict], filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, separators=(",", ":"))
    top = records[0]
    print(f"  → {filepath}  ({len(records)} players  |  #1: {top['name']} {top['value']:,})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Downloading NFL offensive season stats (1999–2024)...")
    offense = load_season_csvs("player_stats_season_{year}.csv")
    print(f"  {len(offense):,} player-seasons loaded")

    print("Downloading NFL defensive season stats (1999–2024)...")
    defense = load_season_csvs("player_stats_def_season_{year}.csv")
    print(f"  {len(defense):,} player-seasons loaded")

    print("\nBuilding passing leaders...")
    save_json(career_leaders(offense, "passing_yards",  position_filter=["QB"]),
              f"{OUT_DIR}/nfl_pass_yds.json")
    save_json(career_leaders(offense, "passing_tds",    position_filter=["QB"]),
              f"{OUT_DIR}/nfl_pass_td.json")
    save_json(career_leaders(offense, "interceptions",  position_filter=["QB"], min_value=1),
              f"{OUT_DIR}/nfl_pass_int.json")

    print("\nBuilding rushing leaders...")
    save_json(career_leaders(offense, "rushing_yards",  min_value=100),
              f"{OUT_DIR}/nfl_rush_yds.json")
    save_json(career_leaders(offense, "rushing_tds"),
              f"{OUT_DIR}/nfl_rush_td.json")

    print("\nBuilding receiving leaders...")
    save_json(career_leaders(offense, "receiving_yards", min_value=100),
              f"{OUT_DIR}/nfl_rec_yds.json")
    save_json(career_leaders(offense, "receiving_tds"),
              f"{OUT_DIR}/nfl_rec_td.json")

    print("\nBuilding defensive leaders...")
    save_json(career_leaders(defense, "def_sacks",         min_value=1),
              f"{OUT_DIR}/nfl_sacks.json")
    save_json(career_leaders(defense, "def_interceptions", min_value=1),
              f"{OUT_DIR}/nfl_def_int.json")

    print(f"\nDone. Nine NFL JSON files written to ./{OUT_DIR}/")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
