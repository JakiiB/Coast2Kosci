/**
 * Coast to Kosciuszko (C2K) - Multi-Source Live Telemetry Client & 46-Hour Simulator Engine
 * Connects to the 24/7 Google Apps Script Cloud Relay and enforces the Epistemic Integrity Protocol.
 */

window.C2KTelemetryClient = (function () {
  const RELAY_URL = "https://script.google.com/macros/s/AKfycbzPosb-6ZToFhkaZBTD82_g74ge7gCVl4DCQixR0LZ4qLkabb7zVAds_PN9Gn2DnDwF3Q/exec";
  const DEFAULT_RACE_START_ISO = "2026-11-20T05:30:00+11:00";

  let courseData = null;
  let mode = "SIM"; // "SIM" | "LIVE"
  let simPlaying = false;
  let simSpeedMultiplier = 180;
  let simElapsedHours = 6.2;
  let targetFinishHours = 38.5;

  let runnerState = null;
  let crewState = null;
  let lastCloudState = null;
  let onStateUpdateCallback = null;
  let lastTick = performance.now();
  let lastLiveRefreshTick = 0;

  let landmarks = {
    total: 241.25,
    cp1: 24.38,
    cp2: 51.67,
    cowBail: 56.07,
    cp3: 70.60,
    cp4: 107.56,
    cp5: 148.93,
    cp6: 184.86,
    cp7: 213.87,
    cp8: 222.62,
    summit: 231.94
  };

  // Highway detour waypoints for Crew Car when U-turning at Cow Bail Trail (56.07 km -> Cathcart 70.60 km)
  // Cow Bail Gate -> Rocky Hall CP2 -> Wyndham -> Mt Darragh Rd -> Cathcart General Store
  const CREW_DETOUR_WAYPOINTS = [
    [149.47101, -36.90518, 295],
    [149.50321, -36.92718, 255],
    [149.52750, -36.92610, 240],
    [149.47200, -36.88500, 490],
    [149.43500, -36.85900, 740],
    [149.39124, -36.84325, 765]
  ];

  function extractLandmarksFromCourse(data) {
    if (!data) return;
    const total = (data.meta && data.meta.total_distance_km) || 241.25;
    const pois = data.pois || [];
    function findKm(substr, fallback) {
      const hit = pois.find(function (p) { return p.name && p.name.indexOf(substr) !== -1; });
      return hit ? hit.course_km : fallback;
    }
    landmarks = {
      total: total,
      cp1: findKm("Checkpoint #1", 24.38),
      cp2: findKm("Checkpoint #2", 51.67),
      cowBail: (data.meta && data.meta.cow_bail_start_km) || findKm("Cow Bail Trail", 56.07),
      cp3: (data.meta && data.meta.cathcart_cp3_km) || findKm("Checkpoint #3", 70.60),
      cp4: findKm("Checkpoint #4", 107.56),
      cp5: findKm("Checkpoint #5", 148.93),
      cp6: findKm("Checkpoint #6", 184.86),
      cp7: findKm("Checkpoint #7", 213.87),
      cp8: (data.meta && data.meta.charlotte_pass_cp8_km) || findKm("Checkpoint #8", 222.62),
      summit: (data.meta && data.meta.summit_km) || findKm("Summit of Mt Kosciuszko", 231.94)
    };
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const r = 6371.0;
    const p1 = (lat1 * Math.PI) / 180.0;
    const p2 = (lat2 * Math.PI) / 180.0;
    const dp = ((lat2 - lat1) * Math.PI) / 180.0;
    const dl = ((lon2 - lon1) * Math.PI) / 180.0;
    const a =
      Math.sin(dp / 2) * Math.sin(dp / 2) +
      Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * r * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a)));
  }

  function snapToCourse(lat, lon, prevCourseKm) {
    if (!courseData || !courseData.track || !courseData.track.length) {
      return { course_km: 0, ele_m: 0, grade_pct: 0, offset_km: 0 };
    }
    const track = courseData.track;
    let bestD = Infinity;
    let bestPt = track[0];
    for (let i = 0; i < track.length; i++) {
      const pt = track[i];
      const d = haversineKm(lat, lon, pt[1], pt[0]);
      if (d < bestD) {
        bestD = d;
        bestPt = pt;
      }
    }

    // Disambiguate Charlotte Pass <-> Mt Kosciuszko out-and-back (222.62 km - 241.25 km, turnaround at 231.94 km)
    if (bestPt[3] >= landmarks.cp8 - 0.5 && typeof prevCourseKm === "number" && !isNaN(prevCourseKm)) {
      const wantReturn = prevCourseKm >= landmarks.summit - 0.5;
      let legBestD = Infinity;
      let legBestPt = null;
      for (let i = 0; i < track.length; i++) {
        const pt = track[i];
        const km = pt[3];
        if (km < landmarks.cp8 - 0.5) continue;
        if (wantReturn && km < landmarks.summit - 0.1) continue;
        if (!wantReturn && km > landmarks.summit + 0.3) continue;
        const d = haversineKm(lat, lon, pt[1], pt[0]);
        if (d < legBestD) {
          legBestD = d;
          legBestPt = pt;
        }
      }
      if (legBestPt && legBestD < 3.5) {
        bestD = legBestD;
        bestPt = legBestPt;
      }
    }

    return {
      lon: bestPt[0],
      lat: bestPt[1],
      ele_m: bestPt[2],
      course_km: bestPt[3],
      grade_pct: bestPt[4],
      offset_km: bestD
    };
  }

  function getRaceStartMs() {
    const iso =
      (lastCloudState && lastCloudState.raceStartIso) ||
      (courseData && courseData.meta && courseData.meta.race_start_iso) ||
      DEFAULT_RACE_START_ISO;
    const ms = Date.parse(iso);
    return isNaN(ms) ? Date.parse(DEFAULT_RACE_START_ISO) : ms;
  }

  function getEffectiveElapsedHours() {
    if (mode === "SIM") {
      return simElapsedHours;
    }
    return (Date.now() - getRaceStartMs()) / 3600000.0;
  }

  function formatFixAge(updatedAtMs) {
    if (!updatedAtMs || updatedAtMs <= 0) return "Awaiting race start";
    const mins = Math.max(0, (Date.now() - updatedAtMs) / 60000.0);
    if (mins < 1.0) return "Just now";
    if (mins < 60.0) return Math.round(mins) + "m ago";
    const hrs = Math.floor(mins / 60.0);
    const remM = Math.round(mins % 60.0);
    return hrs + "h " + remM + "m ago";
  }

  function computeSimulatedStates(elapsedHours) {
    if (!courseData || !courseData.track) return;
    const totalKm = landmarks.total;

    const finished = elapsedHours >= targetFinishHours;
    const progressFrac = Math.max(0, Math.min(1, elapsedHours / targetFinishHours));
    const curvedFrac = Math.pow(progressFrac, 0.92);
    const simonKm = finished ? totalKm : Math.min(totalKm, curvedFrac * totalKm);

    const pt = window.C2KTerrainEngine.getPointAtKm(simonKm) || courseData.track[0];
    const grade = pt[4] || 0;
    const fatigueFactor = 1.0 - 0.28 * progressFrac;
    const gradePenalty = grade > 0 ? Math.max(0.38, 1.0 - grade * 0.045) : Math.min(1.18, 1.0 - grade * 0.015);
    const simonSpeed = finished ? 0 : Math.max(3.2, 9.8 * fatigueFactor * gradePenalty);

    runnerState = {
      name: "Simon",
      bib: "C2K",
      lon: pt[0],
      lat: pt[1],
      ele_m: pt[2],
      course_km: simonKm,
      grade_pct: grade,
      speed_kmh: Math.round(simonSpeed * 10) / 10,
      battery_pct: Math.max(18, Math.round(100 - (elapsedHours % 18) * 4.2)),
      source: "46h Race Simulator",
      epistemic: "SIMULATION",
      fix_age_text: "Simulated @" + targetFinishHours + "h target",
      note: finished ? "Finished at Charlotte Pass (" + targetFinishHours + "h target!)" : getSectionNote(simonKm),
      updated_at: Date.now()
    };

    // Crew Car realistic leapfrog & Cow Bail Trail detour logic derived from exact landmarks
    let crewLon = pt[0];
    let crewLat = pt[1];
    let crewEle = pt[2];
    let crewKm = simonKm;
    let crewSpeed = 0;
    let crewNote = "Leapfrog support alongside Simon";

    if (simonKm < landmarks.cp1) {
      const towambaPt = window.C2KTerrainEngine.getPointAtKm(landmarks.cp1) || pt;
      crewLon = towambaPt[0];
      crewLat = towambaPt[1];
      crewEle = towambaPt[2];
      crewKm = landmarks.cp1;
      crewSpeed = 0;
      crewNote = "Staged at Towamba Rendezvous (CP1)";
    } else if (simonKm >= landmarks.cowBail && simonKm <= landmarks.cp3) {
      const span = Math.max(1.0, landmarks.cp3 - landmarks.cowBail);
      const detourFrac = (simonKm - landmarks.cowBail) / span;
      const segFloat = detourFrac * (CREW_DETOUR_WAYPOINTS.length - 1);
      const idx0 = Math.min(CREW_DETOUR_WAYPOINTS.length - 2, Math.floor(segFloat));
      const idx1 = idx0 + 1;
      const subT = segFloat - idx0;
      const w0 = CREW_DETOUR_WAYPOINTS[idx0];
      const w1 = CREW_DETOUR_WAYPOINTS[idx1];
      crewLon = w0[0] + (w1[0] - w0[0]) * subT;
      crewLat = w0[1] + (w1[1] - w0[1]) * subT;
      crewEle = w0[2] + (w1[2] - w0[2]) * subT;
      crewKm = landmarks.cowBail + detourFrac * span;
      crewSpeed = detourFrac < 0.85 ? 58.0 : 0.0;
      crewNote = detourFrac < 0.85
        ? "Detouring around Cow Bail Trail via Mt Darragh Rd"
        : "Staged at CP3 Cathcart awaiting Simon";
    } else if (simonKm > landmarks.cp8 && simonKm < totalKm - 0.5) {
      const cp8Pt = window.C2KTerrainEngine.getPointAtKm(landmarks.cp8) || pt;
      crewLon = cp8Pt[0];
      crewLat = cp8Pt[1];
      crewEle = cp8Pt[2];
      crewKm = landmarks.cp8;
      crewSpeed = 0;
      crewNote = "Parked at Charlotte Pass (CP8 / Finish Gate)";
    } else if (finished) {
      const finPt = window.C2KTerrainEngine.getPointAtKm(totalKm) || pt;
      crewLon = finPt[0];
      crewLat = finPt[1];
      crewEle = finPt[2];
      crewKm = totalKm;
      crewSpeed = 0;
      crewNote = "Celebrate Finish at Charlotte Pass!";
    } else {
      const leapKm = Math.min(totalKm, Math.ceil((simonKm + 0.8) / 3.5) * 3.5);
      const cPt = window.C2KTerrainEngine.getPointAtKm(leapKm) || pt;
      crewLon = cPt[0];
      crewLat = cPt[1];
      crewEle = cPt[2];
      crewKm = leapKm;
      crewSpeed = Math.abs(leapKm - simonKm) < 0.4 ? 32.0 : 0.0;
      crewNote = crewSpeed > 0 ? "Leapfrogging ahead on course" : "Parked on shoulder (" + leapKm.toFixed(1) + " km)";
    }

    crewState = {
      name: "Crew Car (Jake)",
      lon: crewLon,
      lat: crewLat,
      ele_m: crewEle,
      course_km: crewKm,
      speed_kmh: crewSpeed,
      battery_pct: 96,
      source: "46h Race Simulator",
      epistemic: "SIMULATION",
      fix_age_text: "Simulated Crew Leapfrog",
      note: crewNote,
      updated_at: Date.now()
    };

    if (window.C2KWeatherClouds3D) {
      window.C2KWeatherClouds3D.setSolarAltitudeForRaceHour(elapsedHours);
    }

    notifyListeners();
  }

  function getSectionNote(km) {
    if (km < landmarks.cp1) return "Stage 1: Boydtown Beach to Towamba Valley (CP1)";
    if (km < landmarks.cp2) return "Stage 2: Towamba River to Rocky Hall (CP2)";
    if (km < landmarks.cowBail) return "Stage 3: Approaching Cow Bail Trail Foot-Only Gate";
    if (km < landmarks.cp3) return "Stage 4: Climbing Cow Bail Trail to Cathcart (CP3)";
    if (km < landmarks.cp4) return "Stage 5: Monaro Plains to Gunningrah (CP4)";
    if (km < landmarks.cp5) return "Stage 6: Snowy River Way to Dalgety Bridge (CP5)";
    if (km < landmarks.cp6) return "Stage 7: Dalgety to Lake Jindabyne (CP6)";
    if (km < landmarks.cp7) return "Stage 8: Kosciuszko Rd Climb to Perisher Valley (CP7)";
    if (km < landmarks.cp8) return "Stage 9: Perisher to Charlotte Pass (CP8)";
    if (km < landmarks.summit) return "Stage 10: Summit Push to Mt Kosciuszko (2,228m)";
    return "Stage 11: Final Descent from Summit to Charlotte Pass Finish!";
  }

  async function pollCloudRelay() {
    try {
      const resp = await fetch(RELAY_URL + "?action=c2k-state&_t=" + Date.now());
      if (!resp.ok) return;
      const data = await resp.json();
      lastCloudState = data;

      const rUpd = data.runner && data.runner.updated_at ? data.runner.updated_at : 0;
      const cUpd = data.crew && data.crew.updated_at ? data.crew.updated_at : 0;
      const latestPingAgeMs = Date.now() - Math.max(rUpd, cUpd);

      if (mode === "LIVE" || (latestPingAgeMs < 6 * 3600 * 1000 && data.raceStatus === "LIVE_RACE")) {
        if (mode !== "LIVE") {
          setMode("LIVE");
        } else {
          applyLiveCloudState(data);
        }
      }
    } catch (err) {
      console.warn("[Telemetry] Cloud relay poll warning:", err);
    }
  }

  function applyLiveCloudState(data) {
    if (!data) return;
    if (data.runner) {
      const rUpd = Number(data.runner.updated_at || 0);
      const prevKnownKm =
        (runnerState && typeof runnerState.confirmed_km === "number")
          ? runnerState.confirmed_km
          : (typeof data.runner.course_km === "number" ? data.runner.course_km : undefined);
      const snap = snapToCourse(data.runner.lat, data.runner.lon, prevKnownKm);
      const baseKm =
        typeof data.runner.course_km === "number" && data.runner.course_km > 0
          ? data.runner.course_km
          : snap.course_km;

      let epistemicStatus = "PRE_RACE_BASELINE";
      let displayKm = baseKm;
      let displayLat = data.runner.lat;
      let displayLon = data.runner.lon;
      let displayEle = data.runner.ele_m !== undefined ? data.runner.ele_m : snap.ele_m;

      if (rUpd > 0) {
        const ageMins = Math.max(0, (Date.now() - rUpd) / 60000.0);
        if (ageMins <= 12.0) {
          epistemicStatus = "CONFIRMED_FIX";
        } else if (ageMins <= 120.0 && (data.runner.speed_kmh || 0) > 2.0) {
          epistemicStatus = "HYPOTHESIS_PACE_ESTIMATE";
          const estExtraKm = ((ageMins - 2.0) / 60.0) * Math.min(8.5, data.runner.speed_kmh || 6.0);
          displayKm = Math.min(landmarks.total, baseKm + estExtraKm);
          const estPt = window.C2KTerrainEngine.getPointAtKm(displayKm);
          if (estPt) {
            displayLon = estPt[0];
            displayLat = estPt[1];
            displayEle = estPt[2];
          }
        } else {
          epistemicStatus = "STALE_FIX";
        }
      }

      runnerState = {
        name: data.runner.name || "Simon",
        bib: data.runner.bib || "C2K",
        lat: displayLat,
        lon: displayLon,
        ele_m: displayEle,
        course_km: displayKm,
        confirmed_lat: data.runner.lat,
        confirmed_lon: data.runner.lon,
        confirmed_km: baseKm,
        grade_pct: snap.grade_pct,
        speed_kmh: data.runner.speed_kmh || 0,
        battery_pct: data.runner.battery_pct !== undefined ? data.runner.battery_pct : 100,
        source: data.runner.source || "Cloud Relay",
        epistemic: epistemicStatus,
        fix_age_text: formatFixAge(rUpd),
        note: data.runner.note || getSectionNote(displayKm),
        updated_at: rUpd
      };
    }

    if (data.crew) {
      const cUpd = Number(data.crew.updated_at || 0);
      const cSnap = snapToCourse(data.crew.lat, data.crew.lon);
      let cEpistemic = "PRE_RACE_BASELINE";
      if (cUpd > 0) {
        const cAgeMins = Math.max(0, (Date.now() - cUpd) / 60000.0);
        cEpistemic = cAgeMins <= 15.0 ? "CONFIRMED_FIX" : "STALE_FIX";
      }
      const offCourse = cSnap.offset_km > 25.0;
      const defaultNote = offCourse
        ? "Off-course (" + Math.round(cSnap.offset_km) + " km from C2K route)"
        : "Offset " + cSnap.offset_km.toFixed(1) + " km from trail";

      crewState = {
        name: data.crew.name || "Crew Car (Jake)",
        lat: data.crew.lat,
        lon: data.crew.lon,
        ele_m: data.crew.ele_m !== undefined ? data.crew.ele_m : cSnap.ele_m,
        course_km: cSnap.course_km,
        off_course_km: offCourse ? cSnap.offset_km : 0,
        speed_kmh: data.crew.speed_kmh || 0,
        battery_pct: data.crew.battery_pct !== undefined ? data.crew.battery_pct : 100,
        source: data.crew.source || "GPSLogger Live",
        epistemic: cEpistemic,
        fix_age_text: formatFixAge(cUpd),
        note: data.crew.note || defaultNote,
        updated_at: cUpd
      };
    }

    if (mode === "LIVE" && window.C2KWeatherClouds3D && window.C2KWeatherClouds3D.setSolarAltitudeFromRealClock) {
      window.C2KWeatherClouds3D.setSolarAltitudeFromRealClock();
    }

    notifyListeners();
  }

  async function submitCrewCheckin(payload) {
    const body = Object.assign({ action: "c2k-checkin" }, payload);
    const resp = await fetch(RELAY_URL, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify(body)
    });
    const res = await resp.json();
    if (res && res.success && res.state) {
      lastCloudState = res.state;
      setMode("LIVE");
      applyLiveCloudState(res.state);
    }
    return res;
  }

  async function submitGpxIngest(payload) {
    const body = Object.assign({ action: "c2k-gpx-ingest" }, payload);
    const resp = await fetch(RELAY_URL, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify(body)
    });
    const res = await resp.json();
    if (res && res.success) {
      await pollCloudRelay();
      setMode("LIVE");
    }
    return res;
  }

  function setMode(newMode) {
    mode = newMode === "LIVE" ? "LIVE" : "SIM";
    if (mode === "SIM") {
      computeSimulatedStates(simElapsedHours);
    } else if (lastCloudState) {
      applyLiveCloudState(lastCloudState);
    } else {
      applyLiveCloudState({
        raceStatus: "PRE_RACE_SIM",
        raceStartIso: DEFAULT_RACE_START_ISO,
        runner: {
          name: "Simon",
          bib: "C2K",
          lat: courseData.track[0][1],
          lon: courseData.track[0][0],
          ele_m: courseData.track[0][2],
          course_km: 0,
          speed_kmh: 0,
          source: "Pre-Race Baseline",
          note: "Ready at Boydtown Beach Start Line",
          updated_at: 0
        },
        crew: {
          name: "Crew Car (Jake)",
          lat: -37.09225,
          lon: 149.87195,
          ele_m: 5,
          course_km: 0,
          speed_kmh: 0,
          source: "Pre-Race Baseline",
          note: "Support Crew staged at Boydtown Beach",
          updated_at: 0
        }
      });
    }

    document.querySelectorAll("[data-telemetry-mode]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-telemetry-mode") === mode);
    });
    const pill = document.getElementById("broadcast-status-pill");
    const pillText = document.getElementById("broadcast-status-text");
    if (pill && pillText) {
      pill.classList.toggle("is-live", mode === "LIVE");
      pillText.textContent = mode === "LIVE" ? "LIVE CLOUD" : "46H SIMULATOR";
    }
  }

  function setSimElapsedHours(hrs) {
    simElapsedHours = Math.max(0, Math.min(46.0, parseFloat(hrs) || 0));
    if (mode !== "SIM") setMode("SIM");
    computeSimulatedStates(simElapsedHours);
  }

  function setSimProgressByKm(targetKm) {
    const totalKm = landmarks.total;
    const frac = Math.max(0, Math.min(1, targetKm / totalKm));
    const hrs = Math.pow(frac, 1.0 / 0.92) * targetFinishHours;
    setSimElapsedHours(hrs);
  }

  function toggleSimPlayback() {
    simPlaying = !simPlaying;
    if (simPlaying && mode !== "SIM") {
      setMode("SIM");
    }
    return simPlaying;
  }

  function setSimSpeed(mult) {
    simSpeedMultiplier = parseFloat(mult) || 180;
  }

  function notifyListeners() {
    if (onStateUpdateCallback) {
      onStateUpdateCallback(runnerState, crewState, getEffectiveElapsedHours(), mode);
    }
  }

  function tickLoop(now) {
    const dt = Math.min(0.1, (now - lastTick) / 1000);
    lastTick = now;

    if (mode === "SIM" && simPlaying) {
      simElapsedHours += (dt * simSpeedMultiplier) / 3600.0;
      if (simElapsedHours >= 46.0) {
        simElapsedHours = 0;
      }
      computeSimulatedStates(simElapsedHours);
    } else if (mode === "LIVE" && now - lastLiveRefreshTick > 5000) {
      lastLiveRefreshTick = now;
      if (lastCloudState) {
        applyLiveCloudState(lastCloudState);
      } else {
        notifyListeners();
      }
    }

    requestAnimationFrame(tickLoop);
  }

  function init(data, callback) {
    courseData = data;
    onStateUpdateCallback = callback;
    extractLandmarksFromCourse(courseData);
    computeSimulatedStates(simElapsedHours);
    pollCloudRelay();
    setInterval(pollCloudRelay, 15000);
    requestAnimationFrame(tickLoop);
  }

  return {
    init: init,
    getRelayUrl: function () { return RELAY_URL; },
    getExternalTrackerUrl: function () {
      return (lastCloudState && lastCloudState.externalTrackerUrl) || "https://live.trackmelive.com.au/";
    },
    getMode: function () { return mode; },
    setMode: setMode,
    getSimElapsedHours: function () { return getEffectiveElapsedHours(); },
    setSimElapsedHours: setSimElapsedHours,
    setSimProgressByKm: setSimProgressByKm,
    toggleSimPlayback: toggleSimPlayback,
    setSimSpeed: setSimSpeed,
    getRunnerState: function () { return runnerState; },
    getCrewState: function () { return crewState; },
    submitCrewCheckin: submitCrewCheckin,
    submitGpxIngest: submitGpxIngest,
    snapToCourse: snapToCourse,
    haversineKm: haversineKm
  };
})();
