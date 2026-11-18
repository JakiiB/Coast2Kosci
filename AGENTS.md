# Coast2Kosci Workspace Guide & Cloud Remote Agent Instructions

## Cloud Remote Agent Workflow (Laptop Closed)

When working from an Antigravity Cloud Remote Agent while `KINOVO` is powered off:

1. **Clone or Sync Full Workspace (`main` branch):**
   ```bash
   git clone https://github.com/JakiiB/Coast2Kosci.git /tmp/Coast2Kosci && cd /tmp/Coast2Kosci
   ```
   Always run `git pull --ff-only origin main` before making edits so cloud and desktop sessions stay in lockstep.

2. **Pull Private Cloud Credentials When Needed:**
   Private GitHub deploy auth (`GITHUB_TOKEN`) and C2K relay credentials (`C2K_RELAY_URL`, `C2K_INGEST_KEY`, `C2K_CREW_PIN`) live inside `_Cloud_Toolkit/.tokens/cloud_keys.json` on personal Google Drive (`jakiib@gmail.com`). Download `_Cloud_Toolkit` into `/tmp/cloud_toolkit/` using `gdrive`, or let `scripts/publish_cloud.py` fetch `cloud_keys.json` automatically via `gdrive`.

3. **Verify, Sync `main`, and Deploy Live `gh-pages` in One Command:**
   ```bash
   python3 scripts/publish_cloud.py -m "Describe your change"
   ```
   This single cross-platform Python command runs `scripts/verify_map_app.py`, enforces the Secret Leak Guard, pushes changes back to `origin/main`, and deploys the clean production web bundle to `gh-pages` (`https://jakiib.github.io/Coast2Kosci/`). Never write tokens into `.git/config` or any file inside the repository.

---

## Architecture & Guardrails

- **Single Unified Live App:** The only active web tracker lives at the repository root (`index.html` + `src/`) and deploys to `https://jakiib.github.io/Coast2Kosci/`. Never recreate or re-link a separate `/diorama/` app.
- **Auto-Hybrid 3D Engine:**
  - `src/hybridThreeStage.js` renders the pre-baked Three.js 3D corridor mesh from `assets/corridor/` (`height.png`, `sat-2k.jpg`, `sat-4k.jpg`, `sat-6k.jpg`, `relief-4k.jpg`, `meta.json`) below zoom `12.2` for fast load and smooth whole-course orbiting.
  - `src/terrainEngine.js` renders MapLibre GL 3D Google Street Satellite terrain when zoomed in at zoom `>= 12.2`.
  - `src/broadcastHud.js`, `src/telemetryClient.js`, `src/weatherClouds3D.js`, `src/app.js`, and `src/styles.css` power the Broadcast HUD, 6-gate cut-offs, Toilets & Aid Stops, Weather Simulator, and live relay client.
- **Synchronized Course Data:** Always keep `data/c2k_course.json` and `data/c2k_course_bundle.js` synchronized via `python3 scripts/build_course_bundle.py`.
- **Never Commit Private Credentials:** `data/c2k_relay_config.json`, `docs/macrodroid_gpslogger_setup.md`, `.tokens/`, and `*.env` must stay gitignored.
- **Punctuation Rule:** Never use Unicode en dash or em dash characters anywhere in docs, copy, UI labels, or commit messages; always use a standard hyphen with spaces (` - `).
