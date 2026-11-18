import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_scrape"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def clean_dashes(val):
    if not isinstance(val, str):
        return val
    # Replace em-dash and en-dash with clean ASCII hyphen spacing
    val = val.replace("\u2014", " - ").replace("\u2013", " - ")
    # Collapse accidental double spaces around hyphens while keeping ' - ' tidy
    while "  -  " in val:
        val = val.replace("  -  ", " - ")
    while "  - " in val:
        val = val.replace("  - ", " - ")
    while " -  " in val:
        val = val.replace(" -  ", " - ")
    return val


def sanitize_records(rows):
    return [{k: clean_dashes(v) for k, v in r.items()} for r in rows]


def gmaps_url(lat, lon):
    if lat is None or lon is None or lat == "" or lon == "":
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def fmt_pace(hours, km):
    if not hours or not km or km <= 0:
        return ""
    total_min_per_km = (hours * 60.0) / km
    mins = int(total_min_per_km)
    secs = int(round((total_min_per_km - mins) * 60))
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d} min/km"


def fmt_speed(hours, km):
    if not hours or not km or hours <= 0:
        return ""
    return f"{km / hours:.2f} km/h"


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def lookup_elev_on_track(pts, lat, lon, approx_km=None):
    best_d = 1e12
    best_tp = None
    for tp in pts:
        if approx_km is not None and abs((tp["d"] / 1000.0) - approx_km) > 8.0:
            continue
        dm = haversine_m(lat, lon, tp["y"], tp["x"])
        if dm < best_d:
            best_d = dm
            best_tp = tp
    if best_tp is None:
        for tp in pts:
            dm = haversine_m(lat, lon, tp["y"], tp["x"])
            if dm < best_d:
                best_d = dm
                best_tp = tp
    return round(best_tp.get("e", 0.0), 1) if best_tp else None


def build_all():
    rw = json.loads((RAW_DIR / "rwgps_41169431.json").read_text(encoding="utf-8"))
    pts = rw["track_points"]
    cues = rw["course_points"]
    tml_cps = json.loads(
        (RAW_DIR / "tracking" / "live.trackmelive.com.au_coasttokosci26_data_checkpoints.json.json").read_text(encoding="utf-8")
    )["data"]
    gov_toilets = json.loads((RAW_DIR / "corridor_towns_toilets_detailed.json").read_text(encoding="utf-8"))

    # Helper to find gov toilet record by substring
    def find_gov_toilet(substr):
        low = substr.lower()
        for t in gov_toilets:
            if low in f"{t['town']} {t['name']}".lower():
                return t
        return None

    # ------------------------------------------------------------------
    # TABLE 2: OFFICIAL CHECKPOINTS & HARD CUT-OFFS (2026)
    # ------------------------------------------------------------------
    checkpoints = [
        {
            "CP_Number": "Start",
            "Checkpoint_Name": "Boydtown Beach, Twofold Bay",
            "Guide_Distance_km": 0.0,
            "GPS_Track_km": 0.00,
            "Segment_Split_km": 0.0,
            "Elevation_m": 7,
            "Has_Hard_Cutoff": "No (Race Start)",
            "Cutoff_Day_Time_AEDT": "Fri 20 Nov 05:30 (Start)",
            "Cutoff_Elapsed_Hours": 0.0,
            "Min_Overall_Pace": "",
            "Min_Overall_Speed": "",
            "Check_In_Procedure": "Mandatory on-beach Registration 04:50 - 05:00; Welcome to Country 05:10; Start 05:30.",
            "Crew_Access": "Off-road parking at Boydtown Beach; DO NOT limit road access. After start, crews must NOT meet or stop for runner until CP1 Towamba (24.5 km).",
            "Pacer_Status": "Not permitted (except mandatory sections later).",
            "Facilities_At_CP": "STRICTLY NO TOILETS AT START LINE - PENALTIES APPLY (bushes prohibited). Nearest 24h pre-start public toilets: Quarantine Bay (2.0 km) or Eden Rotary Park / Wharf (~4 km).",
            "Latitude": -37.092121,
            "Longitude": 149.871246,
            "Google_Maps_URL": gmaps_url(-37.092121, 149.871246),
        },
        {
            "CP_Number": "CP 1",
            "Checkpoint_Name": "Towamba (Towamba Rd & Pericoe Rd)",
            "Guide_Distance_km": 24.5,
            "GPS_Track_km": 24.43,
            "Segment_Split_km": 24.5,
            "Elevation_m": 38,
            "Has_Hard_Cutoff": "No",
            "Cutoff_Day_Time_AEDT": "No hard cut-off",
            "Cutoff_Elapsed_Hours": "",
            "Min_Overall_Pace": "",
            "Min_Overall_Speed": "",
            "Check_In_Procedure": "Mandatory checkpoint. Support Crew Chief texts C2K WhatsApp group confirming runner name, bib, CP1 Towamba, time, and fitness to continue.",
            "Crew_Access": "FIRST CREW RENDEZVOUS POINT. Park safely past junction of Towamba Rd & Pericoe Rd. Fit yellow/black Runner Ahead & Runner Following signs from Towamba onwards.",
            "Pacer_Status": "Not permitted until sunset (~20:30) or CP4, except mandatory Big Jack section at 57.3 km.",
            "Facilities_At_CP": "Towamba Public School BBQ breakfast fundraiser (cash preferred). Toilets at Towamba / Towamba Hall (24h, shower, ~690m off intersection) & Towamba sports fields.",
            "Latitude": -37.081589,
            "Longitude": 149.694107,
            "Google_Maps_URL": gmaps_url(-37.081589, 149.694107),
        },
        {
            "CP_Number": "CP 2",
            "Checkpoint_Name": "Rocky Hall (Public Telephone)",
            "Guide_Distance_km": 51.7,
            "GPS_Track_km": 51.67,
            "Segment_Split_km": 27.2,
            "Elevation_m": 209,
            "Has_Hard_Cutoff": "No",
            "Cutoff_Day_Time_AEDT": "No hard cut-off",
            "Cutoff_Elapsed_Hours": "",
            "Min_Overall_Pace": "",
            "Min_Overall_Speed": "",
            "Check_In_Procedure": "Mandatory checkpoint at Rocky Hall public telephone (left-hand side of road). Crew Chief checks runner in via C2K WhatsApp group.",
            "Crew_Access": "Full crew access (leapfrog ~5 km). Prepare runner & 1 pacer for upcoming Big Jack Mountain ascent (starts ~57.2-57.3 km).",
            "Pacer_Status": "General pacing not yet open (unless after sunset); mandatory 1 pacer starts ahead at 57.3 km (Big Jack Mountain).",
            "Facilities_At_CP": "Rocky Hall Society coffee & snacks (CASH ONLY). Public restrooms right at Rocky Hall CP2 (51.68 km on official route map).",
            "Latitude": -36.927048,
            "Longitude": 149.503311,
            "Google_Maps_URL": gmaps_url(-36.927048, 149.503311),
        },
        {
            "CP_Number": "CP 3",
            "Checkpoint_Name": "Cathcart (Cathcart General Store)",
            "Guide_Distance_km": 69.8,
            "GPS_Track_km": 69.65,
            "Segment_Split_km": 18.1,
            "Elevation_m": 797,
            "Has_Hard_Cutoff": "YES - HARD CUT-OFF #1",
            "Cutoff_Day_Time_AEDT": "Fri 20 Nov 17:30 AEDT",
            "Cutoff_Elapsed_Hours": 12.0,
            "Min_Overall_Pace": fmt_pace(12.0, 70.0),
            "Min_Overall_Speed": fmt_speed(12.0, 70.0),
            "Check_In_Procedure": "Mandatory checkpoint & Cut-Off #1 (schedule lists 70 km / 12 hrs). Crew Chief reports pass time & fitness in C2K WhatsApp group. Runners behind 17:30 may be withdrawn.",
            "Crew_Access": "Full crew access; note runner undertakes U-turn at Cathcart General Store (right-hand side of Eden St) before continuing onto Cathcart Rd.",
            "Pacer_Status": "Not permitted until sunset (~20:30) or CP4.",
            "Facilities_At_CP": "Cathcart General Store drinks & snacks (CASH ONLY). Public toilets & water/shower at Cathcart Rest Area ~200m past store (69.87 km, Daylight hours).",
            "Latitude": -36.843208,
            "Longitude": 149.391190,
            "Google_Maps_URL": gmaps_url(-36.843208, 149.391190),
        },
        {
            "CP_Number": "CP 4",
            "Checkpoint_Name": "Gunningrach Rd & Snowy River Way",
            "Guide_Distance_km": 106.7,
            "GPS_Track_km": 106.60,
            "Segment_Split_km": 36.9,
            "Elevation_m": 925,
            "Has_Hard_Cutoff": "YES - HARD CUT-OFF #2",
            "Cutoff_Day_Time_AEDT": "Fri 20 Nov 23:30 AEDT",
            "Cutoff_Elapsed_Hours": 18.0,
            "Min_Overall_Pace": fmt_pace(18.0, 106.7),
            "Min_Overall_Speed": fmt_speed(18.0, 106.7),
            "Check_In_Procedure": "Mandatory checkpoint & Cut-Off #2 (schedule lists 106 km / 18 hrs). Landmark: disused livestock ramp. Marshal road crossing. Crew Chief reports via C2K WhatsApp group.",
            "Crew_Access": "Full crew access. Note poor/zero mobile signal right at Gunningrach Rd; move along Snowy River Way if needed for WhatsApp update. Reflective vest MANDATORY for runner & pacer from CP4 to Finish.",
            "Pacer_Status": "General pacing PERMITTED from CP4 (106.7 km) onwards to finish (1 pacer at a time).",
            "Facilities_At_CP": "NO public toilets or shops at intersection. Mobile crew aid only (carry water/food/warm night gear).",
            "Latitude": -36.690868,
            "Longitude": 149.159988,
            "Google_Maps_URL": gmaps_url(-36.690868, 149.159988),
        },
        {
            "CP_Number": "CP 5",
            "Checkpoint_Name": "Dalgety (Memorial Hall & Dalgety Bridge)",
            "Guide_Distance_km": 148.0,
            "GPS_Track_km": 147.98,
            "Segment_Split_km": 41.3,
            "Elevation_m": 756,
            "Has_Hard_Cutoff": "YES - HARD CUT-OFF #3",
            "Cutoff_Day_Time_AEDT": "Sat 21 Nov 06:30 AEDT",
            "Cutoff_Elapsed_Hours": 25.0,
            "Min_Overall_Pace": fmt_pace(25.0, 148.25),
            "Min_Overall_Speed": fmt_speed(25.0, 148.25),
            "Check_In_Procedure": "Mandatory checkpoint at Dalgety Memorial Hall (148.0 km); Cut-Off #3 at 06:30 is enforced across Dalgety Bridge on West side (148.25 km). Crew Chief reports via C2K WhatsApp group.",
            "Crew_Access": "Full crew access. Strict parking/resident noise respect at dawn. Prepare for Beloka Hill ahead (162-165 km).",
            "Pacer_Status": "Permitted (1 pacer at a time; must wear reflective vest + flashing rear light).",
            "Facilities_At_CP": "Dalgety Hall hot soup & refreshments for RUNNERS & SUPPORT CREW ONLY (not spectators/family). TOILET RULE: Hall indoor toilets are RUNNERS ONLY; Crews MUST use building 50-100m behind Hall (Brierly St public toilets / drinking water).",
            "Latitude": -36.504173,
            "Longitude": 148.834229,
            "Google_Maps_URL": gmaps_url(-36.504173, 148.834229),
        },
        {
            "CP_Number": "CP 6",
            "Checkpoint_Name": "Jindabyne (Caravan & Holiday Discovery Park)",
            "Guide_Distance_km": 183.8,
            "GPS_Track_km": 183.92,
            "Segment_Split_km": 35.8,
            "Elevation_m": 924,
            "Has_Hard_Cutoff": "YES - HARD CUT-OFF #4",
            "Cutoff_Day_Time_AEDT": "Sat 21 Nov 14:00 AEDT",
            "Cutoff_Elapsed_Hours": 32.5,
            "Min_Overall_Pace": fmt_pace(32.5, 184.0),
            "Min_Overall_Speed": fmt_speed(32.5, 184.0),
            "Check_In_Procedure": "Mandatory checkpoint & Cut-Off #4 at entrance of Jindabyne Caravan & Holiday Discovery Park (note 2026 cut-off is 14:00 / 32.5 hrs). Crew Chief reports via C2K WhatsApp group.",
            "Crew_Access": "Crew turns LEFT at Barry Way / Kosciuszko Rd roundabout towards Perisher (or RIGHT into Jindabyne town for groceries/fuel), then meets runner exiting Caravan Park onto Kosciuszko Rd.",
            "Pacer_Status": "Permitted (1 pacer at a time).",
            "Facilities_At_CP": "Main late-race town resupply (~7am-7pm/8pm; Shell adjacent closes 4pm; BP closes 10pm). 24h public toilet & water on lake path at Claypits Foreshore Park (181.9 km) & Kalkite St (24h). Note: Town Centre toilets listed as closed for renovation.",
            "Latitude": -36.409264,
            "Longitude": 148.597031,
            "Google_Maps_URL": gmaps_url(-36.409264, 148.597031),
        },
        {
            "CP_Number": "CP 7",
            "Checkpoint_Name": "Perisher Valley (Ski-Tube Bus Shelter)",
            "Guide_Distance_km": 212.9,
            "GPS_Track_km": 213.11,
            "Segment_Split_km": 29.1,
            "Elevation_m": 1722,
            "Has_Hard_Cutoff": "No",
            "Cutoff_Day_Time_AEDT": "No standalone cut-off (must clear CP8 Charlotte Pass by 23:00)",
            "Cutoff_Elapsed_Hours": "",
            "Min_Overall_Pace": "",
            "Min_Overall_Speed": "",
            "Check_In_Procedure": "Mandatory checkpoint at bus shelter in front of Perisher Ski-Tube Station (right-hand side). Crew Chief reports pass & fitness via C2K WhatsApp group.",
            "Crew_Access": "Full crew access via Kosciuszko Rd. Final gear/thermal staging before Charlotte Pass summit inspection.",
            "Pacer_Status": "Permitted (1 pacer at a time).",
            "Facilities_At_CP": "Bus shelter landmark. Note: No 24h public toilet confirmed on National Public Toilet Map at Perisher; use Sawpit Rest Area (195.5 km, 24h) prior or Charlotte Pass Lookout (222.1 km, 24h) ahead.",
            "Latitude": -36.404984,
            "Longitude": 148.412201,
            "Google_Maps_URL": gmaps_url(-36.404984, 148.412201),
        },
        {
            "CP_Number": "CP 8",
            "Checkpoint_Name": "Charlotte Pass (Turnaround Loop Car Park)",
            "Guide_Distance_km": 221.8,
            "GPS_Track_km": 222.05,
            "Segment_Split_km": 8.9,
            "Elevation_m": 1838,
            "Has_Hard_Cutoff": "YES - HARD CUT-OFF #5",
            "Cutoff_Day_Time_AEDT": "Sat 21 Nov 23:00 AEDT",
            "Cutoff_Elapsed_Hours": 41.5,
            "Min_Overall_Pace": fmt_pace(41.5, 222.0),
            "Min_Overall_Speed": fmt_speed(41.5, 222.0),
            "Check_In_Procedure": "Mandatory checkpoint & Cut-Off #5 (23:00 Sat / 41.5 hrs). Officials inspect ALL Mandatory Summit Path Gear for runner & pacer(s) + assess runner fitness + authorise departure. Any rule time penalties served here.",
            "Crew_Access": "Final vehicle support point before 18.4 km Summit Path out-and-back. Vehicles must obey all NPWS parking signage & restrictions. Protect wildlife (secure food from ravens/currawongs).",
            "Pacer_Status": "MANDATORY pacer(s) from Charlotte Pass to Mt Kosciuszko Summit and return (222-240 km). MULTIPLE support crew may accompany on the Summit Path!",
            "Facilities_At_CP": "24h public toilets at Charlotte Pass Lookout car park (22m off course).",
            "Latitude": -36.431606,
            "Longitude": 148.328827,
            "Google_Maps_URL": gmaps_url(-36.431606, 148.328827),
        },
        {
            "CP_Number": "Summit",
            "Checkpoint_Name": "Mount Kosciuszko Summit (2,228 m)",
            "Guide_Distance_km": 231.0,
            "GPS_Track_km": 231.30,
            "Segment_Split_km": 9.2,
            "Elevation_m": 2228,
            "Has_Hard_Cutoff": "No (Turnaround point)",
            "Cutoff_Day_Time_AEDT": "Must return to Finish by Sun 03:30",
            "Cutoff_Elapsed_Hours": "",
            "Min_Overall_Pace": "",
            "Min_Overall_Speed": "",
            "Check_In_Procedure": "Turnaround control point via GPS tracker (TrackMeLive). Touch/reach summit, do NOT stand or climb on summit cairn (NPWS rule - penalty/DQ!), turn around and descend same Summit Walk.",
            "Crew_Access": "NO vehicle access (Summit Walk foot path only).",
            "Pacer_Status": "MANDATORY accompaniment by at least 1 pacer (multiple support crew allowed). Mandatory Summit Gear must be carried by runner/pacer/crew.",
            "Facilities_At_CP": "No toilets at summit itself. Nearest alpine toilets & emergency shelters: Rawson Pass (229.6 km outbound / 232.9 km return, 24h) and Seamans Hut (228.1 km outbound / 234.6 km return, 24h).",
            "Latitude": -36.455849,
            "Longitude": 148.263550,
            "Google_Maps_URL": gmaps_url(-36.455849, 148.263550),
        },
        {
            "CP_Number": "Finish",
            "Checkpoint_Name": "Charlotte Pass (Summit Road Trailhead)",
            "Guide_Distance_km": 240.0,
            "GPS_Track_km": 240.65,
            "Segment_Split_km": 9.0,
            "Elevation_m": 1839,
            "Has_Hard_Cutoff": "YES - FINAL FINISH CUT-OFF",
            "Cutoff_Day_Time_AEDT": "Sun 22 Nov 03:30 AEDT",
            "Cutoff_Elapsed_Hours": 46.0,
            "Min_Overall_Pace": fmt_pace(46.0, 240.65),
            "Min_Overall_Speed": fmt_speed(46.0, 240.65),
            "Check_In_Procedure": "Official Race Finish. Return GPS tracker immediately (mandatory or DQ!). Warm, feed & hydrate runner; ensure rested driver for descent to Jindabyne.",
            "Crew_Access": "Crew vehicles wait at Charlotte Pass car park; follow parking rules and drive cautiously down Kosciuszko Rd (wildlife & fatigued drivers).",
            "Pacer_Status": "Mandatory pacer(s) finish together with runner.",
            "Facilities_At_CP": "24h public toilets at Charlotte Pass Lookout. Post-race breakfast (pre-paid $21/head), return of yellow vehicle signs/trackers (07:00-09:00) & Presentation (09:00-11:00) at Adventist Alpine Village, Jindabyne.",
            "Latitude": -36.431729,
            "Longitude": 148.328413,
            "Google_Maps_URL": gmaps_url(-36.431729, 148.328413),
        },
    ]

    # ------------------------------------------------------------------
    # TABLE 3: TOILETS, AID STATIONS & COMMUNITY REFRESHMENTS
    # ------------------------------------------------------------------
    toilets_aid = [
        {
            "Stop_ID": "TA-00",
            "Distance_km": 0.00,
            "Location_Name": "Boydtown Beach Start Line (Twofold Bay)",
            "Stop_Category": "PROHIBITED / NO TOILETS ZONE",
            "Authority": "Official C2K 2026 Runners Guide (p.27)",
            "Toilet_Available": "NO - STRICTLY PROHIBITED",
            "Opening_Hours": "N/A",
            "Food_Drink_Aid": "None",
            "Payment_Method": "N/A",
            "Drinking_Water": "No",
            "Shower": "No",
            "Wheelchair_Accessible": "No",
            "Off_Course_Distance_m": 0,
            "Crew_And_Runner_Rules": "THERE ARE NO TOILETS AT THE START LINE - PENALTIES APPLY. Bushes must NOT be used. Use pre-start toilets in Eden or Seahorse Inn / accommodation before arriving at Boydtown Beach.",
            "Latitude": -37.092121,
            "Longitude": 149.871246,
            "Google_Maps_URL": gmaps_url(-37.092121, 149.871246),
        },
        {
            "Stop_ID": "TA-01",
            "Distance_km": 0.89,
            "Location_Name": "Quarantine Bay Public Toilet (Pre-Start Option, Eden)",
            "Stop_Category": "Public Toilet (Pre-Start)",
            "Authority": "National Public Toilet Map (AU Dept of Health)",
            "Toilet_Available": "Yes (24h Public Toilet)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "None",
            "Payment_Method": "Free",
            "Drinking_Water": "False",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 1985,
            "Crew_And_Runner_Rules": "Nearest 24-hour public toilet to Boydtown Beach (~2 km). Use BEFORE arriving for 04:50 start-line check-in (note Ampol Eden only opens 06:00).",
            "Latitude": -37.076300,
            "Longitude": 149.884580,
            "Google_Maps_URL": gmaps_url(-37.076300, 149.884580),
        },
        {
            "Stop_ID": "TA-02",
            "Distance_km": 3.74,
            "Location_Name": "Aid Station #1 (Brandy Creek Trail / Nullica Rd & Towamba Rd)",
            "Stop_Category": "Official Race Aid Station",
            "Authority": "Official C2K Course Map & Rules",
            "Toilet_Available": "No",
            "Opening_Hours": "Race morning (approx 05:45 - 06:45)",
            "Food_Drink_Aid": "Minimal water, electrolyte/drink & light snacks provided by race crew. ONLY race aid before Towamba (24.5 km).",
            "Payment_Method": "Free (Included)",
            "Drinking_Water": "Yes (Limited race aid)",
            "Shower": "No",
            "Wheelchair_Accessible": "No",
            "Off_Course_Distance_m": 1,
            "Crew_And_Runner_Rules": "Support crews are FORBIDDEN to stop or meet runners before Towamba (24.5 km). Carry whatever nutrition/fluid you need from Boydtown to Towamba.",
            "Latitude": -37.089905,
            "Longitude": 149.843209,
            "Google_Maps_URL": gmaps_url(-37.089905, 149.843209),
        },
        {
            "Stop_ID": "TA-03",
            "Distance_km": 24.47,
            "Location_Name": "Towamba (CP1 Rendezvous, Public School BBQ & Towamba Hall)",
            "Stop_Category": "Official CP + Community Aid + 24h Public Toilet",
            "Authority": "Official C2K 2026 Runners Guide (p.23, p.27) + National Public Toilet Map",
            "Toilet_Available": "Yes (Towamba Hall 24h + Towamba sports fields)",
            "Opening_Hours": "Towamba Hall: OPEN 24 hours",
            "Food_Drink_Aid": "Towamba Public School BBQ breakfast fundraiser for runners & crews; crew vehicle mobile aid begins here.",
            "Payment_Method": "CASH PREFERRED (School fundraiser)",
            "Drinking_Water": "At crew / school",
            "Shower": "Yes (Towamba Hall listed)",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 689,
            "Crew_And_Runner_Rules": "First support crew stop. Park safely past Towamba Rd / Pericoe Rd junction. Remember: if runner deviates off route to use Towamba Hall/sports field toilets (~690m-1.2km), must re-enter course at exact exit point.",
            "Latitude": -37.081612,
            "Longitude": 149.693848,
            "Google_Maps_URL": gmaps_url(-37.081612, 149.693848),
        },
        {
            "Stop_ID": "TA-04",
            "Distance_km": 51.68,
            "Location_Name": "Rocky Hall (CP2, Restrooms & Rocky Hall Society)",
            "Stop_Category": "Official CP + Community Aid + Official Toilet",
            "Authority": "Official C2K 2026 Runners Guide (p.23, p.27) & RWGPS POI",
            "Toilet_Available": "Yes (Official Restrooms right at Rocky Hall CP2)",
            "Opening_Hours": "Race day hours",
            "Food_Drink_Aid": "Rocky Hall Society coffee and snacks for runners & support crews + crew mobile aid.",
            "Payment_Method": "CASH ONLY",
            "Drinking_Water": "At crew / stall",
            "Shower": "No",
            "Wheelchair_Accessible": "Unknown",
            "Off_Course_Distance_m": 0,
            "Crew_And_Runner_Rules": "Public telephone checkpoint on left-hand side of road. Prep mandatory 1 pacer before Big Jack Mountain climb (57.3 km).",
            "Latitude": -36.927101,
            "Longitude": 149.503274,
            "Google_Maps_URL": gmaps_url(-36.927101, 149.503274),
        },
        {
            "Stop_ID": "TA-05",
            "Distance_km": 57.23,
            "Location_Name": "Base of Big Jack Mountain (Opposite Park)",
            "Stop_Category": "Official Guide Toilet Stop",
            "Authority": "Official C2K 2026 Runners Guide (p.27) & RWGPS POI",
            "Toilet_Available": "Yes (Opposite side of road to the park)",
            "Opening_Hours": "24 hours (Public park restroom)",
            "Food_Drink_Aid": "Crew mobile aid only before steep climb",
            "Payment_Method": "Free",
            "Drinking_Water": "Unconfirmed (rely on crew)",
            "Shower": "No",
            "Wheelchair_Accessible": "Unknown",
            "Off_Course_Distance_m": 0,
            "Crew_And_Runner_Rules": "Last toilet before climbing Big Jack Mountain / Cow Bail Trail (57.3-64.1 km). Mandatory 1 pacer starts here; run on LEFT-hand side of road.",
            "Latitude": -36.897993,
            "Longitude": 149.463533,
            "Google_Maps_URL": gmaps_url(-36.897993, 149.463533),
        },
        {
            "Stop_ID": "TA-06",
            "Distance_km": 69.87,
            "Location_Name": "Cathcart (CP3 General Store & Rest Area ~200m past store)",
            "Stop_Category": "Official CP / Cut-Off #1 + Store + Official Toilet",
            "Authority": "Official C2K 2026 Runners Guide (p.23, p.27) + National Public Toilet Map",
            "Toilet_Available": "Yes (Cathcart Rest Area ~200m past Cathcart General Store)",
            "Opening_Hours": "OPEN: Daylight hours (store & rest area)",
            "Food_Drink_Aid": "Cathcart General Store drinks & snacks (Cut-Off #1 Fri 17:30).",
            "Payment_Method": "CASH ONLY (General Store)",
            "Drinking_Water": "True (Rest Area)",
            "Shower": "True (Rest Area)",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 19,
            "Crew_And_Runner_Rules": "Runner does U-turn at Cathcart General Store (69.65 km) then passes restrooms ~200m further on (69.87 km). Carry cash as mobile signal/EFTPOS is unreliable.",
            "Latitude": -36.843436,
            "Longitude": 149.389075,
            "Google_Maps_URL": gmaps_url(-36.843436, 149.389075),
        },
        {
            "Stop_ID": "TA-07",
            "Distance_km": 77.39,
            "Location_Name": "Black Lake Reserve (Bibbenluke approach)",
            "Stop_Category": "Public Toilet (Corridor)",
            "Authority": "National Public Toilet Map (AU Dept of Health)",
            "Toilet_Available": "Yes (24h Park / Reserve Toilet)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "None (Crew mobile aid)",
            "Payment_Method": "Free",
            "Drinking_Water": "False",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 215,
            "Crew_And_Runner_Rules": "Useful 24h toilet along Black Lake Rd shortly before Monaro Hwy crossing at Bibbenluke (81.0 km). Resume exact point if deviating 215m.",
            "Latitude": -36.814000,
            "Longitude": 149.318000,
            "Google_Maps_URL": gmaps_url(
                find_gov_toilet("Black Lake")["lat"], find_gov_toilet("Black Lake")["lon"]
            ) if find_gov_toilet("Black Lake") else "",
        },
        {
            "Stop_ID": "TA-08",
            "Distance_km": 106.60,
            "Location_Name": "Gunningrach Rd & Snowy River Way (CP4 / Cut-Off #2)",
            "Stop_Category": "Official CP / Cut-Off #2 (NO FIXED FACILITIES)",
            "Authority": "Official C2K 2026 Runners Guide & Course Directions",
            "Toilet_Available": "NO fixed toilets or shops",
            "Opening_Hours": "N/A (Cut-Off Fri 23:30)",
            "Food_Drink_Aid": "Crew mobile aid only (disused livestock ramp). Stock up thoroughly for 41 km overnight leg to Dalgety.",
            "Payment_Method": "N/A",
            "Drinking_Water": "No (Crew must carry)",
            "Shower": "No",
            "Wheelchair_Accessible": "No",
            "Off_Course_Distance_m": 0,
            "Crew_And_Runner_Rules": "No public toilets, no shops, weak/no mobile phone signal. Leave No Trace strictly applies (pack out all toilet paper & wrappers in crew vehicle). Reflective vest mandatory from here.",
            "Latitude": -36.690868,
            "Longitude": 149.159988,
            "Google_Maps_URL": gmaps_url(-36.690868, 149.159988),
        },
        {
            "Stop_ID": "TA-09",
            "Distance_km": 148.03,
            "Location_Name": "Dalgety Memorial Hall & Rear Public Toilets (CP5 / Cut-Off #3)",
            "Stop_Category": "Official CP / Cut-Off #3 + Community Soup + Segregated Toilets",
            "Authority": "Official C2K 2026 Runners Guide (p.23, p.27) + National Public Toilet Map",
            "Toilet_Available": "Yes - SEGREGATED: Hall indoor toilets = RUNNERS ONLY; Rear building (50-100m behind Hall / Brierly St) = Support Crew & others.",
            "Opening_Hours": "Hall open overnight/early Sat for race; Brierly St rear park toilet listed Daylight hours (check race access).",
            "Food_Drink_Aid": "Dalgety Hall hot soup and refreshments for RUNNERS AND SUPPORT CREWS ONLY (not spectators/family/friends).",
            "Payment_Method": "Race/Community provision (bring cash if village service station/pub visited during daylight)",
            "Drinking_Water": "True (Brierly St / Hall)",
            "Shower": "False",
            "Wheelchair_Accessible": "True (Brierly St)",
            "Off_Course_Distance_m": 15,
            "Crew_And_Runner_Rules": "CRITICAL TOILET RULE (2026 Guide p.27): Dalgety Hall toilets are strictly RUNNERS ONLY. Support crews MUST use the toilet building 50-100m beyond the rear of Dalgety Hall. Note Dalgety service station/pub have very limited daytime hours.",
            "Latitude": -36.504125,
            "Longitude": 148.833730,
            "Google_Maps_URL": gmaps_url(-36.504125, 148.833730),
        },
        {
            "Stop_ID": "TA-10",
            "Distance_km": 181.88,
            "Location_Name": "Jindabyne Foreshore / Claypits Park (Opposite Roundabout)",
            "Stop_Category": "Official Guide Toilet Stop + 24h Drinking Water",
            "Authority": "Official C2K 2026 Runners Guide (p.27) + National Public Toilet Map",
            "Toilet_Available": "Yes (24h Public Toilet right on bike path, 11m off course)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "Drinking water tap; Jindabyne town shops/supermarkets/BP 550-800m detour (~7am-7pm/8pm; BP 6am-10pm).",
            "Payment_Method": "Free toilet; card/cash in town",
            "Drinking_Water": "True",
            "Shower": "False",
            "Wheelchair_Accessible": "True",
            "Off_Course_Distance_m": 11,
            "Crew_And_Runner_Rules": "Runner joins Lake Jindabyne foreshore path here. Main resupply window for food, ice, fuel & supplies before mountain ascent (many Jindabyne shops close ~7pm). Note: Jindabyne Town Centre toilets currently closed for renovation.",
            "Latitude": find_gov_toilet("Claypits")["lat"] if find_gov_toilet("Claypits") else -36.4139,
            "Longitude": find_gov_toilet("Claypits")["lon"] if find_gov_toilet("Claypits") else 148.6098,
            "Google_Maps_URL": gmaps_url(
                find_gov_toilet("Claypits")["lat"], find_gov_toilet("Claypits")["lon"]
            ) if find_gov_toilet("Claypits") else gmaps_url(-36.4139, 148.6098),
        },
        {
            "Stop_ID": "TA-11",
            "Distance_km": 183.92,
            "Location_Name": "Jindabyne Caravan & Holiday Discovery Park + Shell (CP6 / Cut-Off #4)",
            "Stop_Category": "Official CP / Cut-Off #4 + Adjacent Service Station",
            "Authority": "Official C2K 2026 Runners Guide + National Public Toilet Map",
            "Toilet_Available": "Yes (Shell Jindabyne 14m across road 6am-4pm; Caravan Park reception area for check-in)",
            "Opening_Hours": "Shell: 6am-4pm; Cut-Off #4 Sat 14:00",
            "Food_Drink_Aid": "Shell service station snacks/fuel/ice + crew mobile aid.",
            "Payment_Method": "Card / Cash",
            "Drinking_Water": "False (at Shell; water at Claypits 181.9 km)",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 14,
            "Crew_And_Runner_Rules": "Rejoin Kosciuszko Rd at service station. Note Shell closes 4pm; Nugget's Crossing / supermarkets close ~7-8pm; BP Jindabyne open until 10pm. Plan alpine supplies BEFORE leaving Jindabyne.",
            "Latitude": -36.409264,
            "Longitude": 148.597031,
            "Google_Maps_URL": gmaps_url(-36.409264, 148.597031),
        },
        {
            "Stop_ID": "TA-12",
            "Distance_km": 189.75,
            "Location_Name": "Little Thredbo River Rest Area (Kosciuszko Rd)",
            "Stop_Category": "Public Toilet (National Park)",
            "Authority": "National Public Toilet Map (AU Dept of Health)",
            "Toilet_Available": "Yes (24h Rest Area Toilet, 69m off course)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "None (Crew mobile aid)",
            "Payment_Method": "Free",
            "Drinking_Water": "False",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 69,
            "Crew_And_Runner_Rules": "Kosciuszko National Park entry corridor. Pack out all rubbish; never leave food accessible to wildlife.",
            "Latitude": find_gov_toilet("Little Thredbo")["lat"] if find_gov_toilet("Little Thredbo") else -36.364,
            "Longitude": find_gov_toilet("Little Thredbo")["lon"] if find_gov_toilet("Little Thredbo") else 148.580,
            "Google_Maps_URL": gmaps_url(
                find_gov_toilet("Little Thredbo")["lat"], find_gov_toilet("Little Thredbo")["lon"]
            ) if find_gov_toilet("Little Thredbo") else "",
        },
        {
            "Stop_ID": "TA-13",
            "Distance_km": 195.47,
            "Location_Name": "Sawpit Creek Rest Area (Kosciuszko Rd)",
            "Stop_Category": "Public Toilet (National Park)",
            "Authority": "National Public Toilet Map (AU Dept of Health)",
            "Toilet_Available": "Yes (24h Rest Area Toilet, 50m off course)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "None (Crew mobile aid)",
            "Payment_Method": "Free",
            "Drinking_Water": "False",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 50,
            "Crew_And_Runner_Rules": "Last confirmed 24-hour public toilet on Kosciuszko Rd before Perisher (no 24h public toilet confirmed in Perisher Valley) and Charlotte Pass (222 km).",
            "Latitude": find_gov_toilet("Sawpit")["lat"] if find_gov_toilet("Sawpit") else -36.345,
            "Longitude": find_gov_toilet("Sawpit")["lon"] if find_gov_toilet("Sawpit") else 148.567,
            "Google_Maps_URL": gmaps_url(
                find_gov_toilet("Sawpit")["lat"], find_gov_toilet("Sawpit")["lon"]
            ) if find_gov_toilet("Sawpit") else "",
        },
        {
            "Stop_ID": "TA-14",
            "Distance_km": 222.05,
            "Location_Name": "Charlotte Pass Lookout & Turnaround Car Park (CP8 / Cut-Off #5 / Finish)",
            "Stop_Category": "Official CP / Cut-Off #5 / Finish + 24h Alpine Toilet",
            "Authority": "Official C2K 2026 Runners Guide (p.27) + National Public Toilet Map",
            "Toilet_Available": "Yes (24h NPWS Public Toilets at Lookout Car Park, 10-22m off course)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "Crew mobile aid & hot food/gear staging at car park (NO open commercial shops late Saturday night).",
            "Payment_Method": "Free",
            "Drinking_Water": "False (Carry water from crew)",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 22,
            "Crew_And_Runner_Rules": "Mandatory Summit Gear check & Fitness Assessment at CP8 before entering Summit Path. Strictly secure all crew food inside locked vehicles from ravens & currawongs.",
            "Latitude": -36.431606,
            "Longitude": 148.328827,
            "Google_Maps_URL": gmaps_url(-36.431606, 148.328827),
        },
        {
            "Stop_ID": "TA-15",
            "Distance_km": 228.06,
            "Location_Name": "Seamans Hut (Summit Path - passed outbound ~228.1 km & return ~234.6 km)",
            "Stop_Category": "Official Alpine Emergency Shelter & 24h Toilet",
            "Authority": "Official C2K 2026 Runners Guide (p.15, p.27) + National Public Toilet Map",
            "Toilet_Available": "Yes (24h Pit Toilet adjacent to stone emergency hut)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "No supplies (Emergency alpine shelter ONLY; carry all food/water from Charlotte Pass).",
            "Payment_Method": "Free",
            "Drinking_Water": "False",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 31,
            "Crew_And_Runner_Rules": "6 km from Charlotte Pass. Emergency shelter in severe alpine weather. Human waste and toilet paper must NEVER be left beside Summit Path.",
            "Latitude": -36.450278,
            "Longitude": 148.282633,
            "Google_Maps_URL": gmaps_url(-36.450278, 148.282633),
        },
        {
            "Stop_ID": "TA-16",
            "Distance_km": 229.64,
            "Location_Name": "Rawson Pass (Summit Path - passed outbound ~229.6 km & return ~232.9 km)",
            "Stop_Category": "Official Alpine Emergency Shelter & 24h Toilet",
            "Authority": "Official C2K 2026 Runners Guide (p.15, p.27) + National Public Toilet Map",
            "Toilet_Available": "Yes (24h Australia's highest public toilets + emergency shelter)",
            "Opening_Hours": "OPEN: 24 hours",
            "Food_Drink_Aid": "No supplies (Emergency shelter ONLY).",
            "Payment_Method": "Free",
            "Drinking_Water": "False",
            "Shower": "False",
            "Wheelchair_Accessible": "False",
            "Off_Course_Distance_m": 16,
            "Crew_And_Runner_Rules": "7.6 km from Charlotte Pass, 1.6 km below Mt Kosciuszko Summit. Last toilet before summit turnaround.",
            "Latitude": -36.457690,
            "Longitude": 148.268770,
            "Google_Maps_URL": gmaps_url(-36.457690, 148.268770),
        },
    ]

    # Fix Black Lake (TA-07) coords cleanly from gov_toilets without overwriting TA-06 Cathcart
    bl = find_gov_toilet("Black Lake")
    if bl:
        for item in toilets_aid:
            if item.get("Stop_ID") == "TA-07":
                item["Latitude"] = bl["lat"]
                item["Longitude"] = bl["lon"]
                item["Google_Maps_URL"] = gmaps_url(bl["lat"], bl["lon"])
                break

    # ------------------------------------------------------------------
    # TABLE 1: MASTER COURSE WAYPOINTS (0.0 km -> 240.65 km)
    # ------------------------------------------------------------------
    waypoints = [
        {
            "Waypoint_ID": "WP-01",
            "Distance_km": 0.00,
            "Location_Name": "Boydtown Beach Start Line (Twofold Bay)",
            "Category": "Start",
            "Official_CP_Number": "Start",
            "Elevation_m": 7,
            "Cutoff_Time_AEDT": "Fri 05:30 (Race Start)",
            "Cutoff_Elapsed_Hrs": 0.0,
            "Toilet_Status": "STRICTLY NO TOILETS - PENALTIES APPLY",
            "Aid_Food_Supplies_Info": "Self-sufficient from start to Towamba (except minimal Aid Station at 3.7 km).",
            "Crew_And_Vehicle_Rules": "Check-in 04:50-05:00; Welcome to Country 05:10; Start 05:30. Vehicle signage check Thu or before leaving beach car park. NO crew support until Towamba (24.5 km).",
            "Pacer_Rules": "No pacers allowed.",
            "Gear_Requirements": "Race bib visible; GPS tracker ON; Flashing rear red light ON (24/7).",
            "Surface_And_Terrain": "Beach sand / coastal road (Nullica Mouth Rd).",
            "Source_Authority": "Official C2K 2026 Guide & Schedule",
            "Latitude": -37.092035,
            "Longitude": 149.872274,
            "Google_Maps_URL": gmaps_url(-37.092035, 149.872274),
            "Notes": "Nearest 24h toilet before start is Quarantine Bay (~2 km) or Eden (~4 km). Bushes strictly prohibited.",
        },
        {
            "Waypoint_ID": "WP-02",
            "Distance_km": 0.49,
            "Location_Name": "Nullica River Bridge & Princes Hwy Crossing (0.5-0.7 km)",
            "Category": "Mandatory Road Crossing / Hazard",
            "Official_CP_Number": "",
            "Elevation_m": 8,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "None",
            "Aid_Food_Supplies_Info": "None",
            "Crew_And_Vehicle_Rules": "Runners cross Nullica River bridge on eastern footpath (right of safety barrier), then cross Princes Hwy ONLY under Race Official direction at cones, then run on 2m left verge (DO NOT run on bitumen).",
            "Pacer_Rules": "No pacers allowed.",
            "Gear_Requirements": "Bib + GPS Tracker + Flashing rear light.",
            "Surface_And_Terrain": "Highway bridge footpath -> verge -> forestry firetrail at 0.9 km.",
            "Source_Authority": "Official C2K Course Directions & RWGPS",
            "Latitude": -37.090589,
            "Longitude": 149.868690,
            "Google_Maps_URL": gmaps_url(-37.090589, 149.868690),
            "Notes": "Marshal Crossing #1 (Bega Valley). Penalties apply for ignoring crossing officials.",
        },
        {
            "Waypoint_ID": "WP-03",
            "Distance_km": 3.74,
            "Location_Name": "Aid Station #1 (Brandy Creek Trail / Nullica Rd & Towamba Rd)",
            "Category": "Official Race Aid Station + Road Crossing",
            "Official_CP_Number": "",
            "Elevation_m": 95,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "None",
            "Aid_Food_Supplies_Info": "Minimal race-provided water/drinks & food. ONLY race-supplied aid station before Towamba.",
            "Crew_And_Vehicle_Rules": "Marshal guides left turn onto Towamba Rd. Crews MUST drive straight past Towamba Rd without stopping or handing off anything to runners.",
            "Pacer_Rules": "No pacers allowed.",
            "Gear_Requirements": "Bib + GPS Tracker + Flashing rear light.",
            "Surface_And_Terrain": "Unsealed forestry firetrail exiting onto sealed Towamba Rd.",
            "Source_Authority": "Official C2K Course Directions & RWGPS",
            "Latitude": -37.089905,
            "Longitude": 149.843209,
            "Google_Maps_URL": gmaps_url(-37.089905, 149.843209),
            "Notes": "Marshal Crossing #2. Crew vehicles turn left from Princes Hwy into Towamba Rd and proceed straight to CP1 Towamba.",
        },
        {
            "Waypoint_ID": "WP-04",
            "Distance_km": 24.43,
            "Location_Name": "CP 1 Towamba (Towamba Rd & Pericoe Rd) + School BBQ & Hall Toilets",
            "Category": "Official Checkpoint + Community Aid + Toilet",
            "Official_CP_Number": "CP 1",
            "Elevation_m": 38,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Public Toilets (Towamba Hall 24h ~690m; Sports fields ~1.2 km drive)",
            "Aid_Food_Supplies_Info": "Towamba Public School BBQ breakfast fundraiser (cash preferred) + FIRST CREW RENDEZVOUS.",
            "Crew_And_Vehicle_Rules": "Crews park safely past Towamba Rd / Pericoe Rd junction. Affix yellow/black Runner Ahead & Runner Following signs from Towamba onwards. Max 40 km/h + hazard/amber lights on course; leapfrog ~5 km.",
            "Pacer_Rules": "No general pacers yet.",
            "Gear_Requirements": "Bib + GPS Tracker + Flashing rear light + Crew Hi-Vis vest when out of vehicle.",
            "Surface_And_Terrain": "Sealed rural road (Towamba Rd -> Pericoe St).",
            "Source_Authority": "Official C2K 2026 Guide + National Public Toilet Map",
            "Latitude": -37.081583,
            "Longitude": 149.694362,
            "Google_Maps_URL": gmaps_url(-37.081583, 149.694362),
            "Notes": "Marshal Crossing #3 at 23.9-24.4 km. Support Crew Chief texts C2K WhatsApp group upon clearance.",
        },
        {
            "Waypoint_ID": "WP-05",
            "Distance_km": 36.62,
            "Location_Name": "Wyndham / Towamba St -> Big Jack Mountain Rd Junction",
            "Category": "Mandatory Road Crossing / Navigation Point",
            "Official_CP_Number": "",
            "Elevation_m": 155,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Wyndham Hall 24h public toilet (~7.6 km detour off Big Jack Mtn Rd if crew detours)",
            "Aid_Food_Supplies_Info": "Crew mobile aid only.",
            "Crew_And_Vehicle_Rules": "Marshal Crossing #4 (~36.6-37.0 km) where Towamba St joins Big Jack Mountain Rd. Note: in severe wet weather, race may divert crews via Burragate/Wyndham.",
            "Pacer_Rules": "No pacers allowed.",
            "Gear_Requirements": "Bib + GPS Tracker + Flashing rear light.",
            "Surface_And_Terrain": "Rural road -> unsealed gravel sections ahead on Big Jack Mountain Rd.",
            "Source_Authority": "Official C2K Race Rules & Course Directions",
            "Latitude": -37.006960,
            "Longitude": 149.619560,
            "Google_Maps_URL": gmaps_url(-37.006960, 149.619560),
            "Notes": "Marathon point (42.18 km) passed shortly ahead along Big Jack Mountain Rd at ~169 m elevation.",
        },
        {
            "Waypoint_ID": "WP-06",
            "Distance_km": 42.18,
            "Location_Name": "Marathon Point (42.2 km Marker)",
            "Category": "Course Milestone",
            "Official_CP_Number": "",
            "Elevation_m": 169,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "None",
            "Aid_Food_Supplies_Info": "Crew mobile aid only.",
            "Crew_And_Vehicle_Rules": "Leapfrog ~5 km; keep dust down on gravel when passing runners.",
            "Pacer_Rules": "No pacers allowed.",
            "Gear_Requirements": "Bib + GPS Tracker + Flashing rear light.",
            "Surface_And_Terrain": "Big Jack Mountain Rd (rural road / gravel).",
            "Source_Authority": "Official C2K RWGPS POI",
            "Latitude": -36.974480,
            "Longitude": 149.584152,
            "Google_Maps_URL": gmaps_url(-36.974480, 149.584152),
            "Notes": "Approx 100m past causeway on Big Jack Mountain Rd.",
        },
        {
            "Waypoint_ID": "WP-07",
            "Distance_km": 51.67,
            "Location_Name": "CP 2 Rocky Hall (Public Telephone, Restrooms & Society Stall)",
            "Category": "Official Checkpoint + Community Aid + Toilet",
            "Official_CP_Number": "CP 2",
            "Elevation_m": 209,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Public Toilets (Official Restrooms right at Rocky Hall CP2, 51.68 km)",
            "Aid_Food_Supplies_Info": "Rocky Hall Society coffee & snacks (CASH ONLY) + crew mobile aid.",
            "Crew_And_Vehicle_Rules": "Checkpoint at public telephone on left side of road. Crew Chief checks runner in via C2K WhatsApp group. Prep pacer for Big Jack Mountain 5.6 km ahead.",
            "Pacer_Rules": "Prepare 1 pacer for mandatory Big Jack climb (starts 57.3 km).",
            "Gear_Requirements": "Bib + GPS Tracker + Flashing rear light.",
            "Surface_And_Terrain": "Rural road transitioning to forest valley.",
            "Source_Authority": "Official C2K 2026 Guide & RWGPS POI",
            "Latitude": -36.927179,
            "Longitude": 149.503211,
            "Google_Maps_URL": gmaps_url(-36.927179, 149.503211),
            "Notes": "Great toilet & caffeine stop before climbing out of the coastal valley onto the Monaro tableland.",
        },
        {
            "Waypoint_ID": "WP-08",
            "Distance_km": 57.23,
            "Location_Name": "Base of Big Jack Mountain (Restroom & Mandatory Pacer Climb Start)",
            "Category": "Toilet / Mandatory Pacer Safety Zone",
            "Official_CP_Number": "",
            "Elevation_m": 290,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Public Toilet (Opposite side of road to the park)",
            "Aid_Food_Supplies_Info": "Crew mobile aid before climb (~510m vertical climb over ~7 km).",
            "Crew_And_Vehicle_Rules": "Runner + 1 pacer MUST run on LEFT-hand side of road from Big Jack ascent (57.2-57.3 km) until 64.1 km. Route takes Cow Bail Trail (56.1-63.2 km) -> Woolosen Rd -> Coolangubra Forest Way.",
            "Pacer_Rules": "MANDATORY 1 PACER ONLY from 57.3 km to 64.1 km (keep LEFT!).",
            "Gear_Requirements": "Runner & pacer MUST both wear flashing rear lights.",
            "Surface_And_Terrain": "Steep mountain unsealed gravel climb (Cow Bail Trail / Big Jack Mtn), gaining ~550m elevation to ~850m.",
            "Source_Authority": "Official C2K 2026 Guide (p.11, p.27) & Course Directions",
            "Latitude": -36.897993,
            "Longitude": 149.463533,
            "Google_Maps_URL": gmaps_url(-36.897993, 149.463533),
            "Notes": "Note: RWGPS & updated Course Directions route via Cow Bail Trail (turn left 56.1 km, right 56.4 km) then rejoin towards Coolangubra Forest Way -> Mt Darragh Rd (65.9 km Marshal Crossing #5).",
        },
        {
            "Waypoint_ID": "WP-09",
            "Distance_km": 69.65,
            "Location_Name": "CP 3 Cathcart General Store & Cut-Off #1 + Rest Area Toilets",
            "Category": "Official Checkpoint / Hard Cut-Off + Store + Toilet",
            "Official_CP_Number": "CP 3",
            "Elevation_m": 797,
            "Cutoff_Time_AEDT": "Fri 20 Nov 17:30 AEDT",
            "Cutoff_Elapsed_Hrs": 12.0,
            "Toilet_Status": "Public Toilets (~200m past store at 69.87 km - Cathcart Rest Area, Daylight hours, Water + Shower)",
            "Aid_Food_Supplies_Info": "Cathcart General Store drinks & snacks (CASH ONLY) + crew mobile aid.",
            "Crew_And_Vehicle_Rules": "HARD CUT-OFF #1 at 17:30 Fri (12 hrs; schedule shows 70 km). Runner makes U-turn at store (right-hand side of Eden St). Crew Chief reports pass via C2K WhatsApp.",
            "Pacer_Rules": "No pacers unless sunset (~20:30) occurs later on next leg.",
            "Gear_Requirements": "Prepare night gear (headlamp, spare batteries, light-coloured clothes) for dusk after Cathcart.",
            "Surface_And_Terrain": "Tableland sealed village street -> unsealed Cathcart Rd / Black Lake Rd (71.5 km).",
            "Source_Authority": "Official C2K 2026 Guide & Schedule",
            "Latitude": -36.843248,
            "Longitude": 149.391237,
            "Google_Maps_URL": gmaps_url(-36.843248, 149.391237),
            "Notes": "Minimum cumulative speed required: 5.83 km/h (10:17 min/km).",
        },
        {
            "Waypoint_ID": "WP-10",
            "Distance_km": 77.39,
            "Location_Name": "Black Lake Reserve Public Toilet (Bibbenluke Approach)",
            "Category": "Public Toilet (Corridor)",
            "Official_CP_Number": "",
            "Elevation_m": 760,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Public Toilet (24 hours, 215m off course)",
            "Aid_Food_Supplies_Info": "None",
            "Crew_And_Vehicle_Rules": "Note exact deviation point on Black Lake Rd if runner leaves course for toilet.",
            "Pacer_Rules": "Permitted only once sunset passes (~20:30 Fri).",
            "Gear_Requirements": "Headlamp/torch mandatory during darkness + flashing rear light + light clothing.",
            "Surface_And_Terrain": "Unsealed rural road (Black Lake Rd).",
            "Source_Authority": "National Public Toilet Map (AU Dept of Health)",
            "Latitude": find_gov_toilet("Black Lake")["lat"] if find_gov_toilet("Black Lake") else -36.814,
            "Longitude": find_gov_toilet("Black Lake")["lon"] if find_gov_toilet("Black Lake") else 149.318,
            "Google_Maps_URL": gmaps_url(
                find_gov_toilet("Black Lake")["lat"], find_gov_toilet("Black Lake")["lon"]
            ) if find_gov_toilet("Black Lake") else "",
            "Notes": "3.6 km before entering Monaro Hwy.",
        },
        {
            "Waypoint_ID": "WP-11",
            "Distance_km": 81.04,
            "Location_Name": "Bibbenluke / Monaro Hwy (B23) & Bombala River Bridge (81.0-81.6 km)",
            "Category": "Mandatory Road Crossing / Penalty Zone",
            "Official_CP_Number": "",
            "Elevation_m": 733,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "None",
            "Aid_Food_Supplies_Info": "Crew mobile aid before/after highway.",
            "Crew_And_Vehicle_Rules": "CRITICAL RULE (Penalty enforced!): Runners MUST stay on extreme RIGHT-hand side of Monaro Hwy facing oncoming traffic to cross Bombala River bridge. At 81.63 km, cross Monaro Hwy ONLY at cones under Marshal direction into Bukalong Siding Rd.",
            "Pacer_Rules": "Permitted if after sunset (~20:30).",
            "Gear_Requirements": "Headlamp + flashing rear light + crew hi-vis vest.",
            "Surface_And_Terrain": "Major sealed highway (B23) -> unsealed Bukalong Siding Rd -> 20 km of cattle grids starting 85.8 km & disused rail line 86.5 km.",
            "Source_Authority": "Official C2K Race Rules & RWGPS POI",
            "Latitude": -36.816199,
            "Longitude": 149.283011,
            "Google_Maps_URL": gmaps_url(-36.816199, 149.283011),
            "Notes": "Marshal Crossing #6 at 81.6 km. Officials watch Bibbenluke closely and apply time penalties for running on the left.",
        },
        {
            "Waypoint_ID": "WP-12",
            "Distance_km": 97.61,
            "Location_Name": "Gunningrach Rd Right Fork & Big Dead Tree Landmark (101.9 km)",
            "Category": "Navigation Hazard / Landmark",
            "Official_CP_Number": "",
            "Elevation_m": 761,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "None",
            "Aid_Food_Supplies_Info": "Crew mobile aid only.",
            "Crew_And_Vehicle_Rules": "Important night navigation check: crews should help confirm runner takes the RIGHT fork after crossing Cambalong Creek bridge at 97.6 km. Watch for numerous cattle grids.",
            "Pacer_Rules": "Permitted if after sunset.",
            "Gear_Requirements": "Headlamp + flashing rear light.",
            "Surface_And_Terrain": "Unsealed country road / cattle grids, climbing toward 925m.",
            "Source_Authority": "Official C2K Course Description & RWGPS",
            "Latitude": -36.747355,
            "Longitude": 149.151747,
            "Google_Maps_URL": gmaps_url(-36.747355, 149.151747),
            "Notes": "Big Dead Tree landmark sits on the right on uphill at 101.93 km.",
        },
        {
            "Waypoint_ID": "WP-13",
            "Distance_km": 106.60,
            "Location_Name": "CP 4 Gunningrach Rd & Snowy River Way (Cut-Off #2)",
            "Category": "Official Checkpoint / Hard Cut-Off + Pacer Gate",
            "Official_CP_Number": "CP 4",
            "Elevation_m": 925,
            "Cutoff_Time_AEDT": "Fri 20 Nov 23:30 AEDT",
            "Cutoff_Elapsed_Hrs": 18.0,
            "Toilet_Status": "None",
            "Aid_Food_Supplies_Info": "NO shops/toilets; Crew mobile aid only.",
            "Crew_And_Vehicle_Rules": "HARD CUT-OFF #2 at 23:30 Fri (18 hrs; schedule shows 106 km). Landmark: disused livestock ramp. Marshal Crossing #7. Poor/no mobile signal at junction - send WhatsApp update once signal resumes on Snowy River Way.",
            "Pacer_Rules": "General Pacing Gate OPENS here (106.7 km) for remainder of race (1 pacer at a time until Charlotte Pass).",
            "Gear_Requirements": "AS/NZS Reflective Vest becomes MANDATORY for runners & pacers from CP4 to Finish (+ headlamp + flashing rear light).",
            "Surface_And_Terrain": "Unsealed Gunningrach Rd -> sealed Snowy River Way (turn left).",
            "Source_Authority": "Official C2K 2026 Guide & Schedule",
            "Latitude": -36.690866,
            "Longitude": 149.159959,
            "Google_Maps_URL": gmaps_url(-36.690866, 149.159959),
            "Notes": "Minimum cumulative speed required: 5.93 km/h (10:07 min/km). Long 41.4 km night leg ahead to Dalgety.",
        },
        {
            "Waypoint_ID": "WP-14",
            "Distance_km": 147.98,
            "Location_Name": "CP 5 Dalgety Memorial Hall, Rear Toilets & Dalgety Bridge Cut-Off #3",
            "Category": "Official Checkpoint / Hard Cut-Off + Community Soup + Toilet",
            "Official_CP_Number": "CP 5",
            "Elevation_m": 756,
            "Cutoff_Time_AEDT": "Sat 21 Nov 06:30 AEDT (Dalgety Bridge West side 148.25 km)",
            "Cutoff_Elapsed_Hrs": 25.0,
            "Toilet_Status": "Hall Toilets = RUNNERS ONLY; Rear building 50-100m behind Hall (Brierly St) = Support Crew",
            "Aid_Food_Supplies_Info": "Dalgety Hall hot soup & refreshments for RUNNERS & SUPPORT CREW ONLY (not spectators/family/friends).",
            "Crew_And_Vehicle_Rules": "HARD CUT-OFF #3 at 06:30 Sat (25 hrs) across Dalgety Bridge (148.25 km). Respect Dalgety village residents at dawn (no loud voices/headlights into homes).",
            "Pacer_Rules": "Permitted (1 pacer; must wear reflective vest + flashing rear light).",
            "Gear_Requirements": "Reflective vest + flashing rear light + headlamp while dark.",
            "Surface_And_Terrain": "Sealed rural highway (Snowy River Way through Dalgety across Snowy River Bridge).",
            "Source_Authority": "Official C2K 2026 Guide & Schedule",
            "Latitude": -36.504090,
            "Longitude": 148.834251,
            "Google_Maps_URL": gmaps_url(-36.504090, 148.834251),
            "Notes": "Minimum cumulative speed required: 5.93 km/h (10:07 min/km). Public telephone landmark opposite Dalgety Pub.",
        },
        {
            "Waypoint_ID": "WP-15",
            "Distance_km": 162.00,
            "Location_Name": "Beloka Hill Ascent (162.0 - 165.0 km)",
            "Category": "Mandatory Pacer Safety Zone + No-Parking Climb",
            "Official_CP_Number": "",
            "Elevation_m": 880,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "None",
            "Aid_Food_Supplies_Info": "Crew must support BEFORE 162 km or AFTER crest (~165+ km).",
            "Crew_And_Vehicle_Rules": "NO STOPPING / NO PARKING by support vehicles on the ascent of Beloka Range on Snowy River Way. Runner & pacer MUST keep to LEFT-hand side of road (162-165 km).",
            "Pacer_Rules": "MANDATORY 1 PACER ONLY from 162.0 km to 165.0 km (keep LEFT!).",
            "Gear_Requirements": "Reflective vest + flashing rear light.",
            "Surface_And_Terrain": "Very steep sealed climb (Beloka Range on Snowy River Way) up towards ~1,100 m.",
            "Source_Authority": "Official C2K 2026 Guide (p.11) & Race Rules",
            "Latitude": -36.495000,
            "Longitude": 148.720000,
            "Google_Maps_URL": "",
            "Notes": "Exact Beloka climb starts right after crossing Guises Creek (~161.9 km); steep exposed morning climb.",
        },
        {
            "Waypoint_ID": "WP-16",
            "Distance_km": 181.70,
            "Location_Name": "Jindabyne Roundabout Crossing & Claypits Lake Path Toilets (181.7-181.9 km)",
            "Category": "Mandatory Road Crossing + 24h Toilet + Town Resupply",
            "Official_CP_Number": "",
            "Elevation_m": 914,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Public Toilets (Claypits Foreshore Park 24h + Water, 11m off course; Kalkite St 24h; BP 6am-10pm; Town Centre CLOSED)",
            "Aid_Food_Supplies_Info": "Jindabyne town supermarkets, cafes, pharmacies & fuel stations (~7am-7pm/8pm). Best late-race resupply.",
            "Crew_And_Vehicle_Rules": "Marshal Crossing #8 at Barry Way / Kosciuszko Rd roundabout (181.6-181.7 km). Runners turn left onto Lake Jindabyne foreshore path. Crews turn left towards Kosciuszko Rd (or right briefly for town supplies).",
            "Pacer_Rules": "Permitted (1 pacer).",
            "Gear_Requirements": "Reflective vest + flashing rear light; load Summit Path alpine gear into vehicle here if not already onboard.",
            "Surface_And_Terrain": "Paved lake foreshore bike path -> Yabby Track -> Hatchery Bay Track through Caravan Park.",
            "Source_Authority": "Official C2K 2026 Guide (p.23, p.27) + National Public Toilet Map",
            "Latitude": -36.413939,
            "Longitude": 148.609790,
            "Google_Maps_URL": gmaps_url(-36.413939, 148.609790),
            "Notes": "Check shop closing times (~7pm) if slower schedule puts you in Jindabyne after dark - actually Cut-off #4 is Sat 14:00 so all active runners clear before afternoon close.",
        },
        {
            "Waypoint_ID": "WP-17",
            "Distance_km": 183.92,
            "Location_Name": "CP 6 Jindabyne Caravan & Holiday Discovery Park (Cut-Off #4)",
            "Category": "Official Checkpoint / Hard Cut-Off",
            "Official_CP_Number": "CP 6",
            "Elevation_m": 924,
            "Cutoff_Time_AEDT": "Sat 21 Nov 14:00 AEDT",
            "Cutoff_Elapsed_Hrs": 32.5,
            "Toilet_Status": "Shell Jindabyne adjacent (6am-4pm); Caravan Park reception",
            "Aid_Food_Supplies_Info": "Shell service station across road (6am-4pm) + crew mobile aid.",
            "Crew_And_Vehicle_Rules": "HARD CUT-OFF #4 at 14:00 Sat (32.5 hrs; updated from 14:30 in older years!). Meet runner exiting bike path onto Kosciuszko Rd. Crew Chief reports pass via C2K WhatsApp.",
            "Pacer_Rules": "Permitted (1 pacer).",
            "Gear_Requirements": "Reflective vest + flashing rear light; ensure sun protection & warm alpine layers ready in crew vehicle.",
            "Surface_And_Terrain": "Gravel/paved park path rejoining sealed Kosciuszko Rd.",
            "Source_Authority": "Official C2K 2026 Guide & Schedule",
            "Latitude": -36.409587,
            "Longitude": 148.596930,
            "Google_Maps_URL": gmaps_url(-36.409587, 148.596930),
            "Notes": "Minimum cumulative speed required: 5.66 km/h (10:36 min/km). Long 38 km climb to Charlotte Pass begins after Jindabyne.",
        },
        {
            "Waypoint_ID": "WP-18",
            "Distance_km": 189.75,
            "Location_Name": "Little Thredbo River Rest Area (Kosciuszko NP)",
            "Category": "Public Toilet (National Park)",
            "Official_CP_Number": "",
            "Elevation_m": 1030,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Public Toilet (24 hours, 69m off course)",
            "Aid_Food_Supplies_Info": "Crew mobile aid only.",
            "Crew_And_Vehicle_Rules": "National Park rules: Leave No Trace, secure food from wildlife.",
            "Pacer_Rules": "Permitted (1 pacer).",
            "Gear_Requirements": "Reflective vest + flashing rear light.",
            "Surface_And_Terrain": "Sealed Kosciuszko Rd climbing steadily.",
            "Source_Authority": "National Public Toilet Map (AU Dept of Health)",
            "Latitude": find_gov_toilet("Little Thredbo")["lat"] if find_gov_toilet("Little Thredbo") else -36.364,
            "Longitude": find_gov_toilet("Little Thredbo")["lon"] if find_gov_toilet("Little Thredbo") else 148.580,
            "Google_Maps_URL": gmaps_url(
                find_gov_toilet("Little Thredbo")["lat"], find_gov_toilet("Little Thredbo")["lon"]
            ) if find_gov_toilet("Little Thredbo") else "",
            "Notes": "Crosses Thredbo River vicinity before climbing Sawpit Creek.",
        },
        {
            "Waypoint_ID": "WP-19",
            "Distance_km": 195.47,
            "Location_Name": "Sawpit Creek Rest Area (Kosciuszko NP)",
            "Category": "Public Toilet (National Park)",
            "Official_CP_Number": "",
            "Elevation_m": 1204,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "Public Toilet (24 hours, 50m off course)",
            "Aid_Food_Supplies_Info": "Crew mobile aid only.",
            "Crew_And_Vehicle_Rules": "Last confirmed 24h public toilet before Charlotte Pass (222.1 km).",
            "Pacer_Rules": "Permitted (1 pacer).",
            "Gear_Requirements": "Reflective vest + flashing rear light + headlamp as second night approaches.",
            "Surface_And_Terrain": "Sealed mountain highway climbing continuously past Guthega turnoff (203.6 km) & Dainers Gap.",
            "Source_Authority": "National Public Toilet Map (AU Dept of Health)",
            "Latitude": find_gov_toilet("Sawpit")["lat"] if find_gov_toilet("Sawpit") else -36.345,
            "Longitude": find_gov_toilet("Sawpit")["lon"] if find_gov_toilet("Sawpit") else 148.567,
            "Google_Maps_URL": gmaps_url(
                find_gov_toilet("Sawpit")["lat"], find_gov_toilet("Sawpit")["lon"]
            ) if find_gov_toilet("Sawpit") else "",
            "Notes": "Key mountain climb milestone along Kosciuszko Rd.",
        },
        {
            "Waypoint_ID": "WP-20",
            "Distance_km": 213.11,
            "Location_Name": "CP 7 Perisher Valley (Bus Shelter in front of Ski-Tube Station)",
            "Category": "Official Checkpoint",
            "Official_CP_Number": "CP 7",
            "Elevation_m": 1722,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "No 24h public toilet confirmed on National Toilet Map",
            "Aid_Food_Supplies_Info": "Crew mobile aid only (no late-night open venues).",
            "Crew_And_Vehicle_Rules": "Check in at bus shelter on right-hand side of road in front of Ski-Tube Station. Crew Chief texts C2K WhatsApp group. Only 9 km to Charlotte Pass.",
            "Pacer_Rules": "Permitted (1 pacer).",
            "Gear_Requirements": "Reflective vest + flashing rear light + headlamp + warm layers (1,722 m elevation).",
            "Surface_And_Terrain": "Alpine sealed road through Perisher Creek / Burramys Rd back onto Kosciuszko Rd.",
            "Source_Authority": "Official C2K 2026 Guide & RWGPS POI",
            "Latitude": -36.405495,
            "Longitude": 148.412360,
            "Google_Maps_URL": gmaps_url(-36.405495, 148.412360),
            "Notes": "Last checkpoint before the Summit Path gear inspection at Charlotte Pass.",
        },
        {
            "Waypoint_ID": "WP-21",
            "Distance_km": 222.05,
            "Location_Name": "CP 8 Charlotte Pass (Turnaround Loop Car Park & Cut-Off #5)",
            "Category": "Official Checkpoint / Hard Cut-Off + Gear Inspection + Toilet",
            "Official_CP_Number": "CP 8",
            "Elevation_m": 1838,
            "Cutoff_Time_AEDT": "Sat 21 Nov 23:00 AEDT",
            "Cutoff_Elapsed_Hrs": 41.5,
            "Toilet_Status": "Public Toilet (Charlotte Pass Lookout 24h, 22m off course)",
            "Aid_Food_Supplies_Info": "Crew mobile aid staging before 18.4 km round-trip Summit Path.",
            "Crew_And_Vehicle_Rules": "HARD CUT-OFF #5 at 23:00 Sat (41.5 hrs). Officials check ALL Mandatory Summit Gear for runner & pacer(s), assess runner fitness, enforce any time penalties, and authorise entry onto Summit Path. May terminate race at Charlotte Pass (Inclement Weather Finish) if unsafe.",
            "Pacer_Rules": "MANDATORY pacer(s) from here to Summit and back (multiple support crew permitted!).",
            "Gear_Requirements": "ALL 14 Summit Mandatory items: Beanie/warm headwear, Gloves, Head torch + spare batteries, Rain jacket, Waterproof pants, Thermal pants, Long-sleeve thermal top, Reflective vest, Charged mobile phone, Space blanket, Food & water, Sunscreen, Trekking poles (mandatory runner / optional pacer), Sunglasses.",
            "Surface_And_Terrain": "End of public road -> alpine Summit Walk track (paved/gravel/snow patches).",
            "Source_Authority": "Official C2K 2026 Guide (p.15, p.20, p.27) & Schedule",
            "Latitude": -36.431598,
            "Longitude": 148.328858,
            "Google_Maps_URL": gmaps_url(-36.431598, 148.328858),
            "Notes": "Minimum cumulative speed required: 5.35 km/h (11:13 min/km). Secure all crew food inside vehicles against ravens/currawongs.",
        },
        {
            "Waypoint_ID": "WP-22",
            "Distance_km": 228.06,
            "Location_Name": "Seamans Hut (Summit Path Outbound & 234.6 km Return)",
            "Category": "Alpine Emergency Shelter + 24h Toilet",
            "Official_CP_Number": "",
            "Elevation_m": 2020,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "National Park 24h Toilet (adjacent to Seamans Hut)",
            "Aid_Food_Supplies_Info": "Emergency shelter only (no supplied food/water).",
            "Crew_And_Vehicle_Rules": "No vehicles. Carry out all wrappers & waste.",
            "Pacer_Rules": "Mandatory pacer(s) must stay with runner.",
            "Gear_Requirements": "Full Mandatory Summit Gear.",
            "Surface_And_Terrain": "High-altitude alpine Summit Walk (6 km from Charlotte Pass).",
            "Source_Authority": "Official C2K 2026 Guide (p.15, p.27) & RWGPS POI",
            "Latitude": -36.450278,
            "Longitude": 148.282633,
            "Google_Maps_URL": gmaps_url(-36.450278, 148.282633),
            "Notes": "Passed twice: ~228.06 km outbound and ~234.58 km return.",
        },
        {
            "Waypoint_ID": "WP-23",
            "Distance_km": 229.64,
            "Location_Name": "Rawson Pass (Summit Path Outbound & 232.9 km Return)",
            "Category": "Alpine Emergency Shelter + 24h Toilet",
            "Official_CP_Number": "",
            "Elevation_m": 2122,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "National Park 24h Toilet (Australia's highest public toilets, 16m off course)",
            "Aid_Food_Supplies_Info": "Emergency shelter only.",
            "Crew_And_Vehicle_Rules": "No vehicles. 1.6 km below Mt Kosciuszko summit. Never leave waste or toilet paper beside Summit Path.",
            "Pacer_Rules": "Mandatory pacer(s) must stay with runner.",
            "Gear_Requirements": "Full Mandatory Summit Gear; turn right onto Summit Walk loop.",
            "Surface_And_Terrain": "Alpine stone/gravel/metal raised walkway approaching summit.",
            "Source_Authority": "Official C2K 2026 Guide (p.15, p.27) + National Public Toilet Map",
            "Latitude": -36.457690,
            "Longitude": 148.268770,
            "Google_Maps_URL": gmaps_url(-36.457690, 148.268770),
            "Notes": "Passed twice: ~229.64 km outbound and ~232.90 km return.",
        },
        {
            "Waypoint_ID": "WP-24",
            "Distance_km": 231.30,
            "Location_Name": "Mount Kosciuszko Summit (2,228 m Turnaround)",
            "Category": "Summit / Turnaround",
            "Official_CP_Number": "Summit",
            "Elevation_m": 2228,
            "Cutoff_Time_AEDT": "",
            "Cutoff_Elapsed_Hrs": "",
            "Toilet_Status": "None (nearest Rawson Pass 1.6 km below)",
            "Aid_Food_Supplies_Info": "Self-carried summit supplies only.",
            "Crew_And_Vehicle_Rules": "CRITICAL NPWS RULE: Do NOT climb or stand on the summit cairn (Strzelecki monument/trig cairn) - time penalty or disqualification applies! Turn around and descend back via Summit Walk.",
            "Pacer_Rules": "Mandatory pacer(s) with runner.",
            "Gear_Requirements": "Full Mandatory Summit Gear + GPS Tracker active.",
            "Surface_And_Terrain": "Highest point in mainland Australia (2,228 m); exposed alpine ridge.",
            "Source_Authority": "Official C2K 2026 Guide & TrackMeLive",
            "Latitude": -36.455849,
            "Longitude": 148.263550,
            "Google_Maps_URL": gmaps_url(-36.455849, 148.263550),
            "Notes": "9.35 km remaining back down to Charlotte Pass Finish Line.",
        },
        {
            "Waypoint_ID": "WP-25",
            "Distance_km": 240.65,
            "Location_Name": "Charlotte Pass Finish Line (End of Summit Walk)",
            "Category": "Finish / Final Cut-Off",
            "Official_CP_Number": "Finish",
            "Elevation_m": 1839,
            "Cutoff_Time_AEDT": "Sun 22 Nov 03:30 AEDT",
            "Cutoff_Elapsed_Hrs": 46.0,
            "Toilet_Status": "Public Toilet (Charlotte Pass Lookout 24h)",
            "Aid_Food_Supplies_Info": "Crew support at finish. Post-race breakfast 07:00-09:00 & Presentation 09:00-11:00 at Adventist Alpine Village, Jindabyne ($21/head pre-paid).",
            "Crew_And_Vehicle_Rules": "FINAL CUT-OFF at 03:30 Sun (46 hrs). Return GPS tracker immediately (mandatory or DQ!). Return both yellow vehicle signs. Ensure driver is rested before driving down to Jindabyne.",
            "Pacer_Rules": "Mandatory pacer(s) finish with runner.",
            "Gear_Requirements": "GPS Tracker returned to Race Officials.",
            "Surface_And_Terrain": "Finish arch at Charlotte Pass road turnaround.",
            "Source_Authority": "Official C2K 2026 Guide & Schedule",
            "Latitude": -36.431729,
            "Longitude": 148.328413,
            "Google_Maps_URL": gmaps_url(-36.431729, 148.328413),
            "Notes": "First-time finishers earn iconic Akubra hat; repeat finishers earn C2K hat pin; all receive 2026 finisher shirt.",
        },
    ]

    # Populate Leg_Split_km for waypoints
    prev_km = 0.0
    for w in waypoints:
        w["Leg_Split_km"] = round(w["Distance_km"] - prev_km, 2)
        prev_km = w["Distance_km"]

    # Fill Beloka Hill exact coord from track point near 162.5 km
    beloka_tp = min(pts, key=lambda t: abs(t["d"] / 1000.0 - 162.5))
    waypoints[14]["Latitude"] = round(beloka_tp["y"], 6)
    waypoints[14]["Longitude"] = round(beloka_tp["x"], 6)
    waypoints[14]["Elevation_m"] = round(beloka_tp.get("e", 880), 0)
    waypoints[14]["Google_Maps_URL"] = gmaps_url(beloka_tp["y"], beloka_tp["x"])

    # ------------------------------------------------------------------
    # TABLE 4: COURSE LEGS & TURN-BY-TURN DIRECTIONS (All 61 official RWGPS cues + leg metadata)
    # ------------------------------------------------------------------
    def leg_context(km):
        if km < 24.43:
            return ("Leg 1: Boydtown Beach -> CP1 Towamba", "Beach/Hwy Verge/Firetrail/Sealed Rural Rd", "NO crew access until 24.5 km; Aid Station at 3.7 km")
        if km < 51.67:
            return ("Leg 2: CP1 Towamba -> CP2 Rocky Hall", "Sealed & Unsealed Rural Rd (Big Jack Mtn Rd)", "First crew zone; Marathon mark at 42.2 km")
        if km < 69.65:
            return ("Leg 3: CP2 Rocky Hall -> CP3 Cathcart", "Steep Unsealed Forest Climb (Cow Bail / Big Jack)", "Mandatory 1 pacer 57.3-64.1 km (keep LEFT); Cut-Off #1 at 69.7 km (Fri 17:30)")
        if km < 106.60:
            return ("Leg 4: CP3 Cathcart -> CP4 Gunningrach Rd", "Unsealed Rural Rd + B23 Crossing + 20km Cattle Grids", "Run RIGHT on Monaro Hwy (Bibbenluke); Cut-Off #2 at 106.6 km (Fri 23:30)")
        if km < 147.98:
            return ("Leg 5: CP4 Gunningrach Rd -> CP5 Dalgety", "Sealed Rural Highway (The Snowy River Way)", "Overnight leg; Reflective vest MANDATORY; Pacers open; Cut-Off #3 Sat 06:30")
        if km < 183.92:
            return ("Leg 6: CP5 Dalgety -> CP6 Jindabyne", "Sealed Mountain Rd (Beloka Hill) + Foreshore Path", "Mandatory 1 pacer & keep LEFT on Beloka Hill (162-165 km); No crew parking on Beloka; Cut-Off #4 Sat 14:00")
        if km < 213.11:
            return ("Leg 7: CP6 Jindabyne -> CP7 Perisher Valley", "Sealed Alpine Highway (Kosciuszko Rd)", "Continuous 800m climb via Sawpit Creek into Kosciuszko NP")
        if km < 222.05:
            return ("Leg 8: CP7 Perisher -> CP8 Charlotte Pass", "Sealed Alpine Road (Kosciuszko Rd)", "Cut-Off #5 Sat 23:00 + Mandatory Summit Gear check")
        if km < 231.30:
            return ("Leg 9a: CP8 Charlotte Pass -> Mt Kosciuszko Summit", "Alpine Summit Walk (Paved/Gravel/Snow)", "Mandatory Pacer(s) & 14-item Summit Gear; shelters/toilets at Seamans Hut & Rawson Pass")
        return ("Leg 9b: Mt Kosciuszko Summit -> Charlotte Pass Finish", "Alpine Summit Walk Descent", "Do NOT stand on summit cairn; Final Cut-Off Sun 03:30 (46 hrs)")

    # Special comments from Course-Directions-1.pdf & RWGPS
    cue_notes_map = {
        0.02: "Start Boydtown Beach immediately south of Nullica River mouth (05:30 AEDT).",
        0.32: "Keep to RIGHT of safety barrier on eastern side to cross Nullica River bridge on footpath; cross Hwy AFTER bridge with marshal/cones (~0.5-0.7 km); then 2m left verge (DO NOT run on bitumen).",
        0.87: "Turn left onto forestry firetrail 50m after 'KEEP LEFT UNLESS OVERTAKING' sign.",
        3.67: "Official Marshal here + Aid Station #1 at Nullica Rd junction (minimal food/drink).",
        13.95: "At 16.9 km keep right to stay on Towamba Rd (avoid The Snake Track left); CP1 Towamba at 24.4 km.",
        36.62: "Marshal Crossing where Towamba St joins Big Jack Mountain Rd (~37.0 km).",
        63.94: "Note: Updated route uses Cow Bail Trail (56.1-63.2 km) -> Woolosen Rd -> Coolangubra Forest Way before Mt Darragh Rd & Cathcart; check race briefing for active 2026 alignment.",
        65.85: "Marshal Crossing where Big Jack Rd / Coolangubra joins Mt Darragh Rd.",
        70.39: "Follow Cathcart General Store U-turn (69.65 km) & Rest Area toilets (69.87 km).",
        81.04: "CRITICAL: Run on RIGHT-hand side of Monaro Hwy facing traffic across Bombala River (penalties enforced).",
        81.63: "Marshal Crossing with cones across Monaro Hwy into Bukalong Siding Rd; 20 km of cattle grids ahead from 85.8 km.",
        106.60: "CP4 & Cut-Off #2 (Fri 23:30, 18 hrs) at disused livestock ramp; Marshal Crossing; Reflective vest mandatory from here.",
        147.98: "CP5 Dalgety Memorial Hall (148.0 km); Cut-Off #3 beyond Dalgety Bridge West side (148.25 km, Sat 06:30).",
        181.62: "Marshal Crossing at roundabout (181.7 km) onto Lake Jindabyne foreshore path; Claypits 24h toilet at 181.9 km.",
        185.06: "Exit Caravan Park bike path at CP6 (183.9 km, Cut-Off #4 Sat 14:00) and join Kosciuszko Rd near service station.",
        212.94: "Loops briefly into Perisher Valley Ski-Tube Station bus shelter (CP7 at 213.11 km) then exits onto Kosciuszko Rd.",
        222.11: "CP8 Charlotte Pass & Cut-Off #5 (Sat 23:00, 41.5 hrs); slight right onto Summit Walk after mandatory gear check.",
        229.72: "Just past Rawson Pass 24h toilets & shelter (229.6 km); next stay left avoiding Main Range track at 230.4 km; summit turnaround at 231.3 km.",
        233.03: "Return past Rawson Pass (232.9 km) and Seamans Hut (234.6 km).",
        240.64: "FINISH LINE at Charlotte Pass end of Summit Walk (Sun 03:30 Final Cut-Off, 46 hrs).",
    }

    legs_rows = []
    for idx, c in enumerate(cues, 1):
        km = round(c.get("d", 0) / 1000.0, 2)
        tp_idx = c.get("i")
        elev = round(pts[tp_idx]["e"], 1) if isinstance(tp_idx, int) and 0 <= tp_idx < len(pts) and "e" in pts[tp_idx] else ""
        leg_name, surface, leg_rule = leg_context(km)
        # Match closest special note within 0.08 km
        spec_note = ""
        for k_ref, txt in cue_notes_map.items():
            if abs(km - k_ref) <= 0.08:
                spec_note = txt
                break
        legs_rows.append({
            "Cue_Seq": idx,
            "Distance_km": km,
            "Leg_Name": leg_name,
            "Turn_Type": c.get("t", ""),
            "Instruction": c.get("n", ""),
            "Elevation_m": elev,
            "Surface_Type": surface,
            "Leg_Rules_And_Cutoff": leg_rule,
            "Official_Course_Notes": spec_note,
            "Latitude": round(c.get("y", 0), 6),
            "Longitude": round(c.get("x", 0), 6),
            "Google_Maps_URL": gmaps_url(c.get("y"), c.get("x")),
        })

    # ------------------------------------------------------------------
    # TABLE 5: RULES, MANDATORY GEAR, SUPPORT CREW & PACERS
    # ------------------------------------------------------------------
    rules_rows = [
        # Mandatory Runner Gear (24h / Course)
        ("Runner Gear (All Race)", "Race Bib", "Mandatory", "Must remain clearly visible throughout entire race. Elastic race number belt recommended for easy clothing changes.", "2026 Runners Guide p.10"),
        ("Runner Gear (All Race)", "Official GPS Tracker", "Mandatory", "Supplied at Thu check-in. Must be worn & operational at all times (placings depend on it). MUST be returned after race or runner is disqualified. If malfunctioning, text Race Control on WhatsApp immediately + record GPS/photos as proof.", "2026 Runners Guide p.10, p.20"),
        ("Runner Gear (All Race)", "Flashing Rear Light (24/7)", "Mandatory", "Rear bike-style light attached to race belt at rear, set to FLASHING mode DAY AND NIGHT (keep spare batteries/charging ready).", "2026 Runners Guide p.10"),
        ("Runner Gear (CP4 to Finish)", "AS/NZS Compliant Reflective Vest", "Mandatory from CP4 (106.7 km)", "Must be worn by runner (and pacer) from Checkpoint 4 (Gunningrach Rd / Snowy River Way) continuously to the Finish.", "2026 Runners Guide p.10"),
        ("Runner Gear (Night)", "Headlamp / Torch & Light Clothing", "Mandatory during darkness", "Headlamp/torch mandatory during night hours; light-coloured clothing strongly encouraged.", "2026 Runners Guide p.10 / Rules"),
        # Summit Path Mandatory Gear (14 items for Runner + Pacer(s))
        ("Summit Path Gear (222-240 km)", "Beanie / Balaclava / Buff (Warm Headwear)", "Mandatory (Runner & Pacer)", "Checked at CP8 Charlotte Pass before entering Summit Path (must be owned/ready before race start).", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Gloves", "Mandatory (Runner & Pacer)", "Checked at CP8 Charlotte Pass.", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Head Torch + Fully Charged Spare Batteries", "Mandatory (Runner & Pacer)", "Checked at CP8 Charlotte Pass.", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Rain Jacket & Waterproof Pants", "Mandatory (Runner & Pacer)", "Seam-sealed weather protection checked at CP8 Charlotte Pass.", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Thermal Pants & Long-Sleeve Thermal Top", "Mandatory (Runner & Pacer)", "Checked at CP8 Charlotte Pass.", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Reflective Vest", "Mandatory (Runner & Pacer)", "Checked at CP8 Charlotte Pass.", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Charged Mobile Phone & Space Blanket", "Mandatory (Runner & Pacer)", "Checked at CP8 Charlotte Pass.", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Sufficient Food & Water", "Mandatory (Runner & Pacer)", "Checked at CP8 Charlotte Pass (carry enough for 18.4 km alpine out-and-back; no shops/aid).", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Sunscreen & Sunglasses", "Mandatory (Runner & Pacer)", "2026 Guide infographic adds Sunglasses alongside Sunscreen (sufficient quantity for party).", "2026 Runners Guide p.15"),
        ("Summit Path Gear (222-240 km)", "Trekking Poles (for snow traverse)", "Mandatory Runner / Optional Pacer", "Mandatory for runner; highly recommended/optional for pacer(s) & crew summiting. Crew may carry Summit gear for runner.", "2026 Runners Guide p.15 / Rules 5.2"),
        # Pacer Rules
        ("Pacer Rules", "Mandatory Pacer Section 1: Big Jack Mountain", "Mandatory (57.3 - 64.1 km)", "Must be paced by ONLY 1 support crew member on the ascent of Big Jack Mountain (57.3-64.1 km). Keep to LEFT-hand side of road.", "2026 Runners Guide p.11"),
        ("Pacer Rules", "Mandatory Pacer Section 2: Beloka Hill", "Mandatory (162.0 - 165.0 km)", "Must be paced by ONLY 1 support crew member on the ascent of Beloka Hill (162-165 km). Keep to LEFT-hand side of road.", "2026 Runners Guide p.11"),
        ("Pacer Rules", "Mandatory Pacer Section 3: Summit Path", "Mandatory (222.0 - 240.0 km)", "Must be accompanied by at least 1 support crew pacer from Charlotte Pass to Mt Kosciuszko Summit and return. EXCEPTION: MULTIPLE support crew may accompany here.", "2026 Runners Guide p.11 / Rules 4.1.6"),
        ("Pacer Rules", "General Pacing Window & Gear", "After CP4 (106.7 km) or Sunset (~20:30)", "1 pacer at a time permitted after CP4 (or after sunset if before CP4). Pacers may carry gear/food/drink ('mule') but CANNOT physically assist, push, pull, carry, or tow runner. Pacers must wear flashing rear light 24/7, reflective vest (post-CP4), and headlamp at night.", "2026 Runners Guide p.11"),
        # Support Crew & Vehicle Rules
        ("Support Crew Rules", "Minimum Crew Composition & WhatsApp Chief", "Mandatory (Min 2 crew)", "Dedicated crew of at least 2 people (at least 1 able to pace). Exactly ONE Support Crew Chief mobile number added to C2K WhatsApp group. Runners are strictly accountable for crew & pacer breaches. Pets prohibited; under-16s require prior RD approval.", "2026 Runners Guide p.11, p.20, p.27"),
        ("Support Crew Rules", "Crew Hi-Vis Vest (Outside Vehicle)", "Mandatory 24/7", "Every support crew member must wear an AS-compliant hi-vis reflective vest whenever outside the support vehicle, day or night, plus headlamp at night.", "2026 Runners Guide p.19 / Rules 3.1.2"),
        ("Support Crew Rules", "No Crew Support Zone: Start to Towamba", "Strict Prohibition (0 - 24.5 km)", "Support crews MUST NOT stop, slow down to talk, or support runners anywhere between Boydtown Beach (0 km) and CP1 Towamba (24.5 km). Drive directly to Towamba and park past Pericoe Rd junction.", "Race Rules 3.1.10-3.1.12"),
        ("Support Vehicle Rules", "1 Active Vehicle / Max Length 5.5m / No Campervans", "Mandatory Inspection Thu/Fri", "Max 1 registered support vehicle active at a time (shift vehicles only swap at mandatory CPs). 4WD strongly recommended; sedan/wagon/ute/HiAce van OK up to MAX 5.5 metres length. Campervans/motorhomes & vehicles >5.5m PROHIBITED. No bikes/scooters/e-scooters.", "2026 Runners Guide p.21-22 / Rules 3.2"),
        ("Support Vehicle Rules", "Mandatory Signs, Sticker & Warning Lights", "Mandatory Inspection", "Display A4 runner number sticker on rear right/driver-side window. Affix yellow/black 'Runners Ahead' (rear) & 'Runners Following' (front) signs from Towamba onwards (return after race). Hazard lights OR amber roof beacon ON at all times on course.", "2026 Runners Guide p.21-22"),
        ("Support Vehicle Rules", "40 km/h Speed Limit & Leapfrog Protocol", "Max 40 km/h", "Maximum 40 km/h while actively supporting on course. Leapfrog ~5 km ahead, park completely off road (never under trees, never blocking driveways/gates, NEVER on Beloka climb). Never shadow/crawl behind runner or hand off from a moving car.", "2026 Runners Guide p.19, p.21"),
        # Road, Route, Toilets & Emergency Rules
        ("Road & Course Rules", "Road Positioning & Critical Exceptions", "Penalty / DQ Enforced", "Run on extreme RIGHT-hand side facing oncoming traffic at all times EXCEPT: (1) Big Jack Mountain ascent (keep LEFT, 57.3-64.1 km), (2) Beloka Hill ascent (keep LEFT, 162-165 km). CRITICAL REMINDER: Bibbenluke / Monaro Hwy MUST run RIGHT (officials impose time penalties here).", "2026 Runners Guide p.9 / Rules 2.1.2-2.1.6"),
        ("Road & Course Rules", "8 Official Marshal Road Crossings & Deviations", "Mandatory Compliance", "Cross major highways/junctions ONLY at cones under Official direction (0.5, 3.7, 23.9, 37.0, 65.9, 81.6, 106.6, 181.6 km). If leaving route for public toilet/aid, MUST return to EXACT departure point.", "2026 Runners Guide p.12 / Rules 2.4-2.5"),
        ("Toilets & Environment", "No Start Toilets, Dalgety Rule & Leave No Trace", "Strict Penalty", "NO toilets at Boydtown Beach (bushes prohibited). Dalgety Hall indoor toilets = RUNNERS ONLY (crew use building 50-100m behind hall). Pack out ALL waste/toilet paper/rubbish in crew vehicle; never leave human waste near Summit Path; never climb summit cairn.", "2026 Runners Guide p.27 / Rules 5.1.3"),
        ("Medical & Emergency", "000 First, Telstra Coverage, Insurance & Hospitals", "Safety Protocol", "Life-threatening emergency: CALL 000 FIRST, then WhatsApp Race Control (Bib/Name/Location/Issue). Telstra SIM strongly recommended (most officials carry Starlink). Install Emergency Plus & Fires Near Me apps. C2K has NO personal accident/ambulance cover (own insurance required). Hospitals: Bega (02) 6491 9999; Cooma 24h ED (02) 6455 3222.", "2026 Runners Guide p.25-26 / Rules 7.0"),
    ]
    rules_formatted = [
        {
            "Rule_ID": f"R-{i:02d}",
            "Category": cat,
            "Topic": topic,
            "Requirement_Status": req,
            "Details": details,
            "Source_Reference": src,
        }
        for i, (cat, topic, req, details, src) in enumerate(rules_rows, 1)
    ]

    # ------------------------------------------------------------------
    # TABLE 6: 2026 OFFICIAL EVENT SCHEDULE (AEDT)
    # ------------------------------------------------------------------
    schedule_rows = [
        ("Pre-Race", "Wed 30 Sep 2026", "20:00", "Webinar 1 - Race Rules", "Online via Zoom", "Informational webinar for runners and crew", ""),
        ("Pre-Race", "Wed 14 Oct 2026", "20:00", "Webinar 2 - Runners Considerations", "Online via Zoom", "Informational webinar for runners and crew", ""),
        ("Pre-Race", "Wed 28 Oct 2026", "20:00", "Webinar 3 - Support Crew & First Aid", "Online via Zoom", "Informational webinar for crews", ""),
        ("Race Week", "Wed 18 Nov 2026", "20:00", "Mandatory Pre-Race Briefing", "Online via Zoom", "MANDATORY for ALL runners AND at least 1 support crew member", ""),
        ("Race Week", "Thu 19 Nov 2026", "15:00 - 18:00", "Runner Check-in, Race Gear Collection & Support Crew Vehicle Check", "Seahorse Inn, Twofold Bay", "Bring Photo ID. Collect Race Bib, GPS Tracker, A4 Vehicle Sticker, Yellow Runner Ahead/Following signs. Complete 2-min vehicle inspection.", ""),
        ("Race Day 1", "Fri 20 Nov 2026", "04:50 - 05:00", "Mandatory Start-Line Race Registration", "Boydtown Beach, Twofold Bay", "Final check-in & pre-race photos. NO TOILETS at Boydtown Beach!", "0.0 km"),
        ("Race Day 1", "Fri 20 Nov 2026", "05:10", "Welcome to Country & Smoking Ceremony", "Boydtown Beach, Twofold Bay", "Led by Uncle BJ Cruse (Yuin Elder)", "0.0 km"),
        ("Race Day 1", "Fri 20 Nov 2026", "05:30", "2026 RACE START", "Boydtown Beach, Twofold Bay", "Official start of 240 km journey (46-hour clock begins)", "0.0 km"),
        ("Cut-Off #1", "Fri 20 Nov 2026", "17:30 (12:00 hrs)", "Hard Cut-Off #1 - Cathcart General Store", "Cathcart General Store (CP 3)", "Must clear checkpoint by 17:30 or risk withdrawal", "70 km (69.8 km)"),
        ("Cut-Off #2", "Fri 20 Nov 2026", "23:30 (18:00 hrs)", "Hard Cut-Off #2 - Gunningrach Rd / Snowy River Way", "Gunningrach Rd & Snowy River Way (CP 4)", "Reflective vest mandatory from here; general pacers permitted", "106 km (106.7 km)"),
        ("Cut-Off #3", "Sat 21 Nov 2026", "06:30 (25:00 hrs)", "Hard Cut-Off #3 - Dalgety Bridge", "Dalgety Bridge West side (after CP 5 Dalgety Hall)", "Must clear Dalgety Bridge by 06:30", "148 km (148.25 km)"),
        ("Cut-Off #4", "Sat 21 Nov 2026", "14:00 (32:30 hrs)", "Hard Cut-Off #4 - Jindabyne Caravan Park", "Jindabyne Caravan & Holiday Discovery Park (CP 6)", "Updated 2026 cut-off (14:00 AEDT)", "184 km (183.8 km)"),
        ("Cut-Off #5", "Sat 21 Nov 2026", "23:00 (41:30 hrs)", "Hard Cut-Off #5 - Charlotte Pass", "Charlotte Pass Turnaround Loop Car Park (CP 8)", "Mandatory Summit Gear check + fitness check + mandatory pacer(s)", "222 km (221.8 km)"),
        ("Final Finish", "Sun 22 Nov 2026", "03:30 (46:00 hrs)", "RACE FINISH / FINAL CUT-OFF", "Charlotte Pass (via Mt Kosciuszko Summit)", "46-hour limit closes; return GPS tracker", "240 km (240.65 km)"),
        ("Post-Race", "Sun 22 Nov 2026", "07:00 - 09:00", "Post-Race Breakfast & Return of Signs & Trackers", "Adventist Alpine Village, Jindabyne", "Pre-paid buffet breakfast ($21/head); return vehicle warning signs & any remaining trackers", ""),
        ("Post-Race", "Sun 22 Nov 2026", "09:00 - 11:00", "Official Race Presentation", "Adventist Alpine Village, Jindabyne", "Presentation of Akubra hats (1st-time finishers), hat pins & finisher shirts", ""),
    ]
    schedule_formatted = [
        {
            "Phase": ph,
            "Date": dt,
            "Time_AEDT": tm,
            "Event": ev,
            "Location": loc,
            "Key_Details": det,
            "Course_Distance": dist,
        }
        for ph, dt, tm, ev, loc, det, dist in schedule_rows
    ]

    # Clean dashes across ALL tables
    waypoints = sanitize_records(waypoints)
    checkpoints = sanitize_records(checkpoints)
    toilets_aid = sanitize_records(toilets_aid)
    legs_rows = sanitize_records(legs_rows)
    rules_formatted = sanitize_records(rules_formatted)
    schedule_formatted = sanitize_records(schedule_formatted)

    # Save 6 CSVs
    tables = [
        ("01_master_course_waypoints.csv", waypoints),
        ("02_checkpoints_and_cutoffs.csv", checkpoints),
        ("03_toilets_and_aid_stations.csv", toilets_aid),
        ("04_course_legs_and_directions.csv", legs_rows),
        ("05_rules_gear_crew_pacers.csv", rules_formatted),
        ("06_2026_event_schedule.csv", schedule_formatted),
    ]
    for fname, rows in tables:
        out_path = DATA_DIR / fname
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {fname}: {len(rows)} rows")

    # Downsample course track (~600 points) for lightweight offline HTML map & elevation chart
    step = max(1, len(pts) // 600)
    sampled_track = [
        [round(tp["y"], 5), round(tp["x"], 5), round(tp["d"] / 1000.0, 2), round(tp.get("e", 0.0), 1)]
        for tp in pts[::step]
    ]
    # Ensure exact last point included
    last_tp = pts[-1]
    sampled_track.append([
        round(last_tp["y"], 5),
        round(last_tp["x"], 5),
        round(last_tp["d"] / 1000.0, 2),
        round(last_tp.get("e", 0.0), 1),
    ])

    master_json = {
        "metadata": {
            "event": "Coast to Kosciuszko (C2K) 2026 Ultramarathon",
            "edition": "18th Official Edition (November 2026)",
            "race_start_aedt": "2026-11-20T05:30:00+11:00",
            "race_finish_cutoff_aedt": "2026-11-22T03:30:00+11:00",
            "time_limit_hours": 46.0,
            "official_distance_km": 240.0,
            "gps_route_distance_km": round(rw.get("distance", 240653) / 1000.0, 2),
            "elevation_gain_m_guide": 5269,
            "elevation_gain_m_rwgps": round(rw.get("elevation_gain", 5467), 1),
            "confirmed_2026_runners": 67,
            "compiled_at": datetime.now().isoformat(timespec="seconds"),
            "sources": [
                "https://coasttokosci.com/wp-content/uploads/2026-Runners-Guide-3.pdf",
                "https://coasttokosci.com/wp-content/uploads/2026-Coast-To-Kosci-Race-Schedule.pdf",
                "https://coasttokosci.com/wp-content/uploads/2025-Coast-To-Kosci-Race-Rules.pdf",
                "https://coasttokosci.com/wp-content/uploads/Course-Directions-1.pdf",
                "https://ridewithgps.com/routes/41169431",
                "https://live.trackmelive.com.au/coasttokosci26/",
                "Australian Government National Public Toilet Map (data.gov.au export 2026-11-01)",
            ],
        },
        "tables": {
            "master_waypoints": waypoints,
            "checkpoints_and_cutoffs": checkpoints,
            "toilets_and_aid_stations": toilets_aid,
            "course_legs_and_directions": legs_rows,
            "rules_gear_crew_pacers": rules_formatted,
            "event_schedule_2026": schedule_formatted,
        },
        "course_profile": sampled_track,
    }
    (DATA_DIR / "c2k_2026_master_database.json").write_text(
        json.dumps(master_json, indent=2), encoding="utf-8"
    )
    print(f"Wrote c2k_2026_master_database.json ({len(sampled_track)} sampled track pts)")

    # Export clean offline GPX with all 25 waypoints + full 12,191-point track
    from xml.sax.saxutils import escape as xml_escape

    gpx_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Coast2Kosci_2026_Database" xmlns="http://www.topografix.com/GPX/1/1">',
        '  <metadata><name>Coast to Kosci (C2K) 2026 Official Course &amp; Waypoints</name></metadata>',
    ]
    for w in waypoints:
        desc = xml_escape(f"{w['Category']} | {w['Cutoff_Time_AEDT']} | Toilets: {w['Toilet_Status']} | {w['Notes']}".strip(" |"))
        name = xml_escape(f"{w['Distance_km']:.1f}km - {w['Location_Name']}")
        ele = w["Elevation_m"]
        gpx_lines.append(
            f'  <wpt lat="{w["Latitude"]:.6f}" lon="{w["Longitude"]:.6f}">'
            f'<ele>{ele}</ele><name>{name}</name><desc>{desc}</desc></wpt>'
        )
    gpx_lines.append('  <trk><name>Coast To Kosci Ultramarathon 240.65 km</name><trkseg>')
    for tp in pts:
        ele = tp.get("e", 0.0)
        gpx_lines.append(f'    <trkpt lat="{tp["y"]:.6f}" lon="{tp["x"]:.6f}"><ele>{ele:.1f}</ele></trkpt>')
    gpx_lines.extend(['  </trkseg></trk>', '</gpx>'])

    gpx_path = BASE_DIR / "official_docs" / "CoastToKosci_2026_Course_Route_With_Waypoints.gpx"
    gpx_path.write_text("\n".join(gpx_lines), encoding="utf-8")
    print(f"Wrote {gpx_path.name} ({len(waypoints)} waypoints, {len(pts)} trackpoints)")


if __name__ == "__main__":
    build_all()
