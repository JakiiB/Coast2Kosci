import csv
import io
import json
import math
import re
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_scrape"
TRACKING_DIR = RAW_DIR / "tracking"


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def check_recent_posts():
    posts = json.loads((RAW_DIR / "wp_posts.json").read_text(encoding="utf-8"))
    posts_sorted = sorted(posts, key=lambda x: x.get("date", ""), reverse=True)
    lines = []
    for p in posts_sorted[:60]:
        lines.append(f"{p.get('date','')[:10]} | {p.get('title',{}).get('rendered','')} | {p.get('link','')}")
    (RAW_DIR / "recent_posts_titles.txt").write_text("\n".join(lines), encoding="utf-8")
    print("Recent posts sample (top 15):")
    for l in lines[:15]:
        print(" ", l)


def check_tml_route():
    app_js = (TRACKING_DIR / "app_1.1.118.js").read_text(encoding="utf-8")
    # Search for Url.make calls and route loading
    refs = set(re.findall(r"Url\.make\([^)]+\)", app_js))
    print("TrackMeLive Url.make calls:", sorted(refs))
    # Search for kml/gpx/route
    route_refs = set(re.findall(r"[^\s;{}()]{0,40}(?:kml|route|routes|overlay)[^\s;{}()]{0,40}", app_js, re.I))
    (TRACKING_DIR / "tml_route_refs.txt").write_text("\n".join(sorted(route_refs)), encoding="utf-8")


def fetch_national_toilet_map():
    headers = {"User-Agent": "CoastToKosciLogisticsDB/1.0"}
    pkg = requests.get(
        "https://data.gov.au/data/api/3/action/package_show?id=national-public-toilet-map",
        headers=headers,
        timeout=20,
    ).json()
    resources = pkg["result"]["resources"]
    print("Toilet Map resources:")
    csv_url = None
    for res in resources:
        fmt = (res.get("format") or "").upper()
        name = res.get("name") or ""
        url = res.get("url") or ""
        print(f"  [{fmt}] {name} -> {url}")
        if fmt == "CSV" or url.lower().endswith(".csv"):
            csv_url = url
            break
    if not csv_url:
        print("No CSV resource found!")
        return

    print(f"Downloading National Public Toilet Map CSV from {csv_url}...")
    resp = requests.get(csv_url, headers=headers, timeout=45)
    resp.raise_for_status()
    csv_path = RAW_DIR / "national_public_toilet_map.csv"
    csv_path.write_bytes(resp.content)
    print(f"Downloaded {len(resp.content)} bytes")

    # Load RWGPS route track_points (subsample every 3rd point to ~4000 pts for rapid matching, then refine)
    rw = json.loads((RAW_DIR / "rwgps_41169431.json").read_text(encoding="utf-8"))
    pts = rw["track_points"]
    coarse = pts[::4]

    matched = []
    text_stream = io.StringIO(resp.content.decode("utf-8-sig", errors="replace"))
    reader = csv.DictReader(text_stream)
    print("Toilet CSV columns:", reader.fieldnames)

    for row in reader:
        state = (row.get("State") or "").strip().upper()
        if state != "NSW":
            continue
        try:
            lat = float(row.get("Latitude") or row.get("latitude"))
            lon = float(row.get("Longitude") or row.get("longitude"))
        except (TypeError, ValueError):
            continue
        # Quick bounding box filter for C2K corridor (-37.18..-36.28, 148.18..149.95)
        if not (-37.18 <= lat <= -36.28 and 148.18 <= lon <= 149.95):
            continue

        # Find nearest point on track
        best_c_idx = 0
        best_c_d = 1e12
        for idx, tp in enumerate(coarse):
            d = (tp["y"] - lat) ** 2 + (tp["x"] - lon) ** 2
            if d < best_c_d:
                best_c_d = d
                best_c_idx = idx
        # Refine around best_c_idx * 4
        center = best_c_idx * 4
        lo = max(0, center - 20)
        hi = min(len(pts), center + 20)
        best_dist_m = 1e12
        best_tp = None
        for tp in pts[lo:hi]:
            dm = haversine_m(lat, lon, tp["y"], tp["x"])
            if dm < best_dist_m:
                best_dist_m = dm
                best_tp = tp

        if best_dist_m <= 3000:
            row_clean = dict(row)
            row_clean["_nearest_course_km"] = round(best_tp["d"] / 1000.0, 2)
            row_clean["_off_course_m"] = round(best_dist_m, 0)
            row_clean["_elev_m"] = round(best_tp.get("e", 0), 1)
            matched.append(row_clean)

    matched.sort(key=lambda r: r["_nearest_course_km"])
    (RAW_DIR / "c2k_corridor_toilets_gov.json").write_text(json.dumps(matched, indent=2), encoding="utf-8")
    print(f"Matched {len(matched)} National Public Toilet Map stops within 3 km of C2K route!")
    for m in matched:
        print(
            f"  km {m['_nearest_course_km']:6.2f} (off {m['_off_course_m']:4.0f}m) | "
            f"{m.get('Name')} ({m.get('Town')}) | {m.get('FacilityType')} | "
            f"Hours: {m.get('OpeningHours')} | Water: {m.get('DrinkingWater')} | Shower: {m.get('Shower')}"
        )


if __name__ == "__main__":
    check_recent_posts()
    check_tml_route()
    fetch_national_toilet_map()
