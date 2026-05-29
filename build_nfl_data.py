#!/usr/bin/env python3
"""
StatStack — NFL data builder
Pulls all-time career leaders from the ESPN Core API (full history, not
just 1999+) and produces ranked JSON files for the top 1,000 players.

Categories (all all-time, no era cutoff):
    nfl_pass_yds.json   Career Passing Yards
    nfl_pass_td.json    Career Passing TDs
    nfl_rush_yds.json   Career Rushing Yards
    nfl_rush_td.json    Career Rushing TDs
    nfl_receptions.json Career Receptions
    nfl_rec_yds.json    Career Receiving Yards
    nfl_rec_td.json     Career Receiving TDs
    nfl_sacks.json      Career Sacks
    nfl_def_int.json    Career Defensive INTs

Usage:
    pip install pandas requests
    python build_nfl_data.py
"""

import os
import json
import sys
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

OUT_DIR  = "data"
TOP_N    = 1000
ESPN_BASE = "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "StatStack-DataBuilder/1.0"})


# ---------------------------------------------------------------------------
# ESPN helpers
# ---------------------------------------------------------------------------

def espn_get(url: str, params: dict | None = None, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 ** attempt)
    return {}


def athlete_id_from_ref(ref: str) -> str:
    """Extract numeric ID from a $ref URL like .../athletes/12?..."""
    m = re.search(r'/athletes/(\d+)', ref)
    return m.group(1) if m else ""


def fetch_athlete_name(athlete_id: str) -> tuple[str, str]:
    """Return (athlete_id, display_name). Returns empty string on failure."""
    try:
        data = espn_get(f"{ESPN_BASE}/athletes/{athlete_id}")
        return athlete_id, data.get("displayName", "")
    except Exception:
        return athlete_id, ""


def resolve_names(athlete_ids: list[str], workers: int = 30) -> dict[str, str]:
    """Batch-resolve athlete IDs → display names using a thread pool."""
    names: dict[str, str] = {}
    total = len(athlete_ids)
    print(f"  Resolving {total:,} athlete names ", end="", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_athlete_name, aid): aid for aid in athlete_ids}
        done = 0
        for fut in as_completed(futures):
            aid, name = fut.result()
            if name:
                names[aid] = name
            done += 1
            if done % 100 == 0:
                print(".", end="", flush=True)
    print(f" done ({len(names):,} resolved)")
    return names


# ---------------------------------------------------------------------------
# Fetch all-time leaders from ESPN
# ---------------------------------------------------------------------------

def fetch_espn_leaders(category_name: str, limit: int = TOP_N) -> list[dict]:
    """
    Pull career leaders for a named category from ESPN's all-time leaders
    endpoint. Returns list of {athlete_id, value} dicts.
    """
    data = espn_get(
        f"{ESPN_BASE}/leaders/0",
        params={"lang": "en", "region": "us", "limit": limit},
    )
    cats = data.get("categories", [])
    cat = next((c for c in cats if c["name"] == category_name), None)
    if cat is None:
        raise KeyError(f"Category '{category_name}' not found in ESPN leaders")
    leaders = []
    for entry in cat.get("leaders", []):
        ref = entry.get("athlete", {}).get("$ref", "")
        aid = athlete_id_from_ref(ref)
        val = entry.get("value", 0)
        if aid and val > 0:
            leaders.append({"athlete_id": aid, "value": val})
    return leaders


# ---------------------------------------------------------------------------
# Receiving yards/TDs — fetch from per-athlete career stats
# (not in ESPN's leaders endpoint, so we derive from the receptions leaders)
# ---------------------------------------------------------------------------

def fetch_receiving_stats(athlete_id: str) -> dict:
    """Return receiving yards and TDs for one athlete."""
    try:
        data = espn_get(f"{ESPN_BASE}/athletes/{athlete_id}/statistics/0")
        cats = data.get("splits", {}).get("categories", [])
        rec_cat = next((c for c in cats if c["name"] == "receiving"), None)
        if not rec_cat:
            return {"yards": 0, "tds": 0}
        stats = {s["name"]: s.get("value", 0) for s in rec_cat.get("stats", [])}
        return {
            "yards": int(stats.get("receivingYards", 0)),
            "tds":   int(stats.get("receivingTouchdowns", 0)),
        }
    except Exception:
        return {"yards": 0, "tds": 0}


def build_receiving_leaders(receptions_leaders: list[dict], names: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """
    For the top receptions leaders (which captures all high receiving-yards
    players), fetch per-athlete career receiving yards + TDs concurrently.
    """
    ids = [l["athlete_id"] for l in receptions_leaders]
    rec_stats: dict[str, dict] = {}
    print(f"  Fetching receiving stats for {len(ids):,} athletes ", end="", flush=True)
    with ThreadPoolExecutor(max_workers=25) as pool:
        futures = {pool.submit(fetch_receiving_stats, aid): aid for aid in ids}
        done = 0
        for fut in as_completed(futures):
            aid = futures[fut]
            rec_stats[aid] = fut.result()
            done += 1
            if done % 100 == 0:
                print(".", end="", flush=True)
    print(" done")

    # Build receiving yards leaders
    yds_rows = []
    for l in receptions_leaders:
        aid  = l["athlete_id"]
        name = names.get(aid, "")
        yds  = rec_stats.get(aid, {}).get("yards", 0)
        if name and yds > 0:
            yds_rows.append({"name": name, "value": yds})

    # Build receiving TD leaders
    td_rows = []
    for l in receptions_leaders:
        aid  = l["athlete_id"]
        name = names.get(aid, "")
        tds  = rec_stats.get(aid, {}).get("tds", 0)
        if name and tds > 0:
            td_rows.append({"name": name, "value": tds})

    return rank_rows(yds_rows), rank_rows(td_rows)


def rank_rows(rows: list[dict], top_n: int = TOP_N) -> list[dict]:
    rows = sorted(rows, key=lambda r: r["value"], reverse=True)[:top_n]
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_json(records: list[dict], filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, separators=(",", ":"))
    top = records[0]
    print(f"  → {filepath}  ({len(records)} players  |  #1: {top['name']} {top['value']:,})")


def leaders_to_records(leaders: list[dict], names: dict[str, str]) -> list[dict]:
    rows = []
    for l in leaders:
        name = names.get(l["athlete_id"], "")
        if name:
            rows.append({"name": name, "value": int(l["value"])})
    return rank_rows(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Fetching ESPN all-time NFL career leaders...")

    # ── Step 1: fetch ESPN all-time leader lists (offense + sacks) ─────────────
    # NOTE: ESPN defensive INT data is incomplete (missing pre-1999 players),
    # so we source that separately from nflverse which is accurate for 1999+.
    categories = {
        "passingYards":      "nfl_pass_yds.json",
        "passingTouchdowns": "nfl_pass_td.json",
        "rushingYards":      "nfl_rush_yds.json",
        "rushingTouchdowns": "nfl_rush_td.json",
        "receptions":        "nfl_receptions.json",
        "sacks":             "nfl_sacks.json",
    }

    leader_data: dict[str, list[dict]] = {}
    for cat_name in categories:
        print(f"  {cat_name} ...", end=" ", flush=True)
        leader_data[cat_name] = fetch_espn_leaders(cat_name)
        print(f"{len(leader_data[cat_name])} leaders")

    # Also fetch receptions leaders at full limit for receiving yards/TDs
    print("  receptions (for rec yards/TDs) ...", end=" ", flush=True)
    rec_leaders = fetch_espn_leaders("receptions", limit=TOP_N)
    print(f"{len(rec_leaders)} leaders")

    # ── Step 2: resolve all unique athlete names ─────────────────────────────
    all_ids = set()
    for leaders in leader_data.values():
        for l in leaders:
            all_ids.add(l["athlete_id"])
    for l in rec_leaders:
        all_ids.add(l["athlete_id"])

    names = resolve_names(list(all_ids))

    # ── Step 3: build and save the 6 ESPN leader JSONs ──────────────────────
    print("\nBuilding and saving ESPN leader files...")
    for cat_name, filename in categories.items():
        records = leaders_to_records(leader_data[cat_name], names)
        save_json(records, f"{OUT_DIR}/{filename}")

    # ── Step 4: build receiving yards + TDs from per-athlete stats ───────────
    print("\nBuilding receiving yards and TDs (fetching per-athlete stats)...")
    rec_yds_records, rec_td_records = build_receiving_leaders(rec_leaders, names)
    save_json(rec_yds_records, f"{OUT_DIR}/nfl_rec_yds.json")
    save_json(rec_td_records,  f"{OUT_DIR}/nfl_rec_td.json")

    # ── Step 5: defensive INTs from nflverse (1999–present, accurate) ────────
    print("\nBuilding defensive INTs from nflverse (1999+)...")
    import pandas as pd
    NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/"
    frames = []
    for year in range(1999, 2025):
        url = NFLVERSE_BASE + f"player_stats_def_season_{year}.csv"
        try:
            df = pd.read_csv(url, low_memory=False)
            df = df[df["season_type"] == "REG"]
            frames.append(df)
            print(".", end="", flush=True)
        except Exception:
            pass
    print()
    defense = pd.concat(frames, ignore_index=True)
    totals = (
        defense.groupby("player_display_name")["def_interceptions"]
        .sum()
        .reset_index()
        .rename(columns={"def_interceptions": "value", "player_display_name": "name"})
    )
    totals = totals[totals["value"] >= 1].sort_values("value", ascending=False).head(TOP_N).reset_index(drop=True)
    totals["rank"] = totals.index + 1
    totals["value"] = totals["value"].astype(int)
    def_int_records = totals[["rank", "name", "value"]].to_dict("records")
    save_json(def_int_records, f"{OUT_DIR}/nfl_def_int.json")

    print(f"\nDone. Nine NFL JSON files written to ./{OUT_DIR}/")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
