r"""
Coast to Kosciuszko (C2K) - Google Drive Cloud GPX Folder Sync
Watches Jake's live GPSLogger Google Drive folder (G:\My Drive\GPSLogger for Android
on Windows, or via gdrive CLI on Cloud Remote Agents) plus dedicated Coast2Kosci
gpx_drop/crew and gpx_drop/simon folders, parses the newest .gpx trackpoints, and
pushes authenticated updates to the 24/7 Cloud Relay.

Usage:
  python3 scripts/sync_gpx_folder.py --dry-run
  python3 scripts/sync_gpx_folder.py --once
  python3 scripts/sync_gpx_folder.py --watch --interval 20
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_PATH = DATA_DIR / "c2k_relay_config.json"
CURSOR_PATH = DATA_DIR / "gpx_sync_cursor.json"

DRIVE_GPSLOGGER_FOLDER_ID = "1UzM5zhTpfrCRfE530q_5u5yuG0J81sHG"
DRIVE_GPX_DROP_CREW_ID = "1qXICksjmsk4VFXRfDmFQPIffzdVYw5Y5"
DRIVE_GPX_DROP_SIMON_ID = "1cP5fOMpIXBJmAzGcn1lZsrQf9II_8ttI"

GPX_SOURCES = [
    ("crew", Path(r"G:\My Drive\GPSLogger for Android"), "GPSLogger Drive GPX"),
    ("crew", ROOT_DIR / "gpx_drop" / "crew", "Crew GPX Drop Folder"),
    ("runner", ROOT_DIR / "gpx_drop" / "simon", "Simon GPX Drop Folder"),
]

CLOUD_DRIVE_SOURCES = [
    ("crew", DRIVE_GPSLOGGER_FOLDER_ID, "GPSLogger Drive GPX"),
    ("crew", DRIVE_GPX_DROP_CREW_ID, "Crew GPX Drop Folder"),
    ("runner", DRIVE_GPX_DROP_SIMON_ID, "Simon GPX Drop Folder"),
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
    for idx in range(1, len(points)):
        curr = points[idx]
        if curr["spd"] is None:
            prev = points[idx - 1]
            if curr["time_ms"] and prev["time_ms"]:
                dt_s = (curr["time_ms"] - prev["time_ms"]) / 1000.0
                if 3.0 <= dt_s <= 900.0:
                    dist_m = haversine_km(prev["lat"], prev["lon"], curr["lat"], curr["lon"]) * 1000.0
                    curr["spd"] = round(min(45.0, dist_m / dt_s), 3)
        if curr["spd"] is None:
            curr["spd"] = 0.0
    if len(points) == 1 and points[0]["spd"] is None:
        points[0]["spd"] = 0.0

    return points


def _fetch_cloud_drive_gpx_candidates() -> List[Tuple[str, Path, str]]:
    """When local Google Drive mount is absent, pull newest .gpx files via gdrive CLI."""
    gdrive_bin = shutil.which("gdrive")
    if not gdrive_bin:
        return []

    cache_root = Path(tempfile.gettempdir()) / "c2k_gpx_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    downloaded: List[Tuple[str, Path, str]] = []

    for role, folder_id, label in CLOUD_DRIVE_SOURCES:
        res = subprocess.run(
            [gdrive_bin, "readonly", "ls", folder_id, "--max", "500", "--json"],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0 or not res.stdout.strip():
            continue
        try:
            payload = json.loads(res.stdout)
        except Exception:
            continue
        items = payload if isinstance(payload, list) else payload.get("files") or payload.get("items") or []
        gpx_items = [
            it for it in items
            if isinstance(it, dict) and str(it.get("name", "")).lower().endswith(".gpx")
        ]
        if not gpx_items:
            continue
        gpx_items.sort(
            key=lambda it: (str(it.get("modifiedTime") or ""), str(it.get("name") or "")),
            reverse=True,
        )
        top = gpx_items[0]
        file_id = str(top.get("id") or "").strip()
        file_name = str(top.get("name") or "latest.gpx").strip()
        if not file_id:
            continue
        role_dir = cache_root / f"{role}_{folder_id[:8]}"
        role_dir.mkdir(parents=True, exist_ok=True)
        out_path = role_dir / file_name
        dl = subprocess.run(
            [gdrive_bin, "readonly", "download", file_id, "--out", str(out_path)],
            capture_output=True,
            text=True,
        )
        if dl.returncode == 0 and out_path.exists():
            mod_ms = parse_iso_ms(str(top.get("modifiedTime") or ""))
            if mod_ms:
                mod_sec = mod_ms / 1000.0
                try:
                    os.utime(out_path, (mod_sec, mod_sec))
                except Exception:
                    pass
            downloaded.append((role, out_path, label))

    return downloaded


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

    if not GPX_SOURCES[0][1].exists():
        for role, gpx_file, label in _fetch_cloud_drive_gpx_candidates():
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

    return {
        role: (item[2], item[3], item[4])
        for role, item in best_by_role.items()
    }


def load_relay_credentials() -> Dict[str, str]:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if cfg.get("relay_url") and cfg.get("ingest_key"):
                return {
                    "relay_url": str(cfg["relay_url"]).strip(),
                    "ingest_key": str(cfg["ingest_key"]).strip(),
                }
        except Exception:
            pass

    env_url = os.environ.get("C2K_RELAY_URL", "").strip()
    env_key = os.environ.get("C2K_INGEST_KEY", "").strip()
    if env_url and env_key:
        return {"relay_url": env_url, "ingest_key": env_key}

    # Cloud Remote Agent fallback: load C2K_RELAY_URL + C2K_INGEST_KEY from cloud_keys.json via gdrive
    gdrive_bin = shutil.which("gdrive")
    if gdrive_bin:
        tmp_dir = Path(tempfile.gettempdir()) / "c2k_keys_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = tmp_dir / "cloud_keys.json"
        try:
            res = subprocess.run(
                [gdrive_bin, "readonly", "search", "--name-exact", "cloud_keys.json", "--json"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                payload = json.loads(res.stdout)
                items = payload if isinstance(payload, list) else payload.get("files") or payload.get("items") or []
                matches = [it for it in items if isinstance(it, dict) and it.get("name") == "cloud_keys.json"]
                if matches:
                    fid = str(matches[0].get("id") or "").strip()
                    if fid:
                        dl = subprocess.run(
                            [gdrive_bin, "readonly", "download", fid, "--out", str(tmp_file)],
                            capture_output=True,
                            text=True,
                        )
                        if dl.returncode == 0 and tmp_file.exists():
                            ck = json.loads(tmp_file.read_text(encoding="utf-8"))
                            r_url = str(ck.get("C2K_RELAY_URL") or "").strip()
                            r_key = str(ck.get("C2K_INGEST_KEY") or "").strip()
                            if r_url and r_key:
                                return {"relay_url": r_url, "ingest_key": r_key}
        except Exception:
            pass
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    raise FileNotFoundError(
        f"Missing {CONFIG_PATH} and cloud_keys.json C2K credentials. Run scripts/deploy_c2k_relay.py first."
    )


def post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "C2K-GPX-Sync/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


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
        print("[GPX Sync] No active .gpx files found in watched local or Google Drive folders.")
        return

    cursor = load_cursor()
    cfg = {}
    if not dry_run:
        cfg = load_relay_credentials()

    now_ms = int(time.time() * 1000)
    for role, (gpx_path, source_label, pts) in latest.items():
        tail_pt = pts[-1]
        fix_ms = tail_pt.get("time_ms") or int(gpx_path.stat().st_mtime * 1000)
        age_mins = max(0.0, (now_ms - fix_ms) / 60000.0)
        speed_kmh = round(float(tail_pt.get("spd") or 0.0) * 3.6, 1)

        if dry_run:
            print(
                f"[DRY RUN] role={role} | file={gpx_path.name} ({source_label}) | points={len(pts)} | "
                f"lat={tail_pt['lat']} lon={tail_pt['lon']} ele={tail_pt.get('ele')}m | "
                f"speed={speed_kmh} km/h | fix_time={tail_pt.get('time')} ({age_mins:.1f}m ago)"
            )
            continue

        prev_entry = cursor.get(role) or {}
        if prev_entry.get("last_fix_ms") == fix_ms and prev_entry.get("file") == gpx_path.name:
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
        res_json = post_json(cfg["relay_url"], payload, timeout=20)
        if res_json.get("error"):
            print(f"[GPX Sync Error] role={role}: {res_json}")
            continue

        cursor[role] = {
            "file": gpx_path.name,
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
