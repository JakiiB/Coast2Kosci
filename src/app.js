/**
 * Coast to Kosciuszko (C2K) - Main Application Orchestrator
 */

window.C2KApp = (function () {
  let courseData = null;
  let activeLocMethod = "checkpoint";
  let parsedGpxPoints = [];

  function boot() {
    courseData = window.C2K_COURSE_DATA;
    if (!courseData) {
      console.error("[C2K] Missing window.C2K_COURSE_DATA bundle.");
      return;
    }

    document.body.setAttribute("data-mobile-sheet", "map");

    // 1. Initialize Broadcast HUD & Elevation Profile
    window.C2KBroadcastHud.init(courseData);

    // 2. Initialize 3D Atmospheric Cloud, Wind & Radar Engine
    window.C2KWeatherClouds3D.init("atmosphere-canvas", courseData.weather_zones || []);

    // 3. Initialize 3D Terrain Map
    window.C2KTerrainEngine.init("map-container", courseData, function () {
      window.C2KTelemetryClient.init(courseData, function (runner, crew, elapsedHours, mode) {
        window.C2KTerrainEngine.updateEntities(runner, crew);
        window.C2KBroadcastHud.updateHud(runner, crew, elapsedHours, mode);
      });
    });

    bindUiControls();
    populateCheckpointSelect();
  }

  function setMobileSheet(sheetName) {
    const next = sheetName || "map";
    document.body.setAttribute("data-mobile-sheet", next);
    document.querySelectorAll("button[data-mobile-sheet]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-mobile-sheet") === next);
    });
    if (window.C2KBroadcastHud && window.C2KBroadcastHud.resizeElevationCanvas) {
      setTimeout(function () {
        window.C2KBroadcastHud.resizeElevationCanvas();
      }, 60);
    }
  }

  function parseGpxXmlClient(xmlText) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlText, "application/xml");
    const parseErr = doc.querySelector("parsererror");
    if (parseErr) {
      throw new Error("Invalid GPX XML file.");
    }
    const trkpts = doc.getElementsByTagNameNS("*", "trkpt");
    const fallbackPts = trkpts.length ? trkpts : doc.getElementsByTagName("trkpt");
    const points = [];
    for (let i = 0; i < fallbackPts.length; i++) {
      const node = fallbackPts[i];
      const lat = parseFloat(node.getAttribute("lat"));
      const lon = parseFloat(node.getAttribute("lon"));
      if (isNaN(lat) || isNaN(lon)) continue;
      const eleNode = node.getElementsByTagName("ele")[0] || node.getElementsByTagNameNS("*", "ele")[0];
      const timeNode = node.getElementsByTagName("time")[0] || node.getElementsByTagNameNS("*", "time")[0];
      const spdNode = node.getElementsByTagNameNS("*", "speed")[0] || node.getElementsByTagName("speed")[0];
      const eleVal = eleNode && eleNode.textContent ? parseFloat(eleNode.textContent.trim()) : undefined;
      const spdVal = spdNode && spdNode.textContent ? parseFloat(spdNode.textContent.trim()) : undefined;
      points.push({
        lat: Number(lat.toFixed(6)),
        lon: Number(lon.toFixed(6)),
        ele: eleVal !== undefined && !isNaN(eleVal) ? Number(eleVal.toFixed(1)) : undefined,
        time: timeNode && timeNode.textContent ? timeNode.textContent.trim() : undefined,
        spd: spdVal !== undefined && !isNaN(spdVal) ? Number(spdVal.toFixed(3)) : 0
      });
    }
    return points;
  }

  function bindUiControls() {
    // Imagery Switcher (Google 3D Hybrid, Esri World Imagery)
    document.querySelectorAll("[data-imagery]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const mode = btn.getAttribute("data-imagery");
        document.querySelectorAll("[data-imagery]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        window.C2KTerrainEngine.setImageryLayer(mode);
      });
    });

    // Terrain Relief Exaggeration Switcher
    document.querySelectorAll("[data-relief]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const val = parseFloat(btn.getAttribute("data-relief"));
        document.querySelectorAll("[data-relief]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        window.C2KTerrainEngine.setTerrainExaggeration(val);
      });
    });

    // Atmospheric Toggles (3D Clouds, Live Radar, 10km Milestones)
    const btnClouds = document.getElementById("toggle-3d-clouds");
    if (btnClouds) {
      btnClouds.addEventListener("click", function () {
        const active = !btnClouds.classList.contains("active-cyan");
        btnClouds.classList.toggle("active-cyan", active);
        window.C2KWeatherClouds3D.setCloudsEnabled(active);
      });
    }

    const btnRadar = document.getElementById("toggle-bom-radar");
    if (btnRadar) {
      btnRadar.addEventListener("click", function () {
        const active = !btnRadar.classList.contains("active-cyan");
        btnRadar.classList.toggle("active-cyan", active);
        window.C2KWeatherClouds3D.setRadarEnabled(active);
      });
    }

    const btnMilestones = document.getElementById("toggle-milestones");
    if (btnMilestones) {
      btnMilestones.addEventListener("click", function () {
        const active = !btnMilestones.classList.contains("active");
        btnMilestones.classList.toggle("active", active);
        window.C2KTerrainEngine.setMilestonesVisible(active);
      });
    }

    // Camera Director Buttons
    document.querySelectorAll("[data-cam-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const mode = btn.getAttribute("data-cam-mode");
        window.C2KTerrainEngine.setCameraMode(mode);
        if (window.innerWidth <= 900) {
          setMobileSheet("map");
        }
      });
    });

    // Quick Landmark Fly-To Buttons
    document.querySelectorAll("[data-fly-km]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const km = parseFloat(btn.getAttribute("data-fly-km"));
        const pt = window.C2KTerrainEngine.getPointAtKm(km);
        if (pt) {
          window.C2KTerrainEngine.flyToCoordinate(pt[0], pt[1], 13.7, 68, pt[5]);
          if (window.innerWidth <= 900) {
            setMobileSheet("map");
          }
        }
      });
    });

    // Telemetry Mode Switcher (46H SIM vs LIVE CLOUD)
    document.querySelectorAll("[data-telemetry-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const m = btn.getAttribute("data-telemetry-mode");
        window.C2KTelemetryClient.setMode(m);
      });
    });

    // Mobile Sheet Switcher
    document.querySelectorAll("button[data-mobile-sheet]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const target = btn.getAttribute("data-mobile-sheet");
        const current = document.body.getAttribute("data-mobile-sheet") || "map";
        if (target !== "map" && current === target) {
          setMobileSheet("map");
        } else {
          setMobileSheet(target);
        }
      });
    });

    // Simulator Play / Pause & Speed Controls
    const btnPlay = document.getElementById("btn-sim-play");
    if (btnPlay) {
      btnPlay.addEventListener("click", function () {
        const playing = window.C2KTelemetryClient.toggleSimPlayback();
        btnPlay.textContent = playing ? "⏸ PAUSE SIM" : "▶ PLAY 46H SIM";
        btnPlay.classList.toggle("active", playing);
      });
    }

    document.querySelectorAll("[data-sim-speed]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const spd = parseFloat(btn.getAttribute("data-sim-speed"));
        document.querySelectorAll("[data-sim-speed]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        window.C2KTelemetryClient.setSimSpeed(spd);
      });
    });

    const simSlider = document.getElementById("sim-time-slider");
    if (simSlider) {
      simSlider.addEventListener("input", function () {
        window.C2KTelemetryClient.setSimElapsedHours(parseFloat(simSlider.value));
      });
    }

    // Refresh Live Weather button
    const btnRefreshWx = document.getElementById("btn-refresh-weather");
    if (btnRefreshWx) {
      btnRefreshWx.addEventListener("click", function () {
        btnRefreshWx.textContent = "↻ SYNCING...";
        window.C2KWeatherClouds3D.refreshLiveWeather().finally(function () {
          btnRefreshWx.textContent = "↻ LIVE WX";
        });
      });
    }

    // Native <dialog closedby="any"> Crew Check-In Dialog
    const modal = document.getElementById("crew-checkin-modal");
    const btnOpenModal = document.getElementById("btn-open-checkin");
    const btnCloseModal = document.getElementById("btn-close-checkin");
    const feedbackEl = document.getElementById("checkin-feedback");
    const trackerLinkEl = document.getElementById("link-official-tracker");

    function setFeedback(msg, isError) {
      if (!feedbackEl) return;
      if (!msg) {
        feedbackEl.hidden = true;
        feedbackEl.textContent = "";
        feedbackEl.className = "checkin-feedback";
        return;
      }
      feedbackEl.hidden = false;
      feedbackEl.textContent = msg;
      feedbackEl.className = "checkin-feedback " + (isError ? "is-error" : "is-success");
    }

    function setActiveLocMethod(method) {
      activeLocMethod = method || "checkpoint";
      document.querySelectorAll("[data-loc-method]").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-loc-method") === activeLocMethod);
      });
      ["checkpoint", "gps", "gpx"].forEach(function (name) {
        const panel = document.getElementById("loc-panel-" + name);
        if (panel) {
          panel.hidden = name !== activeLocMethod;
        }
      });
      setFeedback("", false);
    }

    document.querySelectorAll("[data-loc-method]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setActiveLocMethod(btn.getAttribute("data-loc-method"));
      });
    });

    function openCheckinDialog() {
      if (!modal) return;
      if (trackerLinkEl && window.C2KTelemetryClient && window.C2KTelemetryClient.getExternalTrackerUrl) {
        trackerLinkEl.href = window.C2KTelemetryClient.getExternalTrackerUrl();
      }
      setFeedback("", false);
      if (typeof modal.showModal === "function") {
        if (!modal.open) modal.showModal();
      } else {
        modal.setAttribute("open", "");
      }
    }

    function closeCheckinDialog(reason) {
      if (!modal) return;
      if (typeof modal.close === "function") {
        if (modal.open) modal.close(reason || "cancel");
      } else {
        modal.removeAttribute("open");
      }
    }

    if (btnOpenModal) {
      btnOpenModal.addEventListener("click", openCheckinDialog);
    }
    if (btnCloseModal) {
      btnCloseModal.addEventListener("click", function () {
        closeCheckinDialog("cancel");
      });
    }
    if (modal) {
      modal.addEventListener("close", function () {
        const rv = modal.returnValue;
        modal.returnValue = "";
        if (rv === "cancel" || rv === "dismiss") {
          setFeedback("", false);
        }
      });

      // Fallback backdrop light-dismiss for browsers without HTMLDialogElement.prototype.closedBy
      if (!("closedBy" in HTMLDialogElement.prototype)) {
        let downOutside = false;
        modal.addEventListener("pointerdown", function (e) {
          if (e.target !== modal) {
            downOutside = false;
            return;
          }
          const rect = modal.getBoundingClientRect();
          downOutside =
            e.clientX < rect.left ||
            e.clientX > rect.right ||
            e.clientY < rect.top ||
            e.clientY > rect.bottom;
        });
        modal.addEventListener("pointerup", function (e) {
          if (!downOutside || e.target !== modal) return;
          const rect = modal.getBoundingClientRect();
          const upOutside =
            e.clientX < rect.left ||
            e.clientX > rect.right ||
            e.clientY < rect.top ||
            e.clientY > rect.bottom;
          downOutside = false;
          if (upOutside) {
            closeCheckinDialog("dismiss");
          }
        });
      }
    }

    // Use Phone GPS Button inside GPS Tab
    const btnUseGps = document.getElementById("btn-use-phone-gps");
    if (btnUseGps) {
      btnUseGps.addEventListener("click", function () {
        if (!navigator.geolocation) {
          setFeedback("Browser Geolocation is not available on this device.", true);
          return;
        }
        btnUseGps.textContent = "Acquiring Satellite Fix...";
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            document.getElementById("checkin-lat").value = pos.coords.latitude.toFixed(6);
            document.getElementById("checkin-lon").value = pos.coords.longitude.toFixed(6);
            btnUseGps.textContent = "✓ Locked Current Phone GPS";
            setFeedback("Locked phone coordinates (" + pos.coords.latitude.toFixed(5) + ", " + pos.coords.longitude.toFixed(5) + ").", false);
          },
          function (err) {
            btnUseGps.textContent = "⚠ GPS Error";
            setFeedback("GPS Error: " + err.message, true);
          },
          { enableHighAccuracy: true, timeout: 10000 }
        );
      });
    }

    // Pick Spot on 3D Map inside GPS Tab
    const btnPickMap = document.getElementById("btn-pick-map-pin");
    if (btnPickMap) {
      btnPickMap.addEventListener("click", function () {
        closeCheckinDialog("pick-map");
        setMobileSheet("map");
        if (window.C2KTerrainEngine && window.C2KTerrainEngine.enableMapPinPick) {
          window.C2KTerrainEngine.enableMapPinPick(function (picked) {
            setActiveLocMethod("gps");
            if (picked) {
              document.getElementById("checkin-lat").value = Number(picked.lat).toFixed(6);
              document.getElementById("checkin-lon").value = Number(picked.lon).toFixed(6);
            }
            openCheckinDialog();
            if (picked) {
              setFeedback("Picked map spot (" + Number(picked.lat).toFixed(5) + ", " + Number(picked.lon).toFixed(5) + ").", false);
            }
          });
        }
      });
    }

    // Parse .gpx file in GPX Tab
    const gpxInput = document.getElementById("checkin-gpx-file");
    const gpxSummary = document.getElementById("gpx-parse-summary");
    if (gpxInput) {
      gpxInput.addEventListener("change", async function () {
        parsedGpxPoints = [];
        const file = gpxInput.files && gpxInput.files[0];
        if (!file) {
          if (gpxSummary) gpxSummary.textContent = "No .gpx file selected.";
          return;
        }
        try {
          const text = await file.text();
          parsedGpxPoints = parseGpxXmlClient(text);
          if (!parsedGpxPoints.length) {
            if (gpxSummary) gpxSummary.textContent = "No <trkpt> coordinates found in " + file.name + ".";
            return;
          }
          const last = parsedGpxPoints[parsedGpxPoints.length - 1];
          if (gpxSummary) {
            gpxSummary.textContent =
              "Ready: " + file.name + " (" + parsedGpxPoints.length + " pts) | Latest fix: " +
              last.lat.toFixed(5) + ", " + last.lon.toFixed(5) +
              (last.time ? " @ " + last.time : "");
          }
        } catch (err) {
          if (gpxSummary) gpxSummary.textContent = "GPX parse failed: " + err.message;
        }
      });
    }

    // Submit 1-Tap Crew Check-In (Strict Active-Tab Separation)
    const btnSubmitCheckin = document.getElementById("btn-submit-checkin");
    if (btnSubmitCheckin) {
      btnSubmitCheckin.addEventListener("click", async function () {
        const pin = document.getElementById("checkin-pin").value.trim();
        const roleSel = document.getElementById("checkin-role").value;
        const raceStatus = document.getElementById("checkin-race-status").value;
        const note = document.getElementById("checkin-note").value.trim();

        if (!pin) {
          setFeedback("Enter Crew Security PIN first.", true);
          return;
        }

        setFeedback("", false);

        if (activeLocMethod === "gpx") {
          if (!parsedGpxPoints.length) {
            setFeedback("Select a valid .gpx file containing <trkpt> points first.", true);
            return;
          }
          const slice = parsedGpxPoints.slice(-30);
          const lastPt = slice[slice.length - 1];
          btnSubmitCheckin.textContent = "Uploading GPX Track...";
          try {
            const roles = roleSel === "both" ? ["runner", "crew"] : [roleSel];
            let lastRes = null;
            for (let i = 0; i < roles.length; i++) {
              lastRes = await window.C2KTelemetryClient.submitGpxIngest({
                pin: pin,
                role: roles[i],
                points: slice,
                source: "Crew GPX File Upload",
                note: note || "Uploaded GPX track fix",
                forceLive: raceStatus === "LIVE_RACE"
              });
              if (lastRes && lastRes.error) break;
            }
            if (lastRes && lastRes.error) {
              setFeedback("GPX ingest error: " + lastRes.error, true);
            } else {
              closeCheckinDialog("submitted");
              window.C2KTerrainEngine.flyToCoordinate(lastPt.lon, lastPt.lat, 13.8, 66, -30);
            }
          } catch (e) {
            setFeedback("Network error uploading GPX: " + e.message, true);
          } finally {
            btnSubmitCheckin.textContent = "Broadcast Live Pin to 3D Map";
          }
          return;
        }

        let lat = NaN;
        let lon = NaN;
        let ele = null;
        let courseKm = null;

        if (activeLocMethod === "checkpoint") {
          const exactRaw = document.getElementById("checkin-exact-km").value.trim();
          let targetKm = parseFloat(document.getElementById("checkin-cp-select").value);
          if (exactRaw !== "") {
            const parsedExact = parseFloat(exactRaw);
            if (isNaN(parsedExact) || parsedExact < 0 || parsedExact > 241.25) {
              setFeedback("Exact course km must be between 0 and 241.25.", true);
              return;
            }
            targetKm = parsedExact;
          }
          const pt = window.C2KTerrainEngine.getPointAtKm(targetKm);
          if (!pt) {
            setFeedback("Could not resolve course coordinate for that checkpoint/km.", true);
            return;
          }
          lon = pt[0];
          lat = pt[1];
          ele = pt[2];
          courseKm = pt[3];
        } else {
          lat = parseFloat(document.getElementById("checkin-lat").value);
          lon = parseFloat(document.getElementById("checkin-lon").value);
          if (isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
            setFeedback("Enter valid Latitude and Longitude or use Phone GPS / Pick on Map.", true);
            return;
          }
        }

        btnSubmitCheckin.textContent = "Broadcasting to 24/7 Cloud Relay...";
        try {
          const payload = {
            pin: pin,
            raceStatus: raceStatus,
            note: note || "Crew Mobile Check-In"
          };
          const pinNote = note || (courseKm !== null ? "Pinned at " + courseKm.toFixed(1) + " km" : "Crew Mobile Check-In");
          if (roleSel === "both" || roleSel === "runner") {
            payload.runner = {
              lat: lat,
              lon: lon,
              ele: ele,
              course_km: courseKm,
              source: activeLocMethod === "checkpoint" ? "Crew KM Quick-Pin" : "Crew GPS Check-In",
              note: pinNote
            };
          }
          if (roleSel === "both" || roleSel === "crew") {
            payload.crew = {
              lat: lat,
              lon: lon,
              ele: ele,
              course_km: courseKm,
              source: activeLocMethod === "checkpoint" ? "Crew KM Quick-Pin" : "Crew GPS Check-In",
              note: pinNote
            };
          }

          const res = await window.C2KTelemetryClient.submitCrewCheckin(payload);
          if (res && res.error) {
            setFeedback("Check-in error: " + res.error, true);
          } else {
            closeCheckinDialog("submitted");
            window.C2KTerrainEngine.flyToCoordinate(lon, lat, 14.0, 68, -30);
          }
        } catch (e) {
          setFeedback("Network error submitting check-in: " + e.message, true);
        } finally {
          btnSubmitCheckin.textContent = "Broadcast Live Pin to 3D Map";
        }
      });
    }
  }

  function populateCheckpointSelect() {
    const sel = document.getElementById("checkin-cp-select");
    if (!sel || !courseData) return;

    let html = '<option value="0">Start - Boydtown Beach (0.0 km)</option>';
    (courseData.pois || []).forEach(function (p) {
      if (["checkpoint", "summit", "finish", "crew_uturn", "crew_rendezvous"].indexOf(p.category) !== -1) {
        html += '<option value="' + p.course_km + '">' + p.name + ' (' + p.course_km.toFixed(1) + ' km • ' + p.ele_m + 'm)</option>';
      }
    });
    for (let k = 10; k <= 240; k += 10) {
      html += '<option value="' + k + '">Course Milestone - ' + k + '.0 km</option>';
    }
    sel.innerHTML = html;
  }

  document.addEventListener("DOMContentLoaded", boot);

  return {
    getCurrentRunnerState: function () {
      return window.C2KTelemetryClient ? window.C2KTelemetryClient.getRunnerState() : null;
    },
    getCurrentCrewState: function () {
      return window.C2KTelemetryClient ? window.C2KTelemetryClient.getCrewState() : null;
    }
  };
})();
