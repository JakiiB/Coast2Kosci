"""
Coast to Kosciuszko (C2K) - 24/7 Live Telemetry Cloud Relay Deployer
Deploys the Google Apps Script telemetry relay for Simon (Runner) and Jake's Crew Car,
supporting:
  1. Authenticated HTTP GET/POST pings from GPSLogger for Android / MacroDroid (&key=...)
  2. Authenticated GPX track ingestion (action=c2k-gpx-ingest) from Google Drive GPX sync & web upload
  3. 1-Tap Crew Check-In override from the mobile 3D web UI (with Crew PIN)
  4. Quota-safe PropertiesService storage (C2K_STATE_CORE < 2 KB + ring buffers + CacheService trail)
  5. Standalone Apps Script project isolation (with safe verified fallback if Google requires 1st-run UI consent)
"""

import os
import sys
import json
import secrets
import subprocess
import requests
from pathlib import Path

sys.path.append(r"H:\My Drive\Antigravity Project Space\Finance\scripts")
from personal_apps_script import PersonalAppsScriptManager

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_PATH = DATA_DIR / "c2k_relay_config.json"

SHARED_SCRIPT_ID = "1oKgzMNs10DDzSXQR0gMIr21TApRbQkVX6JOXRiPMA7fkWk35NGw4Y5n9"
SHARED_DEPLOYMENT_ID = "AKfycbzPJCgIpQKUSTQj6JFX4D05fHb1Rj1ErdM-uznSzPm7AcS7Le0e-34NA8TEuZq_koSv5w"
DND_ROOT = Path(r"H:\My Drive\Antigravity Project Space\The Ballad of the Seasoners")


def load_or_create_secrets() -> tuple[dict, str, str]:
    existing = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    ingest_key = str(existing.get("ingest_key") or "").strip() or secrets.token_urlsafe(18)
    crew_pin = str(existing.get("crew_pin") or "").strip() or "2228"
    return existing, ingest_key, crew_pin


def build_c2k_core_js(ingest_key: str, crew_pin: str) -> str:
    return f"""
const DEFAULT_C2K_INGEST_KEY = {json.dumps(ingest_key)};
const DEFAULT_C2K_CREW_PIN = {json.dumps(crew_pin)};
const C2K_CACHE_TTL = 21600; // 6 hours
const C2K_MAX_PROP_CHARS = 7800; // Stay safely under Apps Script 9 KB per-property quota

const DEFAULT_C2K_CORE = {{
  raceStatus: "PRE_RACE_SIM", // PRE_RACE_SIM | LIVE_RACE | FINISHED
  raceStartIso: "2026-11-20T05:30:00+11:00",
  externalTrackerUrl: "https://live.trackmelive.com.au/coasttokosci26/?search=43",
  runner: {{
    name: "Jesse Simon",
    bib: "43",
    lat: -37.092052,
    lon: 149.872263,
    ele_m: 4.0,
    course_km: 0.0,
    speed_kmh: 0.0,
    battery_pct: 100,
    source: "Pre-Race Baseline (Boydtown Beach)",
    epistemic: "PRE_RACE_BASELINE",
    note: "Ready at Boydtown Beach Start Line",
    fix_time: 0,
    updated_at: 0
  }},
  crew: {{
    name: "Crew Car (Jake)",
    lat: -37.092250,
    lon: 149.871950,
    ele_m: 5.0,
    course_km: 0.0,
    speed_kmh: 0.0,
    battery_pct: 100,
    source: "Pre-Race Baseline (Boydtown Beach)",
    epistemic: "PRE_RACE_BASELINE",
    note: "Support Crew staged at Boydtown Beach",
    fix_time: 0,
    updated_at: 0
  }}
}};

function getC2KIngestKey() {{
  const props = PropertiesService.getScriptProperties();
  const saved = props.getProperty('C2K_INGEST_KEY');
  if (saved) return String(saved).trim();
  props.setProperty('C2K_INGEST_KEY', DEFAULT_C2K_INGEST_KEY);
  return DEFAULT_C2K_INGEST_KEY;
}}

function getC2KCrewPin() {{
  const props = PropertiesService.getScriptProperties();
  const saved = props.getProperty('C2K_CREW_PIN');
  if (saved) return String(saved).trim();
  props.setProperty('C2K_CREW_PIN', DEFAULT_C2K_CREW_PIN);
  return DEFAULT_C2K_CREW_PIN;
}}

function isC2KAuthorized(data, requirePinOnly) {{
  const pin = String((data && data.pin) || '').trim();
  if (pin && pin === getC2KCrewPin()) return true;
  if (requirePinOnly) return false;
  const key = String((data && data.key) || '').trim();
  if (key && key === getC2KIngestKey()) return true;
  return false;
}}

function parsePropJsonArray(props, key) {{
  try {{
    const raw = props.getProperty(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  }} catch (e) {{
    return [];
  }}
}}

function saveBoundedPropArray(props, key, arr, maxLen) {{
  let list = Array.isArray(arr) ? arr.slice(-maxLen) : [];
  let encoded = JSON.stringify(list);
  while (encoded.length > C2K_MAX_PROP_CHARS && list.length > 1) {{
    list = list.slice(Math.ceil(list.length / 2));
    encoded = JSON.stringify(list);
  }}
  props.setProperty(key, encoded);
  return list;
}}

function getC2KState() {{
  const props = PropertiesService.getScriptProperties();
  const cache = CacheService.getScriptCache();
  let state = JSON.parse(JSON.stringify(DEFAULT_C2K_CORE));

  try {{
    const rawCore = props.getProperty('C2K_STATE_CORE');
    if (rawCore) {{
      const saved = JSON.parse(rawCore);
      if (saved.raceStatus) state.raceStatus = saved.raceStatus;
      if (saved.raceStartIso) state.raceStartIso = saved.raceStartIso;
      if (saved.externalTrackerUrl !== undefined && saved.externalTrackerUrl !== 'https://live.trackmelive.com.au/') {{
        state.externalTrackerUrl = saved.externalTrackerUrl;
      }}
      if (saved.runner) {{
        state.runner = Object.assign(state.runner, saved.runner);
        if (!state.runner.name || state.runner.name === 'Simon') state.runner.name = DEFAULT_C2K_CORE.runner.name;
        if (!state.runner.bib || state.runner.bib === 'C2K') state.runner.bib = DEFAULT_C2K_CORE.runner.bib;
      }}
      if (saved.crew) state.crew = Object.assign(state.crew, saved.crew);
    }} else {{
      // One-time migration from legacy C2K_TELEMETRY_STATE if present
      const legacyRaw = props.getProperty('C2K_TELEMETRY_STATE');
      if (legacyRaw) {{
        const legacy = JSON.parse(legacyRaw);
        if (legacy.raceStatus) state.raceStatus = legacy.raceStatus;
        if (legacy.externalTrackerUrl !== undefined && legacy.externalTrackerUrl !== 'https://live.trackmelive.com.au/') {{
          state.externalTrackerUrl = legacy.externalTrackerUrl;
        }}
        if (legacy.runner) {{
          state.runner = Object.assign(state.runner, legacy.runner);
          if (!state.runner.name || state.runner.name === 'Simon') state.runner.name = DEFAULT_C2K_CORE.runner.name;
          if (!state.runner.bib || state.runner.bib === 'C2K') state.runner.bib = DEFAULT_C2K_CORE.runner.bib;
        }}
        if (legacy.crew) state.crew = Object.assign(state.crew, legacy.crew);
      }}
    }}
  }} catch (e) {{}}

  state.checkins = parsePropJsonArray(props, 'C2K_CHECKINS_RING');
  let trail = null;
  try {{
    const cachedTrail = cache.get('C2K_TRAIL_CACHE');
    if (cachedTrail) trail = JSON.parse(cachedTrail);
  }} catch (e) {{}}
  if (!Array.isArray(trail)) {{
    trail = parsePropJsonArray(props, 'C2K_TRAIL_TAIL');
  }}
  state.trail = trail;
  state.server_time = Date.now();
  return state;
}}

function sanitizePublicC2KState(state) {{
  const copy = JSON.parse(JSON.stringify(state));
  delete copy.crewPinHash;
  delete copy.ingestKey;
  return copy;
}}

function saveC2KCore(coreState) {{
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {{
    const props = PropertiesService.getScriptProperties();
    const compactCore = {{
      raceStatus: coreState.raceStatus || 'PRE_RACE_SIM',
      raceStartIso: coreState.raceStartIso || DEFAULT_C2K_CORE.raceStartIso,
      externalTrackerUrl: coreState.externalTrackerUrl || DEFAULT_C2K_CORE.externalTrackerUrl,
      runner: coreState.runner || DEFAULT_C2K_CORE.runner,
      crew: coreState.crew || DEFAULT_C2K_CORE.crew
    }};
    props.setProperty('C2K_STATE_CORE', JSON.stringify(compactCore));
    return compactCore;
  }} finally {{
    lock.releaseLock();
  }}
}}

function appendC2KTrailPoints(newTuples) {{
  if (!Array.isArray(newTuples) || !newTuples.length) return;
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {{
    const props = PropertiesService.getScriptProperties();
    const cache = CacheService.getScriptCache();
    let tail = parsePropJsonArray(props, 'C2K_TRAIL_TAIL');
    let fullTrail = null;
    try {{
      const cachedRaw = cache.get('C2K_TRAIL_CACHE');
      if (cachedRaw) fullTrail = JSON.parse(cachedRaw);
    }} catch (e) {{}}
    if (!Array.isArray(fullTrail)) fullTrail = tail.slice();

    for (let i = 0; i < newTuples.length; i++) {{
      const pt = newTuples[i];
      tail.push(pt);
      fullTrail.push(pt);
    }}
    saveBoundedPropArray(props, 'C2K_TRAIL_TAIL', tail, 50);
    if (fullTrail.length > 300) {{
      fullTrail = fullTrail.slice(fullTrail.length - 300);
    }}
    cache.put('C2K_TRAIL_CACHE', JSON.stringify(fullTrail), C2K_CACHE_TTL);
  }} finally {{
    lock.releaseLock();
  }}
}}

function parseFixTimeMs(rawTime, fallbackMs) {{
  if (rawTime === undefined || rawTime === null || rawTime === '') return fallbackMs;
  if (typeof rawTime === 'number' && !isNaN(rawTime)) {{
    return rawTime < 10000000000 ? Math.round(rawTime * 1000) : Math.round(rawTime);
  }}
  const num = Number(rawTime);
  if (!isNaN(num) && String(rawTime).trim().length >= 9) {{
    return num < 10000000000 ? Math.round(num * 1000) : Math.round(num);
  }}
  const parsed = Date.parse(String(rawTime));
  return !isNaN(parsed) ? parsed : fallbackMs;
}}

function handleC2KPing(data) {{
  if (!isC2KAuthorized(data, false)) {{
    return {{ error: 'Unauthorized: valid key or pin required.' }};
  }}

  const state = getC2KState();
  const roleRaw = String(data.role || 'crew').toLowerCase();
  const role = (roleRaw === 'runner' || roleRaw === 'simon' || roleRaw === 'jesse') ? 'runner' : 'crew';
  const lat = parseFloat(data.lat);
  const lon = parseFloat(data.lon || data.lng);
  if (isNaN(lat) || isNaN(lon)) {{
    return {{ error: 'Invalid lat/lon in c2k-ping' }};
  }}

  const now = Date.now();
  const fixTimeMs = parseFixTimeMs(data.fix_time || data.time, now);
  const target = (role === 'runner') ? state.runner : state.crew;

  // Out-of-order guard: never let a delayed offline retry overwrite a newer fix
  if (fixTimeMs > 0 && target.fix_time > 0 && fixTimeMs < target.fix_time && String(data.forceOverwrite || '') !== '1') {{
    return {{ success: true, skipped: 'older_fix', role: role, server_time: now }};
  }}

  const ele = !isNaN(parseFloat(data.ele || data.alt)) ? parseFloat(data.ele || data.alt) : null;
  const spdRaw = !isNaN(parseFloat(data.spd || data.speed)) ? parseFloat(data.spd || data.speed) : 0;
  const speedKmh = (data.spd_kmh !== undefined && data.spd_kmh !== '')
    ? Math.round(parseFloat(data.spd_kmh) * 10) / 10
    : Math.round(spdRaw * 3.6 * 10) / 10;
  const bat = !isNaN(parseFloat(data.bat || data.batt)) ? Math.round(parseFloat(data.bat || data.batt)) : null;
  const courseKm = !isNaN(parseFloat(data.course_km)) ? Math.round(parseFloat(data.course_km) * 100) / 100 : null;
  const source = String(data.source || (role === 'runner' ? 'Runner Telemetry Ping' : 'GPSLogger Android Live')).slice(0, 80);
  const note = String(data.note || '').slice(0, 140);

  if (data.name) target.name = String(data.name).trim().slice(0, 60);
  if (role === 'runner' && data.bib) target.bib = String(data.bib).trim().slice(0, 16);
  target.lat = Math.round(lat * 1000000) / 1000000;
  target.lon = Math.round(lon * 1000000) / 1000000;
  if (ele !== null) target.ele_m = Math.round(ele * 10) / 10;
  if (courseKm !== null) target.course_km = courseKm;
  target.speed_kmh = isNaN(speedKmh) ? 0 : speedKmh;
  if (bat !== null) target.battery_pct = Math.max(0, Math.min(100, bat));
  target.source = source;
  target.epistemic = String(data.epistemic || 'CONFIRMED_FIX');
  if (note) target.note = note;
  target.fix_time = fixTimeMs;
  target.updated_at = now;

  // Pre-race safety: only auto-promote PRE_RACE_SIM -> LIVE_RACE within 6h of start or explicit forceLive
  const raceStartMs = Date.parse(state.raceStartIso || DEFAULT_C2K_CORE.raceStartIso);
  if (data.raceStatus) {{
    state.raceStatus = String(data.raceStatus);
  }} else if (state.raceStatus === 'PRE_RACE_SIM') {{
    const forceLive = String(data.forceLive || '') === '1' || data.forceLive === true;
    if (forceLive || (!isNaN(raceStartMs) && now >= raceStartMs - 6 * 3600 * 1000)) {{
      state.raceStatus = 'LIVE_RACE';
    }}
  }}

  saveC2KCore(state);
  appendC2KTrailPoints([[
    Math.round(fixTimeMs / 1000),
    role === 'runner' ? 'r' : 'c',
    Math.round(target.lat * 100000) / 100000,
    Math.round(target.lon * 100000) / 100000
  ]]);

  return {{ success: true, role: role, updated: target, raceStatus: state.raceStatus, server_time: now }};
}}

function extractGpxPointsFromXml(xmlText) {{
  const pts = [];
  if (!xmlText || typeof xmlText !== 'string') return pts;
  const trkptRegex = /<trkpt\\b([^>]*)>([\\s\\S]*?)<\\/trkpt>/gi;
  let match;
  while ((match = trkptRegex.exec(xmlText)) !== null) {{
    const attrs = match[1] || '';
    const inner = match[2] || '';
    const latMatch = /\\blat\\s*=\\s*["']([^"']+)["']/i.exec(attrs);
    const lonMatch = /\\blon\\s*=\\s*["']([^"']+)["']/i.exec(attrs);
    if (!latMatch || !lonMatch) continue;
    const lat = parseFloat(latMatch[1]);
    const lon = parseFloat(lonMatch[1]);
    if (isNaN(lat) || isNaN(lon)) continue;
    const eleMatch = /<ele>\\s*([^<\\s]+)\\s*<\\/ele>/i.exec(inner);
    const timeMatch = /<time>\\s*([^<\\s]+)\\s*<\\/time>/i.exec(inner);
    const spdMatch = /<(?:[a-z0-9_]+:)?speed>\\s*([^<\\s]+)\\s*<\\/speed>/i.exec(inner);
    pts.push({{
      lat: lat,
      lon: lon,
      ele: eleMatch ? parseFloat(eleMatch[1]) : undefined,
      time: timeMatch ? timeMatch[1] : undefined,
      spd: spdMatch ? parseFloat(spdMatch[1]) : 0
    }});
  }}
  return pts;
}}

function handleC2KGpxIngest(body) {{
  if (!isC2KAuthorized(body, false)) {{
    return {{ error: 'Unauthorized: valid key or pin required.' }};
  }}
  const roleRaw = String(body.role || 'crew').toLowerCase();
  const role = (roleRaw === 'runner' || roleRaw === 'simon' || roleRaw === 'jesse') ? 'runner' : 'crew';
  let pts = Array.isArray(body.points) ? body.points : [];
  if ((!pts || !pts.length) && body.gpxXml) {{
    pts = extractGpxPointsFromXml(String(body.gpxXml));
  }}
  if (!pts.length) {{
    return {{ error: 'No <trkpt> coordinates found in GPX payload.' }};
  }}

  const lastPt = pts[pts.length - 1];
  const pingPayload = {{
    key: body.key,
    pin: body.pin,
    role: role,
    lat: lastPt.lat,
    lon: lastPt.lon,
    ele: lastPt.ele,
    spd: lastPt.spd,
    spd_kmh: lastPt.spd_kmh,
    bat: lastPt.bat,
    time: lastPt.time,
    course_km: lastPt.course_km,
    source: body.source || 'Google Drive GPX Sync',
    note: body.note || '',
    forceLive: body.forceLive
  }};
  const pingRes = handleC2KPing(pingPayload);

  if (pts.length > 1) {{
    const slice = pts.slice(Math.max(0, pts.length - 25), pts.length - 1);
    const roleCode = role === 'runner' ? 'r' : 'c';
    const nowSec = Math.round(Date.now() / 1000);
    const tuples = slice.map(function (p) {{
      const ms = parseFixTimeMs(p.time, nowSec * 1000);
      return [
        Math.round(ms / 1000),
        roleCode,
        Math.round(parseFloat(p.lat) * 100000) / 100000,
        Math.round(parseFloat(p.lon) * 100000) / 100000
      ];
    }});
    appendC2KTrailPoints(tuples);
  }}

  return Object.assign({{ ingests: pts.length }}, pingRes);
}}

function handleC2KCheckin(body) {{
  if (!isC2KAuthorized(body, true)) {{
    return {{ error: 'Invalid Crew PIN.' }};
  }}

  const results = {{}};
  const now = Date.now();
  if (body.runner && !isNaN(parseFloat(body.runner.lat))) {{
    results.runner = handleC2KPing(Object.assign({{
      pin: body.pin,
      role: 'runner',
      source: 'Crew 1-Tap Check-In',
      fix_time: now,
      forceOverwrite: '1',
      forceLive: body.raceStatus === 'LIVE_RACE' ? '1' : ''
    }}, body.runner));
  }}
  if (body.crew && !isNaN(parseFloat(body.crew.lat))) {{
    results.crew = handleC2KPing(Object.assign({{
      pin: body.pin,
      role: 'crew',
      source: 'Crew 1-Tap Check-In',
      fix_time: now,
      forceOverwrite: '1',
      forceLive: body.raceStatus === 'LIVE_RACE' ? '1' : ''
    }}, body.crew));
  }}

  const state = getC2KState();
  let coreDirty = false;
  if (body.raceStatus) {{
    state.raceStatus = String(body.raceStatus);
    coreDirty = true;
  }}
  if (body.externalTrackerUrl) {{
    state.externalTrackerUrl = String(body.externalTrackerUrl).trim();
    coreDirty = true;
  }}
  if (coreDirty) {{
    saveC2KCore(state);
  }}

  const props = PropertiesService.getScriptProperties();
  const checkins = parsePropJsonArray(props, 'C2K_CHECKINS_RING');
  checkins.push({{
    note: String(body.note || 'Crew Manual Check-In').slice(0, 80),
    runner_km: state.runner ? state.runner.course_km : null,
    runner_lat: state.runner ? state.runner.lat : null,
    runner_lon: state.runner ? state.runner.lon : null,
    t: now
  }});
  saveBoundedPropArray(props, 'C2K_CHECKINS_RING', checkins, 15);

  return {{ success: true, results: results, state: sanitizePublicC2KState(getC2KState()) }};
}}

function handleC2KConfig(body) {{
  if (!isC2KAuthorized(body, true)) {{
    return {{ error: 'Invalid Crew PIN.' }};
  }}
  const state = getC2KState();
  if (body.resetBaseline === true) {{
    const props = PropertiesService.getScriptProperties();
    const fresh = JSON.parse(JSON.stringify(DEFAULT_C2K_CORE));
    fresh.externalTrackerUrl = state.externalTrackerUrl || DEFAULT_C2K_CORE.externalTrackerUrl;
    saveC2KCore(fresh);
    props.setProperty('C2K_CHECKINS_RING', '[]');
    props.setProperty('C2K_TRAIL_TAIL', '[]');
    try {{ CacheService.getScriptCache().remove('C2K_TRAIL_CACHE'); }} catch (e) {{}}
    return {{ success: true, reset: true, state: sanitizePublicC2KState(getC2KState()) }};
  }}
  if (body.externalTrackerUrl !== undefined) {{
    state.externalTrackerUrl = String(body.externalTrackerUrl).trim();
  }}
  if (body.runnerName !== undefined && state.runner) {{
    state.runner.name = String(body.runnerName).trim().slice(0, 60);
  }}
  if (body.runnerBib !== undefined && state.runner) {{
    state.runner.bib = String(body.runnerBib).trim().slice(0, 16);
  }}
  if (body.raceStatus !== undefined) {{
    state.raceStatus = String(body.raceStatus).trim();
  }}
  if (body.raceStartIso !== undefined) {{
    state.raceStartIso = String(body.raceStartIso).trim();
  }}
  saveC2KCore(state);
  return {{ success: true, state: sanitizePublicC2KState(getC2KState()) }};
}}

function jsonResponse(obj) {{
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}}
"""


def build_c2k_standalone_code_gs(ingest_key: str, crew_pin: str) -> str:
    return f"""/**
 * Coast to Kosciuszko (C2K) - Standalone 24/7 Cloud Telemetry Relay (jakiib@gmail.com)
 */
{build_c2k_core_js(ingest_key, crew_pin)}

function doGet(e) {{
  const params = (e && e.parameter) ? e.parameter : {{}};
  const action = String(params.action || 'c2k-state').trim();
  if (action === 'c2k-ping') {{
    return jsonResponse(handleC2KPing(params));
  }}
  return jsonResponse(sanitizePublicC2KState(getC2KState()));
}}

function doPost(e) {{
  try {{
    const params = (e && e.parameter) ? e.parameter : {{}};
    const raw = (e && e.postData && e.postData.contents) ? e.postData.contents : '{{}}';
    let body = {{}};
    try {{ body = JSON.parse(raw); }} catch (err) {{ body = {{}}; }}
    const action = String(body.action || params.action || '').trim();
    const merged = Object.assign({{}}, params, body);
    if (action === 'c2k-ping') return jsonResponse(handleC2KPing(merged));
    if (action === 'c2k-gpx-ingest') return jsonResponse(handleC2KGpxIngest(merged));
    if (action === 'c2k-checkin') return jsonResponse(handleC2KCheckin(merged));
    if (action === 'c2k-config') return jsonResponse(handleC2KConfig(merged));
    return jsonResponse({{ error: 'Unknown action: ' + action }});
  }} catch (err) {{
    return jsonResponse({{ error: String(err.message || err) }});
  }}
}}
"""


def build_unified_code_gs(ingest_key: str, crew_pin: str) -> str:
    roster_str = (DND_ROOT / "data" / "party_roster.json").read_text(encoding="utf-8")
    state_str = (DND_ROOT / "data" / "party_state.json").read_text(encoding="utf-8")
    return f"""/**
 * 24/7 Personal Cloud State Relay (jakiib@gmail.com)
 * Namespace 1: The Ballad of the Seasoners (D&D Beyond Live Party Command Center)
 * Namespace 2: Coast to Kosciuszko (C2K) 241km 3D Live Broadcast Telemetry Relay
 */

const DEFAULT_ROSTER_JSON = {roster_str};
const DEFAULT_PARTY_STATE_JSON = {state_str};
const CHUNK_SIZE = 40000;
const CACHE_TTL = 21600; // 6 hours
{build_c2k_core_js(ingest_key, crew_pin)}

function doGet(e) {{
  const params = (e && e.parameter) ? e.parameter : {{}};
  const action = String(params.action || 'state').trim();

  if (action === 'c2k-state') {{
    return jsonResponse(sanitizePublicC2KState(getC2KState()));
  }}
  if (action === 'c2k-ping') {{
    return jsonResponse(handleC2KPing(params));
  }}
  if (action === 'character' && params.id) {{
    return jsonResponse(getCachedCharacter(String(params.id).trim()));
  }}
  return jsonResponse(getCloudStateBundle());
}}

function doPost(e) {{
  try {{
    const params = (e && e.parameter) ? e.parameter : {{}};
    const raw = (e && e.postData && e.postData.contents) ? e.postData.contents : '{{}}';
    let body = {{}};
    try {{ body = JSON.parse(raw); }} catch (parseErr) {{ body = {{}}; }}
    const action = String(body.action || params.action || '').trim();
    const merged = Object.assign({{}}, params, body);

    if (action === 'c2k-ping') return jsonResponse(handleC2KPing(merged));
    if (action === 'c2k-gpx-ingest') return jsonResponse(handleC2KGpxIngest(merged));
    if (action === 'c2k-checkin') return jsonResponse(handleC2KCheckin(merged));
    if (action === 'c2k-config') return jsonResponse(handleC2KConfig(merged));

    if (action === 'save-state' && body.partyState) return jsonResponse(saveCloudPartyState(body.partyState));
    if (action === 'save-roster' && body.roster) return jsonResponse(saveCloudRoster(body.roster));
    if (action === 'save-characters' && body.characters) return jsonResponse(saveCachedCharacters(body.characters));
    return jsonResponse({{ error: 'Unknown action: ' + action }});
  }} catch (err) {{
    return jsonResponse({{ error: String(err.message || err) }});
  }}
}}

function putChunkedCache(cache, baseKey, strVal) {{
  const totalChunks = Math.ceil(strVal.length / CHUNK_SIZE);
  for (let i = 0; i < totalChunks; i++) {{
    cache.put(baseKey + '_' + i, strVal.substring(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE), CACHE_TTL);
  }}
  cache.put(baseKey + '_cnt', String(totalChunks), CACHE_TTL);
}}

function getChunkedCache(cache, baseKey) {{
  const cntStr = cache.get(baseKey + '_cnt');
  if (!cntStr) return null;
  const totalChunks = parseInt(cntStr, 10);
  if (isNaN(totalChunks) || totalChunks <= 0) return null;
  const keys = [];
  for (let i = 0; i < totalChunks; i++) keys.push(baseKey + '_' + i);
  const map = cache.getAll(keys);
  let out = '';
  for (let i = 0; i < totalChunks; i++) {{
    const part = map[baseKey + '_' + i];
    if (part === undefined || part === null) return null;
    out += part;
  }}
  try {{ return JSON.parse(out); }} catch (e) {{ return null; }}
}}

function saveCachedCharacters(charactersMap) {{
  const cache = CacheService.getScriptCache();
  const ids = Object.keys(charactersMap || {{}});
  for (let i = 0; i < ids.length; i++) {{
    const cid = String(ids[i]).trim();
    const charObj = charactersMap[cid];
    if (!cid || !charObj) continue;
    putChunkedCache(cache, 'DDB_CHAR_' + cid, JSON.stringify(charObj));
  }}
  cache.put('DDB_CHAR_IDS', JSON.stringify(ids), CACHE_TTL);
  return {{ success: true, count: ids.length, timestamp: Date.now() }};
}}

function getCachedCharacter(charId) {{
  const cache = CacheService.getScriptCache();
  return getChunkedCache(cache, 'DDB_CHAR_' + charId);
}}

function getCloudStateBundle() {{
  const props = PropertiesService.getScriptProperties();
  const cache = CacheService.getScriptCache();
  let partyState = DEFAULT_PARTY_STATE_JSON;
  let roster = DEFAULT_ROSTER_JSON;
  try {{
    const rawState = props.getProperty('PARTY_STATE');
    if (rawState) partyState = JSON.parse(rawState);
  }} catch (e) {{}}
  try {{
    const rawRoster = props.getProperty('PARTY_ROSTER');
    if (rawRoster) roster = JSON.parse(rawRoster);
  }} catch (e) {{}}
  const characters = {{}};
  const activeIds = (roster || [])
    .filter(function(r) {{ return r && r.enabled !== false && r.dndBeyondId; }})
    .map(function(r) {{ return String(r.dndBeyondId).trim(); }});
  for (let i = 0; i < activeIds.length; i++) {{
    const cid = activeIds[i];
    const ch = getChunkedCache(cache, 'DDB_CHAR_' + cid);
    if (ch) characters[cid] = ch;
  }}
  return {{ partyState: partyState, roster: roster, characters: characters, timestamp: Date.now() }};
}}

function saveCloudPartyState(partyState) {{
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {{
    PropertiesService.getScriptProperties().setProperty('PARTY_STATE', JSON.stringify(partyState));
    return {{ success: true, timestamp: Date.now() }};
  }} finally {{ lock.releaseLock(); }}
}}

function saveCloudRoster(roster) {{
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {{
    PropertiesService.getScriptProperties().setProperty('PARTY_ROSTER', JSON.stringify(roster));
    return {{ success: true, timestamp: Date.now() }};
  }} finally {{ lock.releaseLock(); }}
}}
"""


def try_standalone_deploy(mgr: PersonalAppsScriptManager, existing: dict, manifest: dict, ingest_key: str, crew_pin: str):
    standalone_id = existing.get("standalone_script_id")
    if not standalone_id and existing.get("script_id") and existing.get("script_id") != SHARED_SCRIPT_ID:
        standalone_id = existing["script_id"]

    if not standalone_id:
        proj = mgr.create_project("Coast2Kosci Live 3D Telemetry Relay")
        standalone_id = proj["scriptId"]

    files = [
        {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, indent=2)},
        {"name": "Code", "type": "SERVER_JS", "source": build_c2k_standalone_code_gs(ingest_key, crew_pin)},
    ]
    mgr.update_project_content(standalone_id, files)
    ver = mgr.create_version(standalone_id, "Coast2Kosci Standalone 24/7 Telemetry Relay")
    v_num = int(ver["versionNumber"])

    deployments = [d for d in mgr.list_deployments(standalone_id) if "versionNumber" in (d.get("deploymentConfig") or {})]
    if deployments:
        dep_id = deployments[0]["deploymentId"]
        mgr.update_deployment(standalone_id, dep_id, v_num, "Coast2Kosci Standalone 24/7 Telemetry Relay")
    else:
        url = f"https://script.googleapis.com/v1/projects/{standalone_id}/deployments"
        payload = {"versionNumber": v_num, "manifestFileName": "appsscript", "description": "Coast2Kosci Standalone WebApp"}
        r = requests.post(url, headers=mgr._headers(), json=payload, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"Failed creating deployment on standalone project: {r.status_code} {r.text}")
        dep_id = r.json()["deploymentId"]

    relay_url = f"https://script.google.com/macros/s/{dep_id}/exec"
    test_resp = requests.get(f"{relay_url}?action=c2k-state", timeout=15)
    if test_resp.status_code == 200:
        try:
            j = test_resp.json()
            if isinstance(j, dict) and j.get("raceStatus"):
                return standalone_id, dep_id, v_num, relay_url, True
        except Exception:
            pass
    return standalone_id, dep_id, v_num, relay_url, False


def main():
    existing, ingest_key, crew_pin = load_or_create_secrets()
    mgr = PersonalAppsScriptManager()
    manifest = {
        "timeZone": "Australia/Sydney",
        "dependencies": {},
        "exceptionLogging": "STACKDRIVER",
        "runtimeVersion": "V8",
        "oauthScopes": [],
        "webapp": {
            "executeAs": "USER_DEPLOYING",
            "access": "ANYONE_ANONYMOUS",
        },
    }

    standalone_id = existing.get("standalone_script_id")
    standalone_dep_id = existing.get("standalone_deployment_id")
    standalone_ok = False

    try:
        standalone_id, standalone_dep_id, st_ver, st_url, standalone_ok = try_standalone_deploy(
            mgr, existing, manifest, ingest_key, crew_pin
        )
        print(f"[Standalone Test] script={standalone_id} ok={standalone_ok} url={st_url}")
    except Exception as e:
        print(f"[Standalone Test] Non-fatal error attempting standalone deploy: {e}")

    if standalone_ok:
        active_script_id = standalone_id
        active_dep_id = standalone_dep_id
        active_ver = st_ver
        relay_url = st_url
        mode_note = "dedicated_standalone"

        # Restore D&D Cloud Relay back to pure D&D code only if it wasn't already restored
        dnd_updater = DND_ROOT / "scripts" / "update_cloud_relay.py"
        if dnd_updater.exists() and existing.get("script_id") == SHARED_SCRIPT_ID:
            print("[Decouple] Restoring D&D Cloud Relay to pure D&D Beyond code...")
            subprocess.run(["python", str(dnd_updater)], check=True)
            try:
                dnd_check = requests.get(f"https://script.google.com/macros/s/{SHARED_DEPLOYMENT_ID}/exec", timeout=15)
                print(f"[Decouple] D&D endpoint HTTP {dnd_check.status_code} ({dnd_check.headers.get('content-type')})")
            except Exception as exc:
                print(f"[Decouple Warning] D&D check note: {exc}")
    else:
        print("[Fallback] Standalone WebApp requires 1-time Google browser consent; deploying quota-safe isolated C2K_* namespace on verified active relay...")
        files = [
            {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, indent=2)},
            {"name": "Code", "type": "SERVER_JS", "source": build_unified_code_gs(ingest_key, crew_pin)},
        ]
        mgr.update_project_content(SHARED_SCRIPT_ID, files)
        ver = mgr.create_version(SHARED_SCRIPT_ID, "Coast2Kosci Quota-Safe Authenticated Telemetry + D&D Relay")
        active_ver = int(ver["versionNumber"])
        mgr.update_deployment(
            SHARED_SCRIPT_ID,
            SHARED_DEPLOYMENT_ID,
            active_ver,
            "Coast2Kosci Quota-Safe Authenticated Telemetry + D&D Relay",
        )
        active_script_id = SHARED_SCRIPT_ID
        active_dep_id = SHARED_DEPLOYMENT_ID
        relay_url = f"https://script.google.com/macros/s/{SHARED_DEPLOYMENT_ID}/exec"
        mode_note = "verified_multi_tenant_with_isolated_c2k_props"

    r = requests.get(f"{relay_url}?action=c2k-state", timeout=15)
    print(f"[Verify GET c2k-state] HTTP {r.status_code}: {r.text[:220]}...")
    r.raise_for_status()

    cfg = {
        "mode": mode_note,
        "script_id": active_script_id,
        "deployment_id": active_dep_id,
        "version": active_ver,
        "relay_url": relay_url,
        "ingest_key": ingest_key,
        "crew_pin": crew_pin,
        "standalone_script_id": standalone_id,
        "standalone_editor_url": f"https://script.google.com/d/{standalone_id}/edit" if standalone_id else "",
        "gpslogger_crew_url": f"{relay_url}?action=c2k-ping&key={ingest_key}&role=crew&lat=%LAT&lon=%LON&ele=%ALT&spd=%SPD&bat=%BATT&time=%TIME",
        "gpslogger_runner_url": f"{relay_url}?action=c2k-ping&key={ingest_key}&role=runner&lat=%LAT&lon=%LON&ele=%ALT&spd=%SPD&bat=%BATT&time=%TIME",
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[Success] Wrote {CONFIG_PATH.name} (mode={mode_note})")


if __name__ == "__main__":
    main()
