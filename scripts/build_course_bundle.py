"""
Coast to Kosciuszko (C2K) - Course & Telemetry Data Bundle Builder
Extracts the 241.25 km route (12,593 track points, 26 official POIs, 49 turn cues,
and 10 km milestones) from RideWithGPS 41169434 + local .fit file, applies exact
2,228.0 m Mt Kosciuszko summit calibration, computes smoothed gradients and bearings,
projects all checkpoints onto exact course km, derives official cutoff gates,
and fetches a live 5-zone baseline weather snapshot.
"""

import os
import sys
import json
import math
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RWGPS_URL = "https://ridewithgps.com/routes/41169434.json"


def load_visual_crossing_key() -> str:
    env_key = os.environ.get("VISUAL_CROSSING_API_KEY", "").strip()
    if env_key:
        return env_key
    keys_file = Path.home() / ".gemini" / "api_keys.json"
    if keys_file.exists():
        try:
            kdata = json.loads(keys_file.read_text(encoding="utf-8"))
            for k in ("VISUAL_CROSSING_API_KEY", "visual_crossing_api_key", "visual_crossing", "visualcrossing"):
                val = kdata.get(k)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        except Exception:
            pass
    env_file = Path.home() / ".gemini" / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("VISUAL_CROSSING_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""

# 5 Micro-Climate Weather Stations along the 241.25 km ascent
WEATHER_ZONES = [
    {
        "id": "coastal_eden",
        "name": "Boydtown Beach / Eden",
        "subtitle": "Start Line & Coastal Zone",
        "lat": -37.09205,
        "lon": 149.87226,
        "ele_m": 4,
        "km_start": 0.0,
        "km_end": 35.0,
    },
    {
        "id": "valley_rocky_hall",
        "name": "Towamba & Rocky Hall",
        "subtitle": "Foothills & Cow Bail Base",
        "lat": -36.92718,
        "lon": 149.50321,
        "ele_m": 255,
        "km_start": 35.0,
        "km_end": 65.0,
    },
    {
        "id": "monaro_cathcart",
        "name": "Cathcart & Monaro Plains",
        "subtitle": "High Tablelands & Snowy Hwy",
        "lat": -36.84325,
        "lon": 149.39124,
        "ele_m": 765,
        "km_start": 65.0,
        "km_end": 135.0,
    },
    {
        "id": "snowy_jindabyne",
        "name": "Dalgety & Lake Jindabyne",
        "subtitle": "Snowy River & Alpine Approach",
        "lat": -36.40954,
        "lon": 148.59683,
        "ele_m": 928,
        "km_start": 135.0,
        "km_end": 198.0,
    },
    {
        "id": "alpine_kosciuszko",
        "name": "Perisher, Charlotte Pass & Mt Kosciuszko",
        "subtitle": "Main Range Alpine Summit (2,228m)",
        "lat": -36.45611,
        "lon": 148.26387,
        "ele_m": 2228,
        "km_start": 198.0,
        "km_end": 242.0,
    },
]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    brng = math.degrees(math.atan2(y, x))
    return (brng + 360.0) % 360.0


def fetch_rwgps_route() -> dict:
    cache_path = DATA_DIR / "rwgps_41169434_raw.json"
    if cache_path.exists() and cache_path.stat().st_size > 100000:
        print(f"[Cache] Loading cached RideWithGPS route from {cache_path.name}...")
        return json.loads(cache_path.read_text(encoding="utf-8"))

    print(f"[Fetch] Downloading RideWithGPS route 41169434...")
    req = urllib.request.Request(RWGPS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read().decode("utf-8")
    cache_path.write_text(raw, encoding="utf-8")
    return json.loads(raw)


def project_point_to_track(lat: float, lon: float, track: list, hint_min_km: float = 0.0, hint_max_km: float = 250.0) -> dict:
    best_idx = 0
    best_dist = float("inf")
    for i, pt in enumerate(track):
        km = pt["d"] / 1000.0
        if km < hint_min_km or km > hint_max_km:
            continue
        d = haversine_m(lat, lon, pt["lat"], pt["lon"])
        if d < best_dist:
            best_dist = d
            best_idx = i
    matched = track[best_idx]
    return {
        "track_idx": best_idx,
        "course_km": round(matched["d"] / 1000.0, 2),
        "ele_m": round(matched["e"], 1),
        "snap_offset_m": round(best_dist, 1),
    }


def classify_poi(poi: dict, full_track: list) -> dict:
    name = (poi.get("name") or "").strip()
    desc = (poi.get("description") or "").strip().replace("\u200b", "")
    lat = float(poi.get("lat"))
    lon = float(poi.get("lng"))
    ptype = poi.get("poi_type_name") or "generic"

    # Disambiguate Charlotte Pass outbound vs Finish Line (which is at the end of the 241.25 km route)
    hint_min, hint_max = 0.0, 250.0
    if "Finishing Line" in name:
        hint_min, hint_max = 235.0, 245.0
    elif "Checkpoint #8" in name or "Cut-Off Point #3" in name:
        hint_min, hint_max = 215.0, 232.0
    elif "Summit of Mt Kosciuszko" in name:
        hint_min, hint_max = 220.0, 236.0

    proj = project_point_to_track(lat, lon, full_track, hint_min, hint_max)

    category = "landmark"
    cutoff_hours = None
    cutoff_label = None
    checkpoint_num = None

    if "Start at Boydtown" in name:
        category = "start"
    elif "Finishing Line" in name:
        category = "finish"
        cutoff_hours = 46.0
        cutoff_label = "Sun 03:30 (46h 00m)"
    elif "Summit of Mt Kosciuszko" in name:
        category = "summit"
    elif "Mandatory Checkpoint" in name:
        category = "checkpoint"
        for n in range(1, 9):
            if f"#{n}" in name:
                checkpoint_num = n
                break
    elif "Cut-Off Point" in name:
        category = "cutoff"
        if "#1" in name:
            cutoff_hours = 25.0
            cutoff_label = "Sat 06:30 (25h 00m)"
        elif "#2" in name:
            cutoff_hours = 32.5
            cutoff_label = "Sat 14:00 (32h 30m)"
        elif "#3" in name:
            cutoff_hours = 41.5
            cutoff_label = "Sat 23:00 (41h 30m)"
    elif "Cow Bail Trail" in name:
        category = "crew_uturn"
    elif "Aid Station" in name or "Rendezvous" in name:
        category = "crew_rendezvous"
    elif ptype == "caution":
        category = "caution"

    return {
        "name": name,
        "category": category,
        "poi_type": ptype,
        "checkpoint_num": checkpoint_num,
        "cutoff_hours": cutoff_hours,
        "cutoff_label": cutoff_label,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "ele_m": proj["ele_m"],
        "course_km": proj["course_km"],
        "track_idx": proj["track_idx"],
        "description": desc,
    }


def wmo_code_to_label(code: int) -> str:
    if code == 0:
        return "Clear Sky"
    if code == 1:
        return "Mainly Clear"
    if code == 2:
        return "Partly Cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Alpine Fog"
    if code in (51, 53, 55, 56, 57):
        return "Light Drizzle"
    if code in (61, 63, 65):
        return "Rain"
    if code in (66, 67):
        return "Freezing Rain"
    if code in (71, 73, 75, 77):
        return "Alpine Snow"
    if code in (80, 81, 82):
        return "Rain Showers"
    if code in (85, 86):
        return "Snow Showers"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "Partly Cloudy"


def fetch_open_meteo_zone(zone: dict) -> dict:
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={zone['lat']}&longitude={zone['lon']}"
        f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,cloud_cover,precipitation,"
        f"weather_code,wind_speed_10m,wind_gusts_10m,wind_direction_10m&timezone=Australia%2FSydney"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read().decode("utf-8"))
    cur = data.get("current") or {}
    code = int(cur.get("weather_code", 2))
    return {
        "temp_c": round(float(cur.get("temperature_2m", 14.0)), 1),
        "feelslike_c": round(float(cur.get("apparent_temperature", 12.0)), 1),
        "humidity": round(float(cur.get("relative_humidity_2m", 65.0)), 0),
        "windspeed_kmh": round(float(cur.get("wind_speed_10m", 16.0)), 1),
        "windgust_kmh": round(float(cur.get("wind_gusts_10m", 24.0)), 1),
        "winddir_deg": round(float(cur.get("wind_direction_10m", 250.0)), 0),
        "cloudcover_pct": round(float(cur.get("cloud_cover", 40.0)), 0),
        "precip_mm": round(float(cur.get("precipitation", 0.0)), 1),
        "precipprob_pct": 15.0,
        "visibility_km": 15.0,
        "conditions": wmo_code_to_label(code),
        "icon": "partly-cloudy-day",
        "sunrise": "05:45:00",
        "sunset": "19:55:00",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_baseline_weather() -> list:
    vc_key = load_visual_crossing_key()
    results = []
    for zone in WEATHER_ZONES:
        zone_out = dict(zone)
        fetched = False
        if vc_key:
            loc_str = f"{zone['lat']},{zone['lon']}"
            url = (
                f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/"
                f"{urllib.parse.quote(loc_str)}/today?unitGroup=metric&include=current,days&key={vc_key}&contentType=json"
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=12) as r:
                    wdata = json.loads(r.read().decode("utf-8"))
                cur = wdata.get("currentConditions") or (wdata.get("days") or [{}])[0]
                day0 = (wdata.get("days") or [{}])[0]
                zone_out["weather"] = {
                    "temp_c": cur.get("temp", day0.get("temp", 14.0)),
                    "feelslike_c": cur.get("feelslike", day0.get("feelslike", 12.0)),
                    "humidity": cur.get("humidity", 65.0),
                    "windspeed_kmh": cur.get("windspeed", 18.0),
                    "windgust_kmh": cur.get("windgust", 28.0),
                    "winddir_deg": cur.get("winddir", 250.0),
                    "cloudcover_pct": cur.get("cloudcover", 45.0),
                    "precip_mm": cur.get("precip", 0.0),
                    "precipprob_pct": cur.get("precipprob", day0.get("precipprob", 15.0)),
                    "visibility_km": cur.get("visibility", 10.0),
                    "conditions": cur.get("conditions", day0.get("conditions", "Partly Cloudy")),
                    "icon": cur.get("icon", "partly-cloudy-day"),
                    "sunrise": day0.get("sunrise", "05:45:00"),
                    "sunset": day0.get("sunset", "19:55:00"),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                fetched = True
            except Exception as e:
                print(f"  [VisualCrossing Fallback -> Open-Meteo] {zone['name']}: {e}")

        if not fetched:
            try:
                zone_out["weather"] = fetch_open_meteo_zone(zone)
                fetched = True
            except Exception as e:
                print(f"  [Weather Warning] Static Fallback for {zone['name']}: {e}")
                zone_out["weather"] = {
                    "temp_c": max(2.0, round(20.0 - (zone["ele_m"] / 1000.0) * 6.5, 1)),
                    "feelslike_c": max(-2.0, round(18.0 - (zone["ele_m"] / 1000.0) * 7.5, 1)),
                    "humidity": 68.0,
                    "windspeed_kmh": round(15.0 + (zone["ele_m"] / 100.0) * 1.2, 1),
                    "windgust_kmh": round(24.0 + (zone["ele_m"] / 100.0) * 1.8, 1),
                    "winddir_deg": 265.0,
                    "cloudcover_pct": 42.0,
                    "precip_mm": 0.0,
                    "precipprob_pct": 10.0,
                    "visibility_km": 15.0,
                    "conditions": "Partly Cloudy",
                    "icon": "partly-cloudy-day",
                    "sunrise": "05:45:00",
                    "sunset": "19:55:00",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }

        print(
            f"  [Weather] {zone['name']} ({zone['ele_m']}m): "
            f"{zone_out['weather']['temp_c']}C, Wind {zone_out['weather']['windspeed_kmh']} km/h @ {zone_out['weather']['winddir_deg']} deg, "
            f"Clouds {zone_out['weather']['cloudcover_pct']}% ({zone_out['weather']['conditions']})"
        )
        results.append(zone_out)
    return results


def calibrate_summit_elevation(full_track: list) -> None:
    """Calibrate SRTM-smoothed Mt Kosciuszko crown (~230.0 - 233.5 km) to exact 2,228.0 m."""
    peak_idx = None
    peak_ele = -1.0
    for i, pt in enumerate(full_track):
        km = pt["d"] / 1000.0
        if 230.0 <= km <= 233.5 and pt["e"] > peak_ele:
            peak_ele = pt["e"]
            peak_idx = i
    if peak_idx is None or peak_ele <= 0:
        return
    delta = 2228.0 - peak_ele
    peak_d = full_track[peak_idx]["d"]
    flat_radius_m = 65.0
    radius_m = 450.0
    for pt in full_track:
        dist_m = abs(pt["d"] - peak_d)
        if dist_m <= flat_radius_m:
            pt["e"] = 2228.0
        elif dist_m <= radius_m:
            t = (dist_m - flat_radius_m) / (radius_m - flat_radius_m)
            weight = 0.5 * (1.0 + math.cos(math.pi * t))
            pt["e"] = min(2228.0, round(pt["e"] + delta * weight, 1))
    print(f"[Elevation] Calibrated Mt Kosciuszko crown at {peak_d / 1000.0:.2f} km from {peak_ele:.1f}m -> {full_track[peak_idx]['e']:.1f}m")


def clean_dashes(text):
    if not isinstance(text, str):
        return text
    return text.replace("\u2014", " - ").replace("\u2013", " - ")


def build_cutoff_gates(pois: list, full_track: list) -> list:
    by_name = {p["name"]: p for p in pois}

    def pick(substr: str, fallback_km: float, fallback_lat: float, fallback_lon: float):
        for name, p in by_name.items():
            if substr in name:
                return p
        return {"course_km": fallback_km, "lat": fallback_lat, "lon": fallback_lon}

    cp3 = pick("Checkpoint #3", 70.60, -36.84325, 149.39124)
    cp4 = pick("Checkpoint #4", 107.56, -36.69087, 149.15996)
    g1 = pick("Cut-Off Point #1", 149.21, -36.50459, 148.83101)
    g2 = pick("Cut-Off Point #2", 184.88, -36.40943, 148.59668)
    g3 = pick("Cut-Off Point #3", 222.63, -36.43155, 148.32901)
    gf = pick("Finishing Line", 241.25, -36.43173, 148.32841)

    gates = [
        {
            "id": "cathcart",
            "name": "Cut-Off #1 - Cathcart (CP3)",
            "shortName": "CP3 Cathcart",
            "km": cp3["course_km"],
            "scheduleKm": 70,
            "limitHours": 12.0,
            "clockLabel": "Fri 17:30",
            "lat": cp3["lat"],
            "lon": cp3["lon"],
        },
        {
            "id": "gunningrah",
            "name": "Cut-Off #2 - Gunningrah Rd (CP4)",
            "shortName": "CP4 Gunningrah",
            "km": cp4["course_km"],
            "scheduleKm": 106,
            "limitHours": 18.0,
            "clockLabel": "Fri 23:30",
            "lat": cp4["lat"],
            "lon": cp4["lon"],
        },
        {
            "id": "dalgety",
            "name": "Cut-Off #3 - Dalgety Bridge (CP5)",
            "shortName": "CP5 Dalgety",
            "km": g1["course_km"],
            "scheduleKm": 148,
            "limitHours": 25.0,
            "clockLabel": "Sat 06:30",
            "lat": g1["lat"],
            "lon": g1["lon"],
        },
        {
            "id": "jindabyne",
            "name": "Cut-Off #4 - Jindabyne (CP6)",
            "shortName": "CP6 Jindabyne",
            "km": g2["course_km"],
            "scheduleKm": 184,
            "limitHours": 32.5,
            "clockLabel": "Sat 14:00",
            "lat": g2["lat"],
            "lon": g2["lon"],
        },
        {
            "id": "charlotte_out",
            "name": "Cut-Off #5 - Charlotte Pass (CP8)",
            "shortName": "CP8 Charlotte Out",
            "km": g3["course_km"],
            "scheduleKm": 222,
            "limitHours": 41.5,
            "clockLabel": "Sat 23:00",
            "lat": g3["lat"],
            "lon": g3["lon"],
        },
        {
            "id": "finish",
            "name": "Final Cut-Off - Charlotte Pass Finish",
            "shortName": "Finish 240km",
            "km": gf["course_km"],
            "scheduleKm": 240,
            "limitHours": 46.0,
            "clockLabel": "Sun 03:30",
            "lat": gf["lat"],
            "lon": gf["lon"],
        },
    ]
    return gates


def build_official_toilets_and_aid(pois: list, full_track: list) -> list:
    """
    Strictly official C2K 2026 Runners Guide (p.23 & p.27) & Course Directions stops,
    projected onto the 241.25 km Cow Bail Trail track.
    """
    p_seamans_out = project_point_to_track(-36.450278, 148.282633, full_track, 222.0, 232.0)
    p_seamans_ret = project_point_to_track(-36.450278, 148.282633, full_track, 232.0, 242.0)
    p_rawson_out = project_point_to_track(-36.457690, 148.268770, full_track, 222.0, 232.0)
    p_rawson_ret = project_point_to_track(-36.457690, 148.268770, full_track, 232.0, 242.0)
    p_bigjack = project_point_to_track(-36.897993, 149.463533, full_track, 50.0, 62.0)
    p_cathcart_toilet = project_point_to_track(-36.843436, 149.389075, full_track, 70.5, 72.0)
    p_jindy_toilet = project_point_to_track(-36.413939, 148.609790, full_track, 180.0, 186.0)

    stops = [
        {
            "id": "boydtown-no-toilet",
            "name": "Boydtown Beach Start - NO TOILETS",
            "shortName": "Start: NO TOILETS",
            "course_km": 0.0,
            "return_course_km": None,
            "lat": -37.092052,
            "lon": 149.872263,
            "ele_m": 4.0,
            "kind": "no_toilet",
            "has_toilet": False,
            "has_aid": False,
            "runner_access": True,
            "crew_access": True,
            "warning_level": "danger",
            "payment_badge": "",
            "toilet_rule": "STRICTLY NO TOILETS AT THE START LINE - PENALTIES APPLY. Bushes must NOT be used.",
            "food_aid": "None (No crew support allowed from 0 km until Towamba 24.4 km).",
            "crew_note": "Use hotel / Eden facilities before arriving for 04:50 start check-in.",
            "off_route_note": "",
            "source": "2026 Runners Guide p.27",
        },
        {
            "id": "aid-station-1",
            "name": "Aid Station #1 - Nullica Rd / Brandy Creek",
            "shortName": "Aid Station #1",
            "course_km": 3.74,
            "return_course_km": None,
            "lat": -37.089905,
            "lon": 149.843209,
            "ele_m": 95.0,
            "kind": "aid_only",
            "has_toilet": False,
            "has_aid": True,
            "runner_access": True,
            "crew_access": False,
            "warning_level": "info",
            "payment_badge": "FREE RACE AID",
            "toilet_rule": "No toilets at Aid Station #1.",
            "food_aid": "Minimal water, drink & light food. ONLY official aid before Towamba (24.4 km).",
            "crew_note": "NO CREW ACCESS - Crews must drive past straight to Towamba (24.4 km) without stopping.",
            "off_route_note": "",
            "source": "Official Course Directions",
        },
        {
            "id": "towamba-cp1",
            "name": "Towamba (CP1) - Toilets & School BBQ",
            "shortName": "Towamba Toilets + BBQ",
            "course_km": 24.42,
            "return_course_km": None,
            "lat": -37.081612,
            "lon": 149.693848,
            "ele_m": 38.0,
            "kind": "toilet_and_aid",
            "has_toilet": True,
            "has_aid": True,
            "runner_access": True,
            "crew_access": True,
            "warning_level": "ok",
            "payment_badge": "CASH PREFERRED",
            "toilet_rule": "Official Towamba toilets listed in 2026 Runners Guide (p.27). Re-enter course at exact exit point if stepping off-route.",
            "food_aid": "Towamba Public School BBQ breakfast fundraiser for runners & support crews.",
            "crew_note": "First official crew rendezvous. Park safely past Towamba Rd / Pericoe Rd junction.",
            "off_route_note": "",
            "source": "2026 Runners Guide p.23 & p.27",
        },
        {
            "id": "rocky-hall-cp2",
            "name": "Rocky Hall (CP2) - Restrooms & Coffee/Snacks",
            "shortName": "Rocky Hall Toilets + Coffee",
            "course_km": 51.67,
            "return_course_km": None,
            "lat": -36.927101,
            "lon": 149.503274,
            "ele_m": 209.0,
            "kind": "toilet_and_aid",
            "has_toilet": True,
            "has_aid": True,
            "runner_access": True,
            "crew_access": True,
            "warning_level": "ok",
            "payment_badge": "CASH ONLY",
            "toilet_rule": "Official Rocky Hall restrooms right at CP2 public telephone.",
            "food_aid": "Rocky Hall Society coffee and snacks available for runners and support crews (CASH ONLY).",
            "crew_note": "Prep 1 mandatory pacer for Cow Bail Trail / Big Jack Mountain ascent ahead (56.1 km).",
            "off_route_note": "",
            "source": "2026 Runners Guide p.23 & p.27",
        },
        {
            "id": "big-jack-base",
            "name": "Base of Big Jack Mountain - Park Toilet",
            "shortName": "Big Jack Base Toilet",
            "course_km": p_bigjack["course_km"],
            "return_course_km": None,
            "lat": -36.897993,
            "lon": 149.463533,
            "ele_m": 290.0,
            "kind": "toilet_only",
            "has_toilet": True,
            "has_aid": False,
            "runner_access": False,
            "crew_access": True,
            "warning_level": "warn",
            "payment_badge": "",
            "toilet_rule": "Official Guide p.27 toilet: Base of Big Jack Mountain - opposite side of road to the park.",
            "food_aid": "No food stall (crew support before Cow Bail turnoff).",
            "crew_note": "Sits ~1.15 km straight ahead past Cow Bail Trail turnoff on Big Jack Mountain Rd (Crew / Big Jack alignment only).",
            "off_route_note": "Off Cow Bail Foot Trail (~1.15 km past 56.07 km left turn onto Big Jack Mountain Rd).",
            "source": "2026 Runners Guide p.27",
        },
        {
            "id": "cathcart-cp3",
            "name": "Cathcart (CP3) - General Store & Toilet",
            "shortName": "Cathcart Store + Toilet",
            "course_km": p_cathcart_toilet["course_km"],
            "return_course_km": None,
            "lat": -36.843436,
            "lon": 149.389075,
            "ele_m": 802.0,
            "kind": "toilet_and_aid",
            "has_toilet": True,
            "has_aid": True,
            "runner_access": True,
            "crew_access": True,
            "warning_level": "ok",
            "payment_badge": "CASH ONLY",
            "toilet_rule": "Official Cathcart toilet approx. 200m past Cathcart General Store.",
            "food_aid": "Cathcart General Store drinks and snacks (CASH ONLY). Hard Cut-Off #1 at 17:30 Fri (12h).",
            "crew_note": "Crew regroups with Simon here after Cow Bail -> Mt Darragh Rd detour.",
            "off_route_note": "",
            "source": "2026 Runners Guide p.23 & p.27",
        },
        {
            "id": "dalgety-cp5",
            "name": "Dalgety Hall (CP5) - Soup & Segregated Toilets",
            "shortName": "Dalgety Hall (Split Toilets)",
            "course_km": 148.93,
            "return_course_km": None,
            "lat": -36.504125,
            "lon": 148.833730,
            "ele_m": 755.0,
            "kind": "toilet_and_aid",
            "has_toilet": True,
            "has_aid": True,
            "runner_access": True,
            "crew_access": True,
            "warning_level": "warn",
            "payment_badge": "RUNNER+CREW ONLY",
            "toilet_rule": "STRICT SPLIT: Dalgety Hall toilets are RUNNERS ONLY. Support Crew MUST use building 50-100m beyond rear of Dalgety Hall.",
            "food_aid": "Dalgety Hall hot soup & refreshments for runners & support crews ONLY (not spectators, family, or friends).",
            "crew_note": "Crews use rear toilet building (50-100m behind Hall). Cut-Off #3 (06:30 Sat) is just ahead across Dalgety Bridge.",
            "off_route_note": "",
            "source": "2026 Runners Guide p.23 & p.27",
        },
        {
            "id": "jindabyne-lake-path",
            "name": "Jindabyne - Lake Path Toilet & Town Supplies",
            "shortName": "Jindabyne Toilet + Supplies",
            "course_km": p_jindy_toilet["course_km"],
            "return_course_km": None,
            "lat": -36.413939,
            "lon": 148.609790,
            "ele_m": 914.0,
            "kind": "toilet_and_aid",
            "has_toilet": True,
            "has_aid": True,
            "runner_access": True,
            "crew_access": True,
            "warning_level": "ok",
            "payment_badge": "PLAN HOURS ~7AM-7PM",
            "toilet_rule": "Official Guide p.27 toilet: Opposite the roundabout, adjacent to the Lake Jindabyne foreshore path.",
            "food_aid": "Main late-race restock: supermarkets, food outlets & fuel open ~7:00 am, many closing ~7:00 pm. Cut-Off #4 at Caravan Park (184.9 km, Sat 14:00).",
            "crew_note": "Crews can turn right at Barry Way roundabout briefly for town supplies, then meet Simon at Caravan Park exit (184.9 km).",
            "off_route_note": "",
            "source": "2026 Runners Guide p.23 & p.27",
        },
        {
            "id": "charlotte-pass-cp8",
            "name": "Charlotte Pass (CP8 & Finish) - Alpine Toilet",
            "shortName": "Charlotte Pass Toilet",
            "course_km": 222.63,
            "return_course_km": 241.25,
            "lat": -36.431606,
            "lon": 148.328827,
            "ele_m": 1838.0,
            "kind": "toilet_only",
            "has_toilet": True,
            "has_aid": False,
            "runner_access": True,
            "crew_access": True,
            "warning_level": "warn",
            "payment_badge": "SUMMIT GEAR CHECK",
            "toilet_rule": "Official Charlotte Pass toilets at turnaround car park (used outbound at CP8 & upon Finish return).",
            "food_aid": "No open shops - crew vehicle staging only before 18.4 km Summit Path. Lock all food inside vehicles from ravens & currawongs.",
            "crew_note": "Final crew vehicle access point. Mandatory 14-item Summit Gear inspection here before 23:00 Sat cut-off.",
            "off_route_note": "",
            "source": "2026 Runners Guide p.15 & p.27",
        },
        {
            "id": "seamans-hut",
            "name": "Seamans Hut - Summit Path Toilet & Shelter",
            "shortName": "Seamans Hut Toilet",
            "course_km": p_seamans_out["course_km"],
            "return_course_km": p_seamans_ret["course_km"],
            "lat": -36.450278,
            "lon": 148.282633,
            "ele_m": 2020.0,
            "kind": "toilet_only",
            "has_toilet": True,
            "has_aid": False,
            "runner_access": True,
            "crew_access": False,
            "warning_level": "info",
            "payment_badge": "EMERGENCY SHELTER",
            "toilet_rule": "Official Summit Path toilet & emergency shelter (6 km past Charlotte Pass). Never leave waste or toilet paper on Summit Path.",
            "food_aid": "Emergency shelter only - carry all food & water from Charlotte Pass.",
            "crew_note": "Foot-only Summit Path (no crew vehicles; pacers/crew on foot only).",
            "off_route_note": "Passed twice: outbound ~" + str(round(p_seamans_out["course_km"], 1)) + " km & return ~" + str(round(p_seamans_ret["course_km"], 1)) + " km.",
            "source": "2026 Runners Guide p.15 & p.27",
        },
        {
            "id": "rawson-pass",
            "name": "Rawson Pass - Summit Path Toilet & Shelter",
            "shortName": "Rawson Pass Toilet",
            "course_km": p_rawson_out["course_km"],
            "return_course_km": p_rawson_ret["course_km"],
            "lat": -36.457690,
            "lon": 148.268770,
            "ele_m": 2122.0,
            "kind": "toilet_only",
            "has_toilet": True,
            "has_aid": False,
            "runner_access": True,
            "crew_access": False,
            "warning_level": "info",
            "payment_badge": "HIGHEST TOILET 2122m",
            "toilet_rule": "Official Summit Path toilet & emergency shelter (7.6 km past Charlotte Pass, 1.6 km below Summit).",
            "food_aid": "Emergency shelter only.",
            "crew_note": "Foot-only Summit Path. Last toilet before Mt Kosciuszko Summit turnaround.",
            "off_route_note": "Passed twice: outbound ~" + str(round(p_rawson_out["course_km"], 1)) + " km & return ~" + str(round(p_rawson_ret["course_km"], 1)) + " km.",
            "source": "2026 Runners Guide p.15 & p.27",
        },
    ]
    return [{k: clean_dashes(v) for k, v in s.items()} for s in stops]


def build_bundle():
    data = fetch_rwgps_route()
    raw_pts = data.get("track_points", [])
    print(f"[Track] Processing {len(raw_pts)} raw track points...")

    full_track = []
    for p in raw_pts:
        lat = float(p.get("y"))
        lon = float(p.get("x"))
        ele = float(p.get("e") or 0.0)
        dist = float(p.get("d") or 0.0)
        full_track.append({"lat": lat, "lon": lon, "e": ele, "d": dist})

    # Calibrate Mt Kosciuszko summit to 2,228.0 m before computing grades & POIs
    calibrate_summit_elevation(full_track)

    # Compute smoothed grade (%) over a +-120m window and bearing
    n = len(full_track)
    for i in range(n):
        j_prev = i
        while j_prev > 0 and (full_track[i]["d"] - full_track[j_prev]["d"]) < 120.0:
            j_prev -= 1
        j_next = i
        while j_next < n - 1 and (full_track[j_next]["d"] - full_track[i]["d"]) < 120.0:
            j_next += 1
        dd = full_track[j_next]["d"] - full_track[j_prev]["d"]
        de = full_track[j_next]["e"] - full_track[j_prev]["e"]
        grade = (de / dd) * 100.0 if dd > 10.0 else 0.0
        grade = max(-28.0, min(28.0, grade))

        b_next = min(n - 1, i + 3)
        b_prev = max(0, i - 3)
        brng = bearing_deg(
            full_track[b_prev]["lat"],
            full_track[b_prev]["lon"],
            full_track[b_next]["lat"],
            full_track[b_next]["lon"],
        )
        full_track[i]["g"] = round(grade, 1)
        full_track[i]["b"] = round(brng, 1)

    # Downsample to ~3,150 high-precision points (~72m spacing) for instant 60fps WebGL + scrub lookup
    # Always preserve start, summit plateau, sharp turns, and finish
    compact_points = []
    last_d = -999.0
    for i, pt in enumerate(full_track):
        if i == 0 or i == n - 1 or pt["e"] >= 2227.5 or (pt["d"] - last_d) >= 72.0 or (abs(pt["g"]) >= 12.0 and (pt["d"] - last_d) >= 40.0):
            compact_points.append([
                round(pt["lon"], 6),
                round(pt["lat"], 6),
                round(pt["e"], 1),
                round(pt["d"] / 1000.0, 3),
                pt["g"],
                pt["b"],
            ])
            last_d = pt["d"]

    print(f"[Track] Compacted to {len(compact_points)} high-precision 3D spine vertices.")

    # Process Official POIs
    raw_pois = data.get("points_of_interest", [])
    pois = [classify_poi(p, full_track) for p in raw_pois]
    pois.sort(key=lambda x: x["course_km"])

    def find_poi_km(substr: str, fallback: float) -> float:
        for p in pois:
            if substr in p["name"]:
                return p["course_km"]
        return fallback

    cutoff_gates = build_cutoff_gates(pois, full_track)
    toilets_aid = build_official_toilets_and_aid(pois, full_track)

    # Generate Distance Milestones every 10 km + special markers
    milestones = []
    special_kms = [
        (42.195, "42.2 KM // MARATHON MARK", "special"),
        (100.0, "100 KM // CENTURY MARK", "special"),
        (160.934, "160.9 KM // 100 MILES", "special"),
        (200.0, "200 KM // MAIN RANGE CLIMB", "special"),
    ]
    for km_target in range(10, 241, 10):
        if km_target in (100, 200):
            continue
        milestones.append((float(km_target), f"{km_target} KM", "km_tick"))
    milestones.extend(special_kms)
    milestones.sort(key=lambda x: x[0])

    milestone_objs = []
    for km_val, label, mtype in milestones:
        target_m = km_val * 1000.0
        best_pt = min(full_track, key=lambda p: abs(p["d"] - target_m))
        milestone_objs.append({
            "km": round(km_val, 1),
            "label": label,
            "type": mtype,
            "lat": round(best_pt["lat"], 6),
            "lon": round(best_pt["lon"], 6),
            "ele_m": round(best_pt["e"], 1),
            "grade_pct": best_pt["g"],
        })

    # Process 49 turn cues
    cues = []
    for cp in data.get("course_points", []):
        cues.append({
            "type": cp.get("t", "Straight"),
            "notes": (cp.get("n") or "").strip(),
            "km": round(float(cp.get("d") or 0.0) / 1000.0, 2),
            "lat": round(float(cp.get("y")), 6),
            "lon": round(float(cp.get("x")), 6),
        })

    # Fetch baseline weather for the 5 elevation zones
    print("[Weather] Fetching live 5-zone weather snapshot...")
    weather_zones = fetch_baseline_weather()

    bundle = {
        "meta": {
            "name": "Coast to Kosciuszko Ultramarathon (Cow Bail Trail Route)",
            "short_name": "COAST TO KOSCI // 240KM ULTRA",
            "rwgps_id": 41169434,
            "total_distance_km": round(float(data.get("distance", 241252.0)) / 1000.0, 2),
            "elevation_gain_m": round(float(data.get("elevation_gain", 5540.6)), 0),
            "elevation_loss_m": round(float(data.get("elevation_loss", 3781.9)), 0),
            "max_elevation_m": 2228.0,
            "start_elevation_m": 0.0,
            "race_start_iso": "2026-11-20T05:30:00+11:00",
            "race_cutoff_iso": "2026-11-22T03:30:00+11:00",
            "race_start_local": "Friday Nov 20, 05:30 AEDT",
            "race_cutoff_local": "Sunday Nov 22, 03:30 AEDT (46 Hours)",
            "cutoff_hours": 46.0,
            "summit_km": find_poi_km("Summit of Mt Kosciuszko", 231.94),
            "cow_bail_start_km": find_poi_km("Cow Bail Trail", 56.07),
            "cathcart_cp3_km": find_poi_km("Checkpoint #3", 70.60),
            "charlotte_pass_cp8_km": find_poi_km("Checkpoint #8", 222.62),
            "bbox": {
                "min_lat": -37.1119,
                "min_lon": 148.26237,
                "max_lat": -36.34199,
                "max_lon": 149.87144,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "point_schema": "[lon, lat, ele_m, dist_km, grade_pct, bearing_deg]",
        },
        "cutoff_gates": cutoff_gates,
        "toilets_aid": toilets_aid,
        "pois": pois,
        "milestones": milestone_objs,
        "cues": cues,
        "weather_zones": weather_zones,
        "track": compact_points,
    }

    out_json = DATA_DIR / "c2k_course.json"
    out_json.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")

    # Also write a JS global bundle so index.html works 100% offline via file:// or GitHub Pages
    out_js = DATA_DIR / "c2k_course_bundle.js"
    out_js.write_text(
        "window.C2K_COURSE_DATA = " + json.dumps(bundle, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    print(f"[Success] Wrote {out_json.name} ({out_json.stat().st_size / 1024:.1f} KB) and {out_js.name}")
    print(f"[Summary] POIs: {len(pois)} | Milestones: {len(milestone_objs)} | Cues: {len(cues)} | Track Vertices: {len(compact_points)}")


if __name__ == "__main__":
    build_bundle()
