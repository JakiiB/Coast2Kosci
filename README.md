# Coast to Kosci (C2K) 2026 - 3D Live Broadcast Map & Master Race Database

This workspace houses both the **3D Live Broadcast Map App** (at `https://jakiib.github.io/Coast2Kosci/`) and the comprehensive **2026 Official Race Logistics Database** compiled from [coasttokosci.com](https://coasttokosci.com), the 2026 Runners Guide, 2026 Race Schedule, Race Rules, Course Directions, RideWithGPS Routes (#41169431 & #41169434 Cow Bail Trail), TrackMeLive 2026, and the Australian Government National Public Toilet Map.

## 3D Live Broadcast Map App (`index.html` & `src/`)

- **Entry Point & Live URL:** `index.html` (live at `https://jakiib.github.io/Coast2Kosci/`) powered by `data/c2k_course_bundle.js`, `src/hybridThreeStage.js`, `src/terrainEngine.js`, `src/telemetryClient.js`, `src/broadcastHud.js`, `src/weatherClouds3D.js`, and `src/app.js`
- **Auto-Hybrid 3D Broadcast Engine:** Launches into the pre-baked Three.js 3D corridor mesh (`assets/corridor/`) below zoom `12.2` for fast boot and smooth whole-course orbiting, then seamlessly crossfades to MapLibre GL 3D Google Street Satellite terrain when zoomed in at zoom `>= 12.2`
- **Official Toilets & Community Aid Layer:** Toggleable `Toilets & Aid` 3D beacons & elevation ticks, dual `Next Toilet/Aid` live readouts on Simon's and Crew Car's cards, dedicated `Toilets & Aid` panel / mobile sheet, and 1-tap stop detail modal with official 2026 rules, cash-only alerts, and Google Maps driving links
- **6-Gate 2026 Cut-Off Engine:** All 6 official 2026 gates (`CP3 Cathcart 12h`, `CP4 Gunningrah 18h`, `CP5 Dalgety 25h`, `CP6 Jindabyne 32.5h`, `CP8 Charlotte Pass 41.5h`, `Finish 46h`), live 1-second Hero Countdown Card, objective minimum pace needed, terrain- and fatigue-adjusted projected buffer, auto-locked live gate splits (`localStorage`), silent warning banner (< 60m buffer), and moving 46h Cut-Off Sweeper wave on the elevation profile

## Cloud Remote Agent Workflow (Laptop Closed)

The full project workspace (app, `assets/corridor/`, build/verification scripts, Excel/HTML/CSV race databases, and official PDFs/GPX) is hosted on the `main` branch of `https://github.com/JakiiB/Coast2Kosci.git`, while `gh-pages` serves the clean static production app. Private relay credentials stay strictly excluded via `.gitignore` and live in Google Drive `_Cloud_Toolkit/.tokens/cloud_keys.json`.

- **Clone in a fresh Cloud Remote Agent container:**
  ```bash
  git clone https://github.com/JakiiB/Coast2Kosci.git /tmp/Coast2Kosci && cd /tmp/Coast2Kosci
  ```
- **Verify, sync `main`, and deploy `gh-pages` from Linux Cloud or Windows (`KINOVO`):**
  ```bash
  python3 scripts/publish_cloud.py -m "Describe update"
  ```
- **Windows wrapper (`KINOVO`):** `scripts/publish_github_pages.ps1` forwards directly to `scripts/publish_cloud.py`. See `AGENTS.md` for full cloud agent instructions.

## Primary Database Files

- **Excel Master Workbook:** `Coast2Kosci_2026_Master_Database.xlsx` (6 formatted, filterable sheets with clickable Google Maps links)
- **Offline Interactive HTML Explorer:** `Coast2Kosci_2026_Interactive_Database.html` (works 100% offline with search, filter pills, SVG elevation profile, and live pace / cut-off buffer calculator)
- **Unified JSON Database:** `data/c2k_2026_master_database.json`
- **GPS Route & Waypoints (GPX):** `official_docs/CoastToKosci_2026_Course_Route_With_Waypoints.gpx` (25 race waypoints + 12,191 elevation track points)

## Normalized CSV Tables (`data/`)

1. `data/01_master_course_waypoints.csv` - 25 key waypoints from 0.0 km (Boydtown Beach) to 240.65 km (Charlotte Pass Finish)
2. `data/02_checkpoints_and_cutoffs.csv` - Start, all 8 mandatory checkpoints, Mt Kosciuszko Summit, Finish, and all 6 hard cut-offs
3. `data/03_toilets_and_aid_stations.csv` - Complete toilet, water, store, and community aid stop matrix (including Boydtown no-toilet penalty, Dalgety runner-vs-crew split, and 24h corridor toilets)
4. `data/04_course_legs_and_directions.csv` - All 61 official RideWithGPS turn cues with road surfaces, leg rules, and marshal crossing notes
5. `data/05_rules_gear_crew_pacers.csv` - Categorized database of mandatory runner gear, 14-item Summit Path gear, pacing windows, vehicle rules (max 5.5m, no campervans, 40 km/h limit), and emergency contacts
6. `data/06_2026_event_schedule.csv` - Full 2026 Race Week & Weekend schedule in AEDT

## Official Source Documents (`official_docs/`)

Includes downloaded PDFs from `coasttokosci.com`, notably `2026-Runners-Guide-3.pdf`, `2026-Coast-To-Kosci-Race-Schedule.pdf`, `2025-Coast-To-Kosci-Race-Rules.pdf`, `Course-Directions-1.pdf`, `Updated-Course-Directions-1.pdf`, `2026-Race-Waiver.pdf`, and `map-overview.png`.
