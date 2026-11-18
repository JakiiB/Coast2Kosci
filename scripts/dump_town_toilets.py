import csv
import json
import math
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_scrape"

rw = json.loads((RAW_DIR / "rwgps_41169431.json").read_text(encoding="utf-8"))
pts = rw["track_points"]

def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

town_keywords = (
    "boydtown", "eden", "towamba", "rocky hall", "wyndham", "cathcart",
    "bibbenluke", "bombala", "dalgety", "berridale", "jindabyne",
    "perisher", "smiggin", "charlotte", "munyang", "kosciuszko", "sawpit"
)

out = []
with open(RAW_DIR / "national_public_toilet_map.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if (row.get("State") or "").strip().upper() != "NSW":
            continue
        town = (row.get("Town") or "").strip().lower()
        name = (row.get("Name") or "").strip().lower()
        addr = (row.get("Address1") or "").strip().lower()
        if any(k in town or k in name or k in addr for k in town_keywords):
            lat = float(row["Latitude"])
            lon = float(row["Longitude"])
            best_d = 1e12
            best_tp = None
            for tp in pts[::3]:
                dm = haversine_m(lat, lon, tp["y"], tp["x"])
                if dm < best_d:
                    best_d = dm
                    best_tp = tp
            out.append({
                "km": round(best_tp["d"] / 1000.0, 2) if best_tp else None,
                "off_m": round(best_d, 0),
                "town": row["Town"],
                "name": row["Name"],
                "type": row["FacilityType"],
                "address": row["Address1"],
                "address_note": row["AddressNote"],
                "hours": row["OpeningHours"],
                "hours_note": row["OpeningHoursNote"],
                "water": row["DrinkingWater"],
                "shower": row["Shower"],
                "accessible": row["Accessible"],
                "toilet_note": row["ToiletNote"],
                "url": row["URL"],
                "lat": lat,
                "lon": lon,
            })

out.sort(key=lambda r: (r["km"] or 999, r["off_m"]))
(RAW_DIR / "corridor_towns_toilets_detailed.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
for r in out:
    print(f"km {r['km']:6.2f} (off {r['off_m']:5.0f}m) | {r['town']} - {r['name']} [{r['type']}] | {r['hours']} ({r['hours_note']}) | Water:{r['water']} Shower:{r['shower']} Access:{r['accessible']}")
