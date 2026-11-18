r"""
Coast to Kosciuszko (C2K) - Google Drive Cloud GPX Folder Sync
Watches Jake's live GPSLogger Google Drive folder (G:\My Drive\GPSLogger for Android)
plus dedicated Coast2Kosci gpx_drop\crew and gpx_drop\simon folders, parses the newest
.gpx trackpoints, and pushes authenticated updates to the 24/7 Cloud Relay.

Usage:
  python scripts/sync_gpx_folder.py --dry-run
  python scripts/sync_gpx_folder.py --once
  python scripts/sync_gpx_folder.py --watch --interval 20
"""

import argparse
import json
import math
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_PATH = DATA_DIR / "c2k_relay_config.json"
CURSOR_PATH = DATA_DIR / "gpx_sync_cursor.json"

GPX_SOURCES = [
    ("crew", Path(r"G:\My Drive\GPSLogger for Android"), "GPSLogger Drive GPX"),
    ("crew", ROOT_DIR / "gpx_drop" / "crew", "Crew GPX Drop Folder"),
    ("runner", ROOT_DIR / "gpx_drop" / "simon", "Simon GPX Drop Folder"),
]


def ensure_drop_folders() -> None:
    for _, folder, _ in GPX_SOURCES[1:]:
        folder.mkdir(parents=True, exist_ok=True)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def parse_iso_ms(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


def parse_gpx_file(gpx_path: Path) -> List[Dict]:
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    points: List[Dict] = []

    for elem in root.iter():
        if local_tag(elem.tag) != "trkpt":
            continue
        try:
            lat = float(elem.attrib["lat"])
            lon = float(elem.attrib["lon"])
        except (KeyError, ValueError):
            continue

        ele_val: Optional[float] = None
        time_str: Optional[str] = None
        speed_ms: Optional[float] = None

        for child in elem.iter():
            cname = local_tag(child.tag)
            if child is elem or not child.text:
                continue
            txt = child.text.strip()
            if not txt:
                continue
            if cname == "ele":
                try:
                    ele_val = float(txt)
                except ValueError:
                    pass
            elif cname == "time" and time_str is None:
                time_str = txt
            elif cname == "speed":
                try:
                    speed_ms = float(txt)
                except ValueError:
                    pass

        time_ms = parse_iso_ms(time_str)
        points.append({
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "ele": round(ele_val, 1) if ele_val is not None else None,
            "time": time_str,
            "time_ms": time_ms,
            "spd": round(speed_ms, 3) if speed_ms is not None else None,
        })

    # Compute derived speed for tail point if <speed> wasn't emitted by fused/network provider
    if len(points) >= 2:
        last = points[-1]
        if last["spd"] is None:
            prev = points[-2]
            if last["time_ms"] and prev["time_ms"]:
                dt_s = (last["time_ms"] - prev["time_ms"]) / 1000.0
                if 3.0 <= dt_s <= 900.0:
                    dist_m = haversine_km(prev["lat"], prev["lon"], last["lat"], last["lon"]) * 1000.0
                    last["spd"] = round(min(45.0, dist_m / dt_s), 3)
        if last["spd"] is None:
            last["spd"] = 0.0
    elif len(points) == 1 and points[0]["spd"] is None:
        points[0]["spd"] = 0.0

    return points


def find_latest_gpx_for_role() -> Dict[str, Tuple[Path, str, List[Dict]]]:
    best_by_role: Dict[str, Tuple[int, float, Path, str, List[Dict]]] = {}

    for role, folder, label in GPX_SOURCES:
        if not folder.exists():
            continue
        gpx_files = sorted(folder.glob("*.gpx"), key=lambda p: p.stat().st_mtime, reverse=True)
        for gpx_file in gpx_files[:3]:
            try:
                pts = parse_gpx_file(gpx_file)
            except Exception:
                continue
            if not pts:
                continue
            mtime = gpx_file.stat().st_mtime
            last_ms = pts[-1].get("time_ms") or int(mtime * 1000)
            prev = best_by_role.get(role)
            if prev is None or (last_ms, mtime) > (prev[0], prev[1]):
                best_by_role[role] = (last_ms, mtime, gpx_file, label, pts)
            break

    return {
        role: (item[2], item[3], item[4])
        for role, item in best_by_role.items()
    }


def load_cursor() -> dict:
    if CURSOR_PATH.exists():
        try:
            return json.loads(CURSOR_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cursor(cursor: dict) -> None:
    CURSOR_PATH.write_text(json.dumps(cursor, indent=2), encoding="utf-8")


def sync_once(dry_run: bool = False, force_live: bool = False) -> None:
    ensure_drop_folders()
    latest = find_latest_gpx_for_role()
    if not latest:
        print("[GPX Sync] No active .gpx files found in watched folders.")
        return

    cursor = load_cursor()
    cfg = {}
    if not dry_run:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"Missing {CONFIG_PATH}. Run scripts/deploy_c2k_relay.py first.")
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    now_ms = int(time.time() * 1000)
    for role, (gpx_path, source_label, pts) in latest.items():
        tail_pt = pts[-1]
        fix_ms = tail_pt.get("time_ms") or int(gpx_path.stat().st_mtime * 1000)
        age_mins = max(0.0, (now_ms - fix_ms) / 60000.0)
        speed_kmh = round(float(tail_pt.get("spd") or 0.0) * 3.6, 1)

        if dry_run:
            print(
                f"[DRY RUN] role={role} | file={gpx_path} | points={len(pts)} | "
                f"lat={tail_pt['lat']} lon={tail_pt['lon']} ele={tail_pt.get('ele')}m | "
                f"speed={speed_kmh} km/h | fix_time={tail_pt.get('time')} ({age_mins:.1f}m ago)"
            )
            continue

        prev_entry = cursor.get(role) or {}
        if prev_entry.get("last_fix_ms") == fix_ms and prev_entry.get("file") == str(gpx_path):
            print(f"[GPX Sync] role={role} unchanged ({gpx_path.name}, fix {tail_pt.get('time')})")
            continue

        slice_pts = [
            {
                "lat": p["lat"],
                "lon": p["lon"],
                "ele": p.get("ele"),
                "spd": p.get("spd") or 0.0,
                "time": p.get("time"),
            }
            for p in pts[-25:]
        ]
        payload = {
            "action": "c2k-gpx-ingest",
            "key": cfg["ingest_key"],
            "role": role,
            "source": f"{source_label} ({gpx_path.name})",
            "points": slice_pts,
            "forceLive": "1" if force_live else "",
        }
        resp = requests.post(cfg["relay_url"], json=payload, timeout=15)
        resp.raise_for_status()
        res_json = resp.json()
        if res_json.get("error"):
            print(f"[GPX Sync Error] role={role}: {res_json}")
            continue

        cursor[role] = {
            "file": str(gpx_path),
            "last_fix_ms": fix_ms,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        save_cursor(cursor)
        print(
            f"[GPX Sync OK] role={role} | file={gpx_path.name} | pushed={len(slice_pts)} pts | "
            f"lat={tail_pt['lat']} lon={tail_pt['lon']} speed={speed_kmh} km/h | relay={res_json.get('skipped') or 'updated'}"
        )


def main():
    parser = argparse.ArgumentParser(description="Coast to Kosciuszko Cloud GPX Folder Sync")
    parser.add_argument("--dry-run", action="store_true", help="Parse latest .gpx files without posting")
    parser.add_argument("--once", action="store_true", help="Push latest updates once and exit")
    parser.add_argument("--watch", action="store_true", help="Poll Drive GPX folders continuously")
    parser.add_argument("--interval", type=int, default=20, help="Watch interval in seconds (default: 20)")
    parser.add_argument("--force-live", action="store_true", help="Also flip relay raceStatus to LIVE_RACE")
    args = parser.parse_args()

    if args.dry_run:
        sync_once(dry_run=True)
    elif args.watch:
        print(f"[GPX Sync] Watching Google Drive GPX folders every {args.interval}s (Ctrl+C to stop)...")
        while True:
            try:
                sync_once(dry_run=False, force_live=args.force_live)
            except Exception as exc:
                print(f"[GPX Sync Warning] {exc}")
            time.sleep(max(5, args.interval))
    else:
        sync_once(dry_run=False, force_live=args.force_live)


if __name__ == "__main__":
    main()
