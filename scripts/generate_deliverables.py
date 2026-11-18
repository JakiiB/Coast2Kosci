import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def clean_dashes(s):
    if not isinstance(s, str):
        return s
    return s.replace("\u2014", " - ").replace("\u2013", " - ")


def build_excel(db):
    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    header_fill = PatternFill("solid", fgColor="0F243E")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="Calibri", size=10, color="111827")
    bold_font = Font(name="Calibri", size=10, bold=True, color="111827")
    link_font = Font(name="Calibri", size=10, color="0563C1", underline="single")

    fill_cutoff = PatternFill("solid", fgColor="FEF3C7")   # Soft amber for hard cut-offs
    fill_danger = PatternFill("solid", fgColor="FEE2E2")   # Soft red for strict prohibitions / no toilets
    fill_cp = PatternFill("solid", fgColor="E0F2FE")       # Soft sky blue for checkpoints
    fill_zebra = PatternFill("solid", fgColor="F8FAFC")

    thin_side = Side(border_style="thin", color="D1D5DB")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    sheet_specs = [
        ("Master_Course_Waypoints", db["tables"]["master_waypoints"], {
            "Waypoint_ID": 11, "Distance_km": 12, "Leg_Split_km": 12, "Location_Name": 36,
            "Category": 28, "Official_CP_Number": 14, "Elevation_m": 12,
            "Cutoff_Time_AEDT": 26, "Cutoff_Elapsed_Hrs": 14, "Toilet_Status": 38,
            "Aid_Food_Supplies_Info": 38, "Crew_And_Vehicle_Rules": 46,
            "Pacer_Rules": 32, "Gear_Requirements": 36, "Surface_And_Terrain": 32,
            "Source_Authority": 28, "Latitude": 12, "Longitude": 12,
            "Google_Maps_URL": 18, "Notes": 44,
        }),
        ("Checkpoints_And_Cutoffs", db["tables"]["checkpoints_and_cutoffs"], {
            "CP_Number": 11, "Checkpoint_Name": 36, "Guide_Distance_km": 14,
            "GPS_Track_km": 13, "Segment_Split_km": 14, "Elevation_m": 12,
            "Has_Hard_Cutoff": 24, "Cutoff_Day_Time_AEDT": 24, "Cutoff_Elapsed_Hours": 15,
            "Min_Overall_Pace": 15, "Min_Overall_Speed": 15, "Check_In_Procedure": 44,
            "Crew_Access": 44, "Pacer_Status": 36, "Facilities_At_CP": 46,
            "Latitude": 12, "Longitude": 12, "Google_Maps_URL": 18,
        }),
        ("Toilets_And_Aid_Stops", db["tables"]["toilets_and_aid_stations"], {
            "Stop_ID": 10, "Distance_km": 12, "Location_Name": 38,
            "Stop_Category": 32, "Authority": 32, "Toilet_Available": 36,
            "Opening_Hours": 24, "Food_Drink_Aid": 38, "Payment_Method": 22,
            "Drinking_Water": 16, "Shower": 14, "Wheelchair_Accessible": 16,
            "Off_Course_Distance_m": 16, "Crew_And_Runner_Rules": 48,
            "Latitude": 12, "Longitude": 12, "Google_Maps_URL": 18,
        }),
        ("Course_Legs_TurnByTurn", db["tables"]["course_legs_and_directions"], {
            "Cue_Seq": 10, "Distance_km": 12, "Leg_Name": 36, "Turn_Type": 14,
            "Instruction": 38, "Elevation_m": 12, "Surface_Type": 34,
            "Leg_Rules_And_Cutoff": 44, "Official_Course_Notes": 46,
            "Latitude": 12, "Longitude": 12, "Google_Maps_URL": 18,
        }),
        ("Rules_Gear_Crew_Pacers", db["tables"]["rules_gear_crew_pacers"], {
            "Rule_ID": 10, "Category": 26, "Topic": 36, "Requirement_Status": 26,
            "Details": 68, "Source_Reference": 26,
        }),
        ("2026_Event_Schedule", db["tables"]["event_schedule_2026"], {
            "Phase": 14, "Date": 18, "Time_AEDT": 18, "Event": 38,
            "Location": 34, "Key_Details": 56, "Course_Distance": 18,
        }),
    ]

    for title, rows, widths in sheet_specs:
        ws = wb.create_sheet(title=title)
        if not rows:
            continue
        headers = list(rows[0].keys())
        ws.append(headers)
        ws.row_dimensions[1].height = 28

        for c_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            cell.border = border
            col_letter = get_column_letter(c_idx)
            ws.column_dimensions[col_letter].width = widths.get(h, 20)

        for r_idx, row_dict in enumerate(rows, 2):
            row_vals = [row_dict.get(h, "") for h in headers]
            ws.append(row_vals)
            row_blob = " ".join(str(v) for v in row_vals).lower()

            row_fill = None
            if "strictly no toilets" in row_blob or "prohibited" in row_blob or "penalty" in row_blob:
                row_fill = fill_danger
            elif "yes - hard cut-off" in row_blob or "yes - final finish" in row_blob or "hard cut-off" in row_blob or "cut-off #" in row_blob:
                row_fill = fill_cutoff
            elif "mandatory checkpoint" in row_blob or str(row_dict.get("CP_Number", "")).startswith("CP"):
                row_fill = fill_cp
            elif r_idx % 2 == 1:
                row_fill = fill_zebra

            for c_idx, h in enumerate(headers, 1):
                cell = ws.cell(row=r_idx, column=c_idx)
                val = cell.value
                cell.border = border
                if h == "Google_Maps_URL" and isinstance(val, str) and val.startswith("http"):
                    cell.hyperlink = val
                    cell.value = "Open Google Maps"
                    cell.font = link_font
                    cell.alignment = Alignment(horizontal="center", vertical="top")
                else:
                    is_key_col = h in ("Waypoint_ID", "CP_Number", "Stop_ID", "Rule_ID", "Location_Name", "Checkpoint_Name", "Topic", "Event")
                    cell.font = bold_font if is_key_col else body_font
                    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                if row_fill is not None:
                    cell.fill = row_fill

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"

    out_xlsx = BASE_DIR / "Coast2Kosci_2026_Master_Database.xlsx"
    wb.save(out_xlsx)
    print(f"Saved Excel workbook: {out_xlsx.name} ({len(wb.sheetnames)} sheets)")
    return out_xlsx


def build_html(db):
    # Serialize JSON safely for inline script tag
    json_blob = clean_dashes(json.dumps(db))
    json_blob = json_blob.replace("</", "<\\/")

    html_template = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coast to Kosci (C2K) 2026 - Master Race Database</title>
<style>
  :root {
    --bg: #0b1320;
    --panel: #111c2e;
    --panel-alt: #16243b;
    --border: #253654;
    --text: #e5ecf6;
    --muted: #93a4be;
    --accent: #38bdf8;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
    --purple: #a78bfa;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.45;
  }
  header {
    background: linear-gradient(135deg, #091526 0%, #102a43 60%, #133b5c 100%);
    border-bottom: 1px solid var(--border);
    padding: 20px 24px;
  }
  .wrap { max-width: 1460px; margin: 0 auto; }
  .title-row { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }
  h1 { margin: 0; font-size: 1.55rem; letter-spacing: -0.01em; }
  .subtitle { color: var(--muted); font-size: 0.92rem; margin-top: 4px; }
  .badge-offline {
    background: rgba(34, 197, 94, 0.16);
    color: #86efac;
    border: 1px solid rgba(34, 197, 94, 0.4);
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 600;
  }
  .kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
    gap: 12px;
    margin: 18px 0 0;
  }
  .kpi {
    background: rgba(17, 28, 46, 0.85);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
  }
  .kpi .lbl { color: var(--muted); font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .kpi .val { font-size: 1.25rem; font-weight: 700; margin-top: 3px; color: #fff; }
  .kpi .sub { font-size: 0.78rem; color: var(--accent); margin-top: 2px; }

  main { padding: 18px 24px 48px; }
  .grid-2 {
    display: grid;
    grid-template-columns: 1.25fr 1fr;
    gap: 16px;
    margin-bottom: 18px;
  }
  @media (max-width: 980px) { .grid-2 { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
  }
  .card h2 {
    margin: 0 0 10px;
    font-size: 1.05rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .card-sub { color: var(--muted); font-size: 0.83rem; margin-bottom: 12px; }

  /* Elevation Chart */
  #elevSvg { width: 100%; height: 245px; display: block; background: #0d1726; border-radius: 8px; border: 1px solid var(--border); }
  .elev-legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.78rem; color: var(--muted); margin-top: 8px; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 5px; }

  /* Pace Calculator */
  .calc-controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 10px; }
  .calc-controls label { font-size: 0.85rem; color: var(--muted); }
  input[type="range"] { width: 180px; accent-color: var(--accent); }
  select, input[type="search"], input[type="number"] {
    background: #0d1726;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 0.88rem;
  }
  .eta-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  .eta-table th, .eta-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; }
  .eta-table th { color: var(--muted); font-weight: 600; }
  .ok { color: #86efac; font-weight: 600; }
  .warn { color: #fcd34d; font-weight: 600; }
  .bad { color: #fca5a5; font-weight: 700; }

  /* Tabs & Filters */
  .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .tab-btn {
    background: var(--panel);
    color: var(--muted);
    border: 1px solid var(--border);
    padding: 9px 14px;
    border-radius: 9px;
    cursor: pointer;
    font-size: 0.88rem;
    font-weight: 600;
  }
  .tab-btn.active { background: var(--accent); color: #061320; border-color: var(--accent); }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }
  .search-box { flex: 1 1 280px; max-width: 440px; width: 100%; }
  .pills { display: flex; flex-wrap: wrap; gap: 6px; }
  .pill {
    background: var(--panel-alt);
    color: var(--muted);
    border: 1px solid var(--border);
    padding: 5px 11px;
    border-radius: 999px;
    font-size: 0.79rem;
    cursor: pointer;
  }
  .pill.active { background: #1e3a5f; color: #fff; border-color: var(--accent); }

  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel);
    max-height: 70vh;
  }
  table.db { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
  table.db thead th {
    position: sticky;
    top: 0;
    background: #0d1726;
    color: #cbd5e1;
    padding: 10px 10px;
    text-align: left;
    border-bottom: 2px solid var(--border);
    white-space: nowrap;
    z-index: 2;
  }
  table.db tbody td {
    padding: 9px 10px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    min-width: 100px;
  }
  table.db tbody tr:hover { background: rgba(56, 189, 248, 0.08); }
  tr.row-cutoff { background: rgba(245, 158, 11, 0.11); }
  tr.row-danger { background: rgba(239, 68, 68, 0.12); }
  tr.row-cp { background: rgba(56, 189, 248, 0.08); }

  .tag {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 5px;
    font-size: 0.74rem;
    font-weight: 700;
    white-space: nowrap;
  }
  .tag-red { background: rgba(239, 68, 68, 0.22); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.45); }
  .tag-amber { background: rgba(245, 158, 11, 0.22); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.45); }
  .tag-blue { background: rgba(56, 189, 248, 0.18); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.4); }
  .tag-green { background: rgba(34, 197, 94, 0.18); color: #86efac; border: 1px solid rgba(34, 197, 94, 0.4); }

  a.map-btn {
    display: inline-block;
    background: rgba(56, 189, 248, 0.15);
    color: #7dd3fc;
    border: 1px solid rgba(56, 189, 248, 0.4);
    padding: 3px 8px;
    border-radius: 6px;
    text-decoration: none;
    font-size: 0.77rem;
    white-space: nowrap;
  }
  a.map-btn:hover { background: var(--accent); color: #061320; }
  .count-note { color: var(--muted); font-size: 0.82rem; margin-bottom: 8px; }
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="title-row">
      <div>
        <h1>Coast to Kosci (C2K) 2026 - Complete Race Logistics Database</h1>
        <div class="subtitle">
          Boydtown Beach (Twofold Bay) to Mt Kosciuszko Summit &amp; Charlotte Pass Finish | Sources: C2K 2026 Runners Guide, Race Schedule, Race Rules, RWGPS #41169431, TrackMeLive 2026 &amp; Australian National Public Toilet Map
        </div>
      </div>
      <div class="badge-offline">100% Offline Ready</div>
    </div>
    <div class="kpis">
      <div class="kpi"><div class="lbl">Course Distance</div><div class="val">240.65 km</div><div class="sub">Official 240 km | +5,269m (+5,467m GPS)</div></div>
      <div class="kpi"><div class="lbl">Race Window (46 Hrs)</div><div class="val">Fri 05:30 - Sun 03:30</div><div class="sub">20-22 Nov 2026 AEDT (67 Runners)</div></div>
      <div class="kpi"><div class="lbl">Checkpoints &amp; Cut-Offs</div><div class="val">8 CPs / 6 Cut-Offs</div><div class="sub">Cathcart, CP4, Dalgety, Jindy, Charlotte, Finish</div></div>
      <div class="kpi"><div class="lbl">Aid Model</div><div class="val">Mobile Support Crew</div><div class="sub">Only 1 race aid before CP1 (3.74 km)</div></div>
      <div class="kpi"><div class="lbl">Toilets &amp; Pitstops</div><div class="val">17 Mapped Stops</div><div class="sub">STRICTLY NO TOILETS at Boydtown Start!</div></div>
      <div class="kpi"><div class="lbl">Mandatory Pacer Zones</div><div class="val">Big Jack, Beloka, Summit</div><div class="sub">General pacers open post-CP4 (106.7 km)</div></div>
    </div>
  </div>
</header>

<main class="wrap">
  <div class="grid-2">
    <div class="card">
      <h2>
        <span>Course Elevation &amp; Checkpoint Profile (0 to 240.65 km)</span>
        <span id="elevHover" style="font-size:0.82rem;color:var(--accent);font-weight:500;">Hover chart to inspect</span>
      </h2>
      <div class="card-sub">Sea level (Twofold Bay) to Australia's highest peak (2,228 m Mt Kosciuszko) and Charlotte Pass finish (1,839 m).</div>
      <svg id="elevSvg" viewBox="0 0 900 245" preserveAspectRatio="none"></svg>
      <div class="elev-legend">
        <span><span class="dot" style="background:#f59e0b"></span>Hard Cut-Off Checkpoint</span>
        <span><span class="dot" style="background:#38bdf8"></span>Mandatory Checkpoint</span>
        <span><span class="dot" style="background:#22c55e"></span>Public / Hall Toilet Stop</span>
        <span><span class="dot" style="background:#ef4444"></span>Mt Kosciuszko Summit (2,228 m)</span>
      </div>
    </div>

    <div class="card">
      <h2><span>Target Pace &amp; Cut-Off Buffer Calculator</span></h2>
      <div class="card-sub">Race starts Fri 20 Nov 2026 at 05:30 AEDT. Adjust target finish time to preview checkpoint arrival times &amp; cut-off margins.</div>
      <div class="calc-controls">
        <label>Target Finish: <strong id="targetHrsLbl" style="color:#fff">40.0 hrs</strong></label>
        <input type="range" id="targetHrs" min="22" max="46" step="0.5" value="40">
        <select id="paceModel">
          <option value="fade">Realistic Ultra Fade (+25% slower late)</option>
          <option value="even">Even Split Pace</option>
        </select>
      </div>
      <div style="overflow-x:auto">
        <table class="eta-table">
          <thead><tr><th>CP / Cut-Off</th><th>km</th><th>Target ETA (AEDT)</th><th>Cut-Off</th><th>Margin</th></tr></thead>
          <tbody id="etaBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="tabs" id="tabs"></div>

  <div class="toolbar">
    <input type="search" id="searchBox" class="search-box" placeholder="Search any location, rule, toilet, cut-off, road, gear item...">
    <div class="pills" id="filterPills"></div>
  </div>

  <div class="count-note" id="countNote"></div>
  <div class="table-wrap">
    <table class="db" id="mainTable">
      <thead id="tableHead"></thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
</main>

<script id="c2k-data" type="application/json">__C2K_JSON__</script>
<script>
const DB = JSON.parse(document.getElementById("c2k-data").textContent);

const TABS = [
  { id: "master_waypoints", label: "Master Waypoints (25)" },
  { id: "checkpoints_and_cutoffs", label: "Checkpoints & Cut-Offs (11)" },
  { id: "toilets_and_aid_stations", label: "Toilets & Aid Stops (17)" },
  { id: "course_legs_and_directions", label: "Turn-by-Turn & Legs (61)" },
  { id: "rules_gear_crew_pacers", label: "Rules, Gear, Crew & Pacers (29)" },
  { id: "event_schedule_2026", label: "2026 Event Schedule (16)" }
];

const FILTERS = [
  { id: "all", label: "All Rows" },
  { id: "cutoff", label: "Hard Cut-Offs" },
  { id: "checkpoint", label: "Checkpoints" },
  { id: "toilet", label: "Toilets & Water" },
  { id: "aid", label: "Food & Community Aid" },
  { id: "pacer", label: "Pacer / Crew Rules" },
  { id: "hazard", label: "Hazards & Crossings" }
];

let activeTab = "master_waypoints";
let activeFilter = "all";
let searchQuery = "";

function rowText(row) {
  return Object.values(row).join(" ").toLowerCase();
}

function matchesFilter(row) {
  const txt = rowText(row);
  if (searchQuery && !txt.includes(searchQuery)) return false;
  if (activeFilter === "all") return true;
  if (activeFilter === "cutoff") return txt.includes("cut-off") || txt.includes("cutoff");
  if (activeFilter === "checkpoint") return txt.includes("checkpoint") || txt.includes("cp ") || txt.includes("summit") || txt.includes("finish");
  if (activeFilter === "toilet") return txt.includes("toilet") || txt.includes("restroom") || txt.includes("water") || txt.includes("shower") || txt.includes("seamans") || txt.includes("rawson");
  if (activeFilter === "aid") return txt.includes("aid") || txt.includes("bbq") || txt.includes("coffee") || txt.includes("soup") || txt.includes("store") || txt.includes("jindabyne") || txt.includes("breakfast");
  if (activeFilter === "pacer") return txt.includes("pacer") || txt.includes("crew") || txt.includes("vehicle") || txt.includes("hi-vis") || txt.includes("reflective");
  if (activeFilter === "hazard") return txt.includes("crossing") || txt.includes("prohibited") || txt.includes("penalt") || txt.includes("cattle") || txt.includes("bibbenluke") || txt.includes("beloka") || txt.includes("big jack");
  return true;
}

function rowClass(row) {
  const txt = rowText(row);
  if (txt.includes("strictly no toilets") || txt.includes("penalties apply") || txt.includes("prohibited")) return "row-danger";
  if (txt.includes("yes - hard cut-off") || txt.includes("yes - final finish") || txt.includes("hard cut-off #")) return "row-cutoff";
  if (txt.includes("mandatory checkpoint") || String(row.CP_Number || "").startsWith("CP")) return "row-cp";
  return "";
}

function formatCell(key, val) {
  if (val === null || val === undefined || val === "") return '<span style="color:#475569">-</span>';
  const s = String(val);
  if (key === "Google_Maps_URL" && s.startsWith("http")) {
    return `<a class="map-btn" href="${s}" target="_blank" rel="noopener">Map Pin</a>`;
  }
  if (key === "Has_Hard_Cutoff" || key === "Requirement_Status") {
    const low = s.toLowerCase();
    if (low.includes("hard cut-off") || low.includes("final finish")) return `<span class="tag tag-amber">${s}</span>`;
    if (low.includes("prohibition") || low.includes("penalty") || low.includes("strict")) return `<span class="tag tag-red">${s}</span>`;
    if (low.includes("mandatory")) return `<span class="tag tag-blue">${s}</span>`;
  }
  if (key === "Toilet_Status" || key === "Toilet_Available") {
    const low = s.toLowerCase();
    if (low.includes("no - strictly") || low.includes("strictly no toilets")) return `<span class="tag tag-red">${s}</span>`;
    if (low.includes("yes") || low.includes("public toilet") || low.includes("24h") || low.includes("hall")) return `<span class="tag tag-green">${s}</span>`;
  }
  return s.replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderTable() {
  const rows = DB.tables[activeTab] || [];
  const filtered = rows.filter(matchesFilter);
  const thead = document.getElementById("tableHead");
  const tbody = document.getElementById("tableBody");
  document.getElementById("countNote").textContent = `Showing ${filtered.length} of ${rows.length} entries in ${TABS.find(t => t.id === activeTab).label}`;

  if (!rows.length) {
    thead.innerHTML = "";
    tbody.innerHTML = "";
    return;
  }
  const cols = Object.keys(rows[0]);
  thead.innerHTML = "<tr>" + cols.map(c => `<th>${c.replace(/_/g, " ")}</th>`).join("") + "</tr>";
  tbody.innerHTML = filtered.map(r => {
    const cls = rowClass(r);
    return `<tr class="${cls}">` + cols.map(c => `<td>${formatCell(c, r[c])}</td>`).join("") + "</tr>";
  }).join("");
}

function renderControls() {
  document.getElementById("tabs").innerHTML = TABS.map(t =>
    `<button class="tab-btn ${t.id === activeTab ? "active" : ""}" onclick="setTab('${t.id}')">${t.label}</button>`
  ).join("");
  document.getElementById("filterPills").innerHTML = FILTERS.map(f =>
    `<button class="pill ${f.id === activeFilter ? "active" : ""}" onclick="setFilter('${f.id}')">${f.label}</button>`
  ).join("");
}

window.setTab = function(id) { activeTab = id; renderControls(); renderTable(); };
window.setFilter = function(id) { activeFilter = id; renderControls(); renderTable(); };
document.getElementById("searchBox").addEventListener("input", e => {
  searchQuery = e.target.value.trim().toLowerCase();
  renderTable();
});

// Pace Calculator (Start: Fri 20 Nov 2026 05:30 AEDT)
const RACE_START_MS = Date.parse("2026-11-20T05:30:00+11:00");
const TOTAL_KM = 240.65;
const CALC_STOPS = [
  { name: "CP1 Towamba", km: 24.43, cutHrs: null, cutLabel: "-" },
  { name: "CP2 Rocky Hall", km: 51.67, cutHrs: null, cutLabel: "-" },
  { name: "CP3 Cathcart (Cut #1)", km: 69.65, cutHrs: 12.0, cutLabel: "Fri 17:30 (12h)" },
  { name: "CP4 Gunningrach Rd (Cut #2)", km: 106.60, cutHrs: 18.0, cutLabel: "Fri 23:30 (18h)" },
  { name: "CP5 Dalgety Bridge (Cut #3)", km: 148.25, cutHrs: 25.0, cutLabel: "Sat 06:30 (25h)" },
  { name: "CP6 Jindabyne CP (Cut #4)", km: 183.92, cutHrs: 32.5, cutLabel: "Sat 14:00 (32.5h)" },
  { name: "CP7 Perisher Ski-Tube", km: 213.11, cutHrs: null, cutLabel: "-" },
  { name: "CP8 Charlotte Pass (Cut #5)", km: 222.05, cutHrs: 41.5, cutLabel: "Sat 23:00 (41.5h)" },
  { name: "Mt Kosciuszko Summit", km: 231.30, cutHrs: null, cutLabel: "-" },
  { name: "Finish Charlotte Pass", km: 240.65, cutHrs: 46.0, cutLabel: "Sun 03:30 (46h)" }
];

function fmtAEDT(hoursElapsed) {
  // Format in +11:00 fixed AEDT cleanly using UTC math + 11h offset
  const d = new Date(RACE_START_MS + hoursElapsed * 3600000 + 11 * 3600000);
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const day = days[d.getUTCDay()];
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${day} ${hh}:${mm}`;
}

function fmtDiff(diffHrs) {
  const sign = diffHrs >= 0 ? "+" : "-";
  const absMins = Math.round(Math.abs(diffHrs) * 60);
  const h = Math.floor(absMins / 60);
  const m = absMins % 60;
  return `${sign}${h}h ${String(m).padStart(2, "0")}m`;
}

function updateCalc() {
  const target = parseFloat(document.getElementById("targetHrs").value);
  const model = document.getElementById("paceModel").value;
  document.getElementById("targetHrsLbl").textContent = target.toFixed(1) + " hrs";

  const tbody = document.getElementById("etaBody");
  tbody.innerHTML = CALC_STOPS.map(s => {
    const frac = s.km / TOTAL_KM;
    let elapsed;
    if (model === "even") {
      elapsed = target * frac;
    } else {
      // Smooth progressive ultra fatigue curve: t(f) = target * (0.88*f + 0.12*f^2) -> 0 at 0, target at 1
      elapsed = target * (0.85 * frac + 0.15 * frac * frac);
    }
    let marginHtml = '<span style="color:#64748b">-</span>';
    if (s.cutHrs !== null) {
      const margin = s.cutHrs - elapsed;
      const cls = margin < 0 ? "bad" : (margin < 1.0 ? "warn" : "ok");
      marginHtml = `<span class="${cls}">${fmtDiff(margin)}</span>`;
    }
    return `<tr>
      <td><strong>${s.name}</strong></td>
      <td>${s.km.toFixed(1)}</td>
      <td>${fmtAEDT(elapsed)} (${elapsed.toFixed(1)}h)</td>
      <td>${s.cutLabel}</td>
      <td>${marginHtml}</td>
    </tr>`;
  }).join("");
}

document.getElementById("targetHrs").addEventListener("input", updateCalc);
document.getElementById("paceModel").addEventListener("change", updateCalc);

// Render Offline SVG Elevation Chart
function renderElevation() {
  const svg = document.getElementById("elevSvg");
  const pts = DB.course_profile || [];
  if (!pts.length) return;
  const W = 900, H = 245, padL = 42, padR = 14, padT = 18, padB = 26;
  const maxKm = 240.65, maxElev = 2300;
  const xOf = km => padL + (km / maxKm) * (W - padL - padR);
  const yOf = el => (H - padB) - (el / maxElev) * (H - padT - padB);

  let html = "";
  // Gridlines
  [0, 500, 1000, 1500, 2000].forEach(el => {
    const y = yOf(el).toFixed(1);
    html += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#1e293b" stroke-width="1"/>`;
    html += `<text x="${padL - 6}" y="${parseFloat(y) + 3}" text-anchor="end" fill="#64748b" font-size="10">${el}m</text>`;
  });
  [0, 50, 100, 150, 200, 240].forEach(km => {
    const x = xOf(km).toFixed(1);
    html += `<text x="${x}" y="${H - 7}" text-anchor="middle" fill="#64748b" font-size="10">${km}km</text>`;
  });

  // Polyline & Area
  const polyCoords = pts.map(p => `${xOf(p[2]).toFixed(1)},${yOf(p[3]).toFixed(1)}`).join(" ");
  const areaCoords = `${xOf(0).toFixed(1)},${yOf(0).toFixed(1)} ` + polyCoords + ` ${xOf(maxKm).toFixed(1)},${yOf(0).toFixed(1)}`;
  html += `<polygon points="${areaCoords}" fill="rgba(56,189,248,0.18)"/>`;
  html += `<polyline points="${polyCoords}" fill="none" stroke="#38bdf8" stroke-width="2"/>`;

  // Plot markers from Checkpoints + Toilets
  const pins = [
    { km: 24.43, el: 38, col: "#38bdf8", lbl: "CP1 Towamba" },
    { km: 51.67, el: 209, col: "#38bdf8", lbl: "CP2 Rocky Hall + Toilet" },
    { km: 57.23, el: 290, col: "#22c55e", lbl: "Big Jack Toilet" },
    { km: 69.65, el: 797, col: "#f59e0b", lbl: "CP3 Cathcart (Cut Fri 17:30)" },
    { km: 106.60, el: 925, col: "#f59e0b", lbl: "CP4 Snowy River Way (Cut Fri 23:30)" },
    { km: 147.98, el: 756, col: "#f59e0b", lbl: "CP5 Dalgety (Cut Sat 06:30)" },
    { km: 183.92, el: 924, col: "#f59e0b", lbl: "CP6 Jindabyne (Cut Sat 14:00)" },
    { km: 195.47, el: 1204, col: "#22c55e", lbl: "Sawpit Toilet (24h)" },
    { km: 213.11, el: 1722, col: "#38bdf8", lbl: "CP7 Perisher" },
    { km: 222.05, el: 1838, col: "#f59e0b", lbl: "CP8 Charlotte Pass (Cut Sat 23:00)" },
    { km: 231.30, el: 2228, col: "#ef4444", lbl: "Mt Kosciuszko Summit (2,228m)" }
  ];
  pins.forEach(p => {
    const cx = xOf(p.km).toFixed(1);
    const cy = yOf(p.el).toFixed(1);
    html += `<circle cx="${cx}" cy="${cy}" r="4.5" fill="${p.col}" stroke="#091526" stroke-width="1.5"><title>${p.lbl} (${p.km} km, ${p.el}m)</title></circle>`;
  });

  svg.innerHTML = html;
  svg.addEventListener("mousemove", ev => {
    const rect = svg.getBoundingClientRect();
    const rx = (ev.clientX - rect.left) / rect.width * W;
    const km = Math.max(0, Math.min(maxKm, ((rx - padL) / (W - padL - padR)) * maxKm));
    let best = pts[0];
    let bd = 1e9;
    for (const pt of pts) {
      const d = Math.abs(pt[2] - km);
      if (d < bd) { bd = d; best = pt; }
    }
    document.getElementById("elevHover").textContent = `${best[2].toFixed(1)} km | ${Math.round(best[3])} m elevation`;
  });
}

renderControls();
renderTable();
updateCalc();
renderElevation();
</script>
</body>
</html>
"""
    html_out = clean_dashes(html_template).replace("__C2K_JSON__", json_blob)
    out_path = BASE_DIR / "Coast2Kosci_2026_Interactive_Database.html"
    out_path.write_text(html_out, encoding="utf-8")
    print(f"Saved Offline Interactive HTML: {out_path.name} ({len(html_out):,} bytes)")
    return out_path


def update_readme(db):
    readme_text = """# Coast to Kosci (C2K) 2026 - Master Race Database

Comprehensive official race logistics database for the **Coast to Kosciuszko (C2K) 240 km Ultramarathon** (20 - 22 November 2026), compiled from [coasttokosci.com](https://coasttokosci.com), the 2026 Runners Guide, 2026 Race Schedule, Race Rules, Course Directions, RideWithGPS Route #41169431, TrackMeLive 2026, and the Australian Government National Public Toilet Map.

## Primary Files

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
"""
    readme_text = clean_dashes(readme_text)
    (BASE_DIR / "README.md").write_text(readme_text, encoding="utf-8")
    print("Updated README.md")


if __name__ == "__main__":
    db = json.loads((DATA_DIR / "c2k_2026_master_database.json").read_text(encoding="utf-8"))
    build_excel(db)
    build_html(db)
    update_readme(db)
