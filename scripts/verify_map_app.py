import json
import re
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
node = shutil.which("node")
js_files = [
    "src/app.js",
    "src/broadcastHud.js",
    "src/hybridThreeStage.js",
    "src/terrainEngine.js",
    "src/telemetryClient.js",
    "src/weatherClouds3D.js",
    "data/c2k_course_bundle.js",
]
if node:
    for f in js_files:
        r = subprocess.run([node, "--check", str(root / f)], capture_output=True, text=True)
        assert r.returncode == 0, f"Syntax err in {f}: {r.stderr}"
        print("node --check OK:", f)
else:
    print("node not on PATH - skipping node --check")

course = json.loads((root / "data/c2k_course.json").read_text(encoding="utf-8"))
assert len(course["cutoff_gates"]) == 6, f"Expected 6 gates, got {len(course['cutoff_gates'])}"
assert len(course["toilets_aid"]) == 11, f"Expected 11 official stops, got {len(course['toilets_aid'])}"
print("Verified course JSON:", len(course["cutoff_gates"]), "gates,", len(course["toilets_aid"]), "stops,", len(course["track"]), "track pts")

html = (root / "index.html").read_text(encoding="utf-8")
required_ids = [
    "toggle-toilets",
    "btn-panel-toggle-toilets",
    "r-next-toilet-row",
    "r-next-toilet",
    "c-next-toilet-row",
    "c-next-toilet",
    "cutoff-alert-banner",
    "cutoff-hero-card",
    "cutoff-gates-list",
    "toilets-aid-panel",
    "toilets-aid-list",
    "stop-detail-modal",
    "btn-close-stop-detail",
    "stop-detail-title",
    "btn-stop-fly",
    "btn-stop-gmaps",
    "relief-slider",
    "btn-drag-mode",
    "btn-compass-reset",
    "drawer-cutoffs",
    "drawer-weather",
    "drawer-telemetry",
    "live-readout-strip",
    "three-corridor-stage",
    "three-corridor-canvas",
    "three-beacon-overlay",
    "hybrid-engine-badge",
    "left-telemetry-dock",
    "right-broadcast-dock",
    "btn-collapse-left-dock",
    "btn-expand-left-dock",
    "btn-collapse-right-dock",
    "btn-expand-right-dock",
    "btn-toggle-all-hud",
    "mob-summary-text",
]
for rid in required_ids:
    assert f'id="{rid}"' in html, f"Missing DOM id in index.html: {rid}"
print(f"Verified all {len(required_ids)} DOM IDs present in index.html")

assert "diorama/" not in html, "Unexpected diorama/ link still present in index.html"
hybrid_js = (root / "src/hybridThreeStage.js").read_text(encoding="utf-8")
assert "diorama/" not in hybrid_js, "Unexpected diorama/ asset path still present in src/hybridThreeStage.js"

for asset_name in ["height.png", "sat-2k.jpg", "sat-4k.jpg", "sat-6k.jpg", "relief-4k.jpg", "meta.json"]:
    p = root / "assets/corridor" / asset_name
    assert p.exists() and p.stat().st_size > 100, f"Missing or empty corridor asset: {p}"
print("Verified all 6 pre-baked assets/corridor assets present and zero diorama/ links remain")

dash_targets = [
    root / "README.md",
    root / "AGENTS.md",
    root / "index.html",
    root / "src/styles.css",
    root / "src/broadcastHud.js",
    root / "src/hybridThreeStage.js",
    root / "src/terrainEngine.js",
    root / "src/telemetryClient.js",
    root / "src/weatherClouds3D.js",
    root / "src/app.js",
    root / "scripts/bake_diorama_assets.py",
    root / "scripts/publish_cloud.py",
]
for chk in dash_targets:
    txt = chk.read_text(encoding="utf-8")
    assert "\u2013" not in txt and "\u2014" not in txt, f"Unicode dash found in {chk}"
print("Zero en/em dashes verified across README, AGENTS, root, src, and scripts!")

# Git ignore and secret scan checks
if (root / ".git").exists() and shutil.which("git"):
    for private_rel in ["data/c2k_relay_config.json", "docs/macrodroid_gpslogger_setup.md"]:
        ig = subprocess.run(["git", "check-ignore", "-q", private_rel], cwd=str(root))
        assert ig.returncode == 0, f"Private file is NOT gitignored: {private_rel}"
    print("Verified private relay files are properly ignored by git.")

token_pattern = re.compile(r"(gho_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})")
local_ingest_key = ""
relay_cfg_path = root / "data" / "c2k_relay_config.json"
if relay_cfg_path.exists():
    try:
        local_ingest_key = str(json.loads(relay_cfg_path.read_text(encoding="utf-8")).get("ingest_key") or "")
    except Exception:
        local_ingest_key = ""

scan_files = [
    root / "README.md",
    root / "AGENTS.md",
    root / "index.html",
    *sorted((root / "src").glob("*")),
    *sorted((root / "scripts").glob("*")),
]
for sf in scan_files:
    if not sf.is_file():
        continue
    content = sf.read_text(encoding="utf-8", errors="ignore")
    assert not token_pattern.search(content), f"GitHub token pattern found in {sf}"
    if local_ingest_key:
        assert local_ingest_key not in content, f"Private C2K ingest key found in {sf}"
print("Secret scan clean across README, AGENTS, index.html, src/*, and scripts/*.")
