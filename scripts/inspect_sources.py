import json
import math
import re
import shutil
from pathlib import Path

import requests
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_scrape"
DOCS_DIR = BASE_DIR / "official_docs"
GUIDE_IMG_DIR = RAW_DIR / "guide_images"
TRACKING_DIR = RAW_DIR / "tracking"
EXTRA_MEDIA_DIR = RAW_DIR / "extra_media"
EXTRA_MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def convert_jp2_images():
    for p in GUIDE_IMG_DIR.glob("*.jp2"):
        out = p.with_suffix(".png")
        try:
            Image.open(p).save(out)
            print(f"Converted {p.name} -> {out.name}")
        except Exception as e:
            print(f"JP2 convert err {p.name}: {e}")


def inspect_rwgps():
    rw = json.loads((RAW_DIR / "rwgps_41169431.json").read_text(encoding="utf-8"))
    pts = rw.get("track_points", [])
    pois = rw.get("points_of_interest", [])
    cues = rw.get("course_points", [])

    # Match each POI to nearest track_point(s) (handle out-and-back near Kosciuszko!)
    poi_rows = []
    for i, poi in enumerate(pois, 1):
        plat, plng = poi.get("lat"), poi.get("lng")
        best_dist = 1e12
        best_pt = None
        all_close_kms = []
        for tp in pts:
            dm = haversine_m(plat, plng, tp["y"], tp["x"])
            if dm < best_dist:
                best_dist = dm
                best_pt = tp
            if dm < 120:
                all_close_kms.append(round(tp["d"] / 1000.0, 2))
        # Deduplicate clusters in all_close_kms (>2 km apart)
        clusters = []
        for km in all_close_kms:
            if not clusters or abs(km - clusters[-1]) > 2.0:
                clusters.append(km)
        poi_rows.append({
            "idx": i,
            "name": poi.get("name"),
            "poi_type": poi.get("poi_type_name"),
            "description": poi.get("description", ""),
            "lat": plat,
            "lng": plng,
            "nearest_track_km": round(best_pt["d"] / 1000.0, 2) if best_pt else None,
            "nearest_elev_m": round(best_pt["e"], 1) if best_pt and "e" in best_pt else None,
            "snap_offset_m": round(best_dist, 1),
            "pass_kms": clusters,
        })

    cue_rows = []
    for i, c in enumerate(cues, 1):
        idx_tp = c.get("i")
        elev = None
        if isinstance(idx_tp, int) and 0 <= idx_tp < len(pts):
            elev = pts[idx_tp].get("e")
        cue_rows.append({
            "idx": i,
            "km": round(c.get("d", 0) / 1000.0, 2),
            "type": c.get("t"),
            "instruction": c.get("n"),
            "lat": c.get("y"),
            "lng": c.get("x"),
            "elev_m": round(elev, 1) if elev is not None else None,
        })

    out_txt = [
        f"Route: {rw.get('name')} | Distance: {rw.get('distance', 0)/1000:.2f} km | Elev Gain: {rw.get('elevation_gain'):.1f} m",
        "",
        "=== 31 OFFICIAL RWGPS POIs ===",
    ]
    for r in sorted(poi_rows, key=lambda x: x["nearest_track_km"] or 0):
        out_txt.append(
            f"km {r['nearest_track_km']:6.2f} (passes={r['pass_kms']}, elev={r['nearest_elev_m']}m, off={r['snap_offset_m']}m) "
            f"[{r['poi_type']}] {r['name']} | {r['description']} | ({r['lat']:.6f}, {r['lng']:.6f})"
        )
    out_txt.append("")
    out_txt.append("=== 61 OFFICIAL RWGPS TURN CUES ===")
    for c in cue_rows:
        out_txt.append(
            f"#{c['idx']:02d} km {c['km']:6.2f} (elev={c['elev_m']}m) [{c['type']}] {c['instruction']} | ({c['lat']:.6f}, {c['lng']:.6f})"
        )

    (RAW_DIR / "rwgps_pois_and_cues.txt").write_text("\n".join(out_txt), encoding="utf-8")
    (RAW_DIR / "rwgps_parsed_summary.json").write_text(
        json.dumps({"pois": poi_rows, "cues": cue_rows}, indent=2), encoding="utf-8"
    )
    print(f"Parsed RWGPS: {len(poi_rows)} POIs, {len(cue_rows)} cues")


def probe_trackmelive_api():
    headers = {"User-Agent": "Mozilla/5.0"}
    app_js = requests.get("https://live.trackmelive.com.au/assets/js/app_1.1.118.js", headers=headers, timeout=20).text
    (TRACKING_DIR / "app_1.1.118.js").write_text(app_js, encoding="utf-8")

    # Find Url.make definition
    m = re.search(r"var\s+Url\s*=.*?(?=var\s+[A-Z]|$)", app_js, re.S)
    url_snippet = m.group(0)[:2000] if m else ""
    (TRACKING_DIR / "url_helper_snippet.txt").write_text(url_snippet, encoding="utf-8")

    # Try standard OpenTracking JSON endpoints
    endpoints = [
        "https://live.trackmelive.com.au/coasttokosci26/data/config.json",
        "https://live.trackmelive.com.au/coasttokosci26/data/checkpoints.json",
        "https://live.trackmelive.com.au/coasttokosci26/data/route.json",
        "https://live.trackmelive.com.au/coasttokosci26/config",
        "https://live.trackmelive.com.au/coasttokosci26/checkpoints",
        "https://live.opentracking.co.uk/coasttokosci26/data/config.json",
        "https://live.opentracking.co.uk/coasttokosci26/data/checkpoints.json",
        "https://live.trackmelive.com.au/coasttokosci25/data/checkpoints.json",
        "https://live.trackmelive.com.au/coasttokosci25/data/config.json",
    ]
    hits = {}
    for ep in endpoints:
        try:
            r = requests.get(ep, headers=headers, timeout=12)
            hits[ep] = {"status": r.status_code, "len": len(r.text), "preview": r.text[:300]}
            if r.status_code == 200 and len(r.text) > 5 and r.text.strip()[0] in "{[":
                name = ep.replace("https://", "").replace("/", "_")
                (TRACKING_DIR / f"{name}.json").write_text(r.text, encoding="utf-8")
                print(f"TML HIT {ep}: {len(r.text)} bytes")
        except Exception as e:
            hits[ep] = {"error": str(e)}
    (TRACKING_DIR / "api_probe_results.json").write_text(json.dumps(hits, indent=2), encoding="utf-8")


def clean_official_docs():
    """Keep official documents (PDF/GPX/etc.) and true info/map/guide images in official_docs/; move stock photos to extra_media."""
    keep_img_patterns = ("map", "course", "route", "elevation", "profile", "schedule", "guide", "sign", "vehicle", "checkpoint")
    moved = 0
    kept = 0
    for f in sorted(DOCS_DIR.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            low = f.name.lower()
            if any(p in low for p in keep_img_patterns) and not any(bad in low for bad in ("_640x640", "cropped-", "dsc", "img_", "photo", "fb_img")):
                kept += 1
            else:
                shutil.move(str(f), str(EXTRA_MEDIA_DIR / f.name))
                moved += 1
        else:
            kept += 1
    print(f"official_docs cleanup -> kept {kept} files, moved {moved} extra/stock images to raw_scrape/extra_media/")


def query_public_toilets_national():
    """
    Query Australia's National Public Toilet Map API or OpenStreetMap Overpass (one clean small query)
    for public toilets across Bega Valley & Snowy Monaro LGAs / corridor towns.
    """
    headers = {"User-Agent": "CoastToKosciLogisticsDB/1.0"}
    # Try one clean Overpass query on overpass.private.coffee or overpass-api.de for toilets in the corridor bbox
    # Corridor bbox: South=-37.15, West=148.20, North=-36.30, East=149.95
    query = """
    [out:json][timeout:35];
    (
      node["amenity"="toilets"](-37.15,148.20,-36.30,149.95);
      way["amenity"="toilets"](-37.15,148.20,-36.30,149.95);
      node["amenity"="fuel"](-37.15,148.20,-36.30,149.95);
      node["amenity"="community_centre"](-37.15,148.20,-36.30,149.95);
      way["amenity"="community_centre"](-37.15,148.20,-36.30,149.95);
      node["tourism"="alpine_hut"](-36.50,148.20,-36.38,148.45);
      way["tourism"="alpine_hut"](-36.50,148.20,-36.38,148.45);
    );
    out center tags;
    """
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    for url in endpoints:
        try:
            print(f"Querying OSM bbox via {url}...")
            r = requests.post(url, data={"data": query}, headers=headers, timeout=40)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                data = r.json()
                els = data.get("elements", [])
                print(f"OSM bbox SUCCESS ({url}): {len(els)} amenities found!")
                (RAW_DIR / "osm_corridor_bbox.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
                return len(els)
            else:
                print(f"OSM {url} HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            print(f"OSM {url} error: {e}")
    return 0


if __name__ == "__main__":
    convert_jp2_images()
    inspect_rwgps()
    probe_trackmelive_api()
    clean_official_docs()
    query_public_toilets_national()
