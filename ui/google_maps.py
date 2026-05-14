"""Google Maps Streamlit components."""

from __future__ import annotations

import json
import math
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html


def downsample_route(route: pd.DataFrame, max_points: int = 650) -> pd.DataFrame:
    """Keep map payloads small while preserving the finish point."""

    if len(route) <= max_points:
        return route
    step = max(len(route) // max_points, 1)
    sampled = route.iloc[::step].copy()
    if sampled.index[-1] != route.index[-1]:
        sampled = pd.concat([sampled, route.tail(1)])
    return sampled


def google_maps_directions_url(route: pd.DataFrame) -> str:
    """Build a Google Maps directions URL for the route start and finish."""

    start = route.iloc[0]
    end = route.iloc[-1]
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={start['latitude']:.6f},{start['longitude']:.6f}"
        f"&destination={end['latitude']:.6f},{end['longitude']:.6f}"
        "&travelmode=walking"
    )


def route_heading_degrees(points: list[dict[str, float]]) -> float:
    """Return compass heading from first route point to final route point."""

    if len(points) < 2:
        return 0.0

    start = points[0]
    end = points[-1]
    lat1 = math.radians(start["lat"])
    lat2 = math.radians(end["lat"])
    delta_lng = math.radians(end["lng"] - start["lng"])
    y = math.sin(delta_lng) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)) - (math.sin(lat1) * math.cos(lat2) * math.cos(delta_lng))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def render_activity_route_map(
    track_points: pd.DataFrame,
    *,
    api_key: str,
    map_id: str = "",
    muted_color: str = "#64748b",
    activity_title: str = "Route replay",
) -> None:
    """Render the activity route as a Google Maps 3D-style hybrid map."""

    route = track_points.dropna(subset=["latitude", "longitude"]).copy()
    if route.empty:
        st.info("No GPS coordinates are stored for this activity yet.")
        return

    route = downsample_route(route)
    points = [
        {
            "lat": float(row.latitude),
            "lng": float(row.longitude),
            "distance": float(row.distance_km) if pd.notna(getattr(row, "distance_km", None)) else None,
            "elevation": float(row.elevation) if pd.notna(getattr(row, "elevation", None)) else None,
        }
        for row in route.itertuples()
    ]
    center = points[len(points) // 2]
    directions_url = google_maps_directions_url(route)
    route_heading = route_heading_degrees(points)

    if not api_key:
        query = quote_plus(f"{points[0]['lat']:.6f},{points[0]['lng']:.6f}")
        st.markdown(
            f"""
            <div class="activity-map-card">
                <div>
                    <span class="coach-pill">Google Maps</span>
                    <h3>Route polyline needs GOOGLE_MAPS_API_KEY</h3>
                    <p style="color:{muted_color}; max-width:640px;">
                        Set GOOGLE_MAPS_API_KEY in .env to draw the exact GPS route on Google Maps.
                        Add GOOGLE_MAPS_MAP_ID for the best vector-based 3D tilt. The embedded map below is centered on the activity start.
                    </p>
                    <p><a href="{directions_url}" target="_blank">Open start-to-finish route in Google Maps</a></p>
                </div>
                <iframe
                    width="100%"
                    height="260"
                    style="border:0; border-radius:18px;"
                    loading="lazy"
                    referrerpolicy="no-referrer-when-downgrade"
                    src="https://maps.google.com/maps?q={query}&z=14&output=embed">
                </iframe>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    points_json = json.dumps(points)
    api_key_json = json.dumps(api_key)
    map_id_json = json.dumps(map_id)
    center_json = json.dumps(center)
    route_heading_json = json.dumps(route_heading)
    title_json = json.dumps(activity_title)
    component_id = f"activity-google-map-{abs(hash(points_json))}"
    progress_id = f"activity-progress-{abs(hash(points_json))}"
    replay_id = f"activity-replay-{abs(hash(points_json))}"
    export_id = f"activity-export-{abs(hash(points_json))}"
    status_id = f"activity-export-status-{abs(hash(points_json))}"
    init_name = f"initActivityMap{abs(hash(points_json))}"
    html(
        f"""
        <div style="position:relative;height:460px;width:100%;border-radius:26px;overflow:hidden;">
          <div id="{component_id}" style="height:100%;width:100%;"></div>
          <div style="
            position:absolute;
            left:16px;
            top:16px;
            z-index:20;
            padding:10px 13px;
            border-radius:16px;
            background:rgba(17,24,39,0.84);
            color:white;
            font-family:Manrope, sans-serif;
            box-shadow:0 12px 30px rgba(15,23,42,0.22);
          ">
            <div style="font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:#fed7aa;">3D routes</div>
            <div style="font-size:13px;font-weight:800;">Tilted satellite replay</div>
          </div>
          <div style="
            position:absolute;
            left:16px;
            bottom:16px;
            z-index:30;
            display:flex;
            align-items:center;
            gap:10px;
            padding:10px 12px;
            border-radius:999px;
            background:rgba(17,24,39,0.88);
            color:white;
            font-family:Manrope, sans-serif;
            box-shadow:0 12px 30px rgba(15,23,42,0.24);
          ">
            <button id="{replay_id}" type="button" style="
              border:0;
              border-radius:999px;
              background:#fc4c02;
              color:white;
              font-weight:800;
              padding:8px 12px;
              cursor:pointer;
              pointer-events:auto;
            ">Replay</button>
            <button id="{export_id}" type="button" style="
              border:1px solid rgba(255,255,255,0.28);
              border-radius:999px;
              background:rgba(255,255,255,0.12);
              color:white;
              font-weight:800;
              padding:8px 12px;
              cursor:pointer;
              pointer-events:auto;
            ">Export video</button>
            <div style="width:160px;height:6px;border-radius:999px;background:rgba(255,255,255,0.22);overflow:hidden;">
              <div id="{progress_id}" style="height:100%;width:0%;background:#fc4c02;border-radius:999px;"></div>
            </div>
          </div>
          <div id="{status_id}" style="
            position:absolute;
            right:16px;
            bottom:20px;
            z-index:30;
            max-width:260px;
            color:white;
            background:rgba(17,24,39,0.82);
            border-radius:14px;
            padding:8px 10px;
            font-family:Manrope, sans-serif;
            font-size:12px;
            display:none;
          "></div>
        </div>
        <script>
          const routePoints = {points_json};
          const mapCenter = {center_json};
          const mapId = {map_id_json};
          const routeHeading = {route_heading_json};
          const routeTitle = {title_json};
          let animationFrame = null;

          window.{init_name} = function() {{
            const mapOptions = {{
              zoom: 14,
              center: mapCenter,
              mapTypeId: "hybrid",
              tilt: 67.5,
              heading: routeHeading,
              disableDefaultUI: false,
              streetViewControl: false,
              fullscreenControl: true,
              mapTypeControl: true,
              rotateControl: true,
              scaleControl: true,
              gestureHandling: "greedy"
            }};
            if (mapId) {{
              mapOptions.mapId = mapId;
            }}
            if (google.maps.RenderingType) {{
              mapOptions.renderingType = google.maps.RenderingType.VECTOR;
            }}

            const map = new google.maps.Map(document.getElementById("{component_id}"), mapOptions);

            const bounds = new google.maps.LatLngBounds();
            routePoints.forEach((point) => bounds.extend(point));

            new google.maps.Polyline({{
              path: routePoints,
              geodesic: true,
              strokeColor: "#111827",
              strokeOpacity: 0.45,
              strokeWeight: 13,
              map
            }});

            new google.maps.Polyline({{
              path: routePoints,
              geodesic: true,
              strokeColor: "#ffffff",
              strokeOpacity: 0.78,
              strokeWeight: 9,
              map
            }});

            const progressRoute = new google.maps.Polyline({{
              path: [routePoints[0]],
              geodesic: true,
              strokeColor: "#fc4c02",
              strokeOpacity: 1,
              strokeWeight: 6,
              map
            }});

            new google.maps.Marker({{
              position: routePoints[0],
              map,
              label: "S",
              title: "Start"
            }});

            new google.maps.Marker({{
              position: routePoints[routePoints.length - 1],
              map,
              label: "F",
              title: "Finish"
            }});

            const runnerMarker = new google.maps.Marker({{
              position: routePoints[0],
              map,
              title: "Current position",
              icon: {{
                path: google.maps.SymbolPath.CIRCLE,
                scale: 8,
                fillColor: "#fc4c02",
                fillOpacity: 1,
                strokeColor: "#ffffff",
                strokeWeight: 3
              }}
            }});

            const progressBar = document.getElementById("{progress_id}");
            const replayButton = document.getElementById("{replay_id}");
            const exportButton = document.getElementById("{export_id}");
            const exportStatus = document.getElementById("{status_id}");
            const durationMs = Math.min(Math.max(routePoints.length * 22, 4500), 14000);

            function interpolate(start, end, fraction) {{
              return {{
                lat: start.lat + (end.lat - start.lat) * fraction,
                lng: start.lng + (end.lng - start.lng) * fraction
              }};
            }}

            function animateRoute() {{
              if (animationFrame) {{
                cancelAnimationFrame(animationFrame);
              }}
              const startedAt = performance.now();
              progressRoute.setPath([routePoints[0]]);
              runnerMarker.setPosition(routePoints[0]);
              progressBar.style.width = "0%";

              function step(now) {{
                const progress = Math.min((now - startedAt) / durationMs, 1);
                const scaledIndex = progress * (routePoints.length - 1);
                const baseIndex = Math.floor(scaledIndex);
                const nextIndex = Math.min(baseIndex + 1, routePoints.length - 1);
                const pointFraction = scaledIndex - baseIndex;
                const currentPoint = interpolate(routePoints[baseIndex], routePoints[nextIndex], pointFraction);
                const visiblePath = routePoints.slice(0, baseIndex + 1).concat([currentPoint]);

                runnerMarker.setPosition(currentPoint);
                progressRoute.setPath(visiblePath);
                progressBar.style.width = `${{Math.round(progress * 100)}}%`;

                if (progress < 1) {{
                  animationFrame = requestAnimationFrame(step);
                }}
              }}

              animationFrame = requestAnimationFrame(step);
            }}

            replayButton.addEventListener("click", (event) => {{
              event.preventDefault();
              event.stopPropagation();
              animateRoute();
            }});
            exportButton.addEventListener("click", (event) => {{
              event.preventDefault();
              event.stopPropagation();
              exportRouteVideo();
            }});

            function showExportStatus(message) {{
              exportStatus.style.display = "block";
              exportStatus.textContent = message;
            }}

            function exportRouteVideo() {{
              const canvas = document.createElement("canvas");
              canvas.width = 1080;
              canvas.height = 1920;
              const ctx = canvas.getContext("2d");
              if (!canvas.captureStream || !window.MediaRecorder) {{
                showExportStatus("This browser cannot export canvas video. Use Chrome or Edge.");
                return;
              }}

              function mercatorY(lat) {{
                const rad = lat * Math.PI / 180;
                return Math.log(Math.tan(Math.PI / 4 + rad / 2));
              }}

              const projectedSource = routePoints.map((point) => ({{
                x: point.lng,
                y: mercatorY(point.lat),
                distance: point.distance,
                elevation: point.elevation
              }}));
              const xValues = projectedSource.map((point) => point.x);
              const yValues = projectedSource.map((point) => point.y);
              const minX = Math.min(...xValues);
              const maxX = Math.max(...xValues);
              const minY = Math.min(...yValues);
              const maxY = Math.max(...yValues);
              const padding = 120;
              const routeWidth = Math.max(maxX - minX, 0.00001);
              const routeHeight = Math.max(maxY - minY, 0.00001);
              const scale = Math.min((canvas.width - padding * 2) / routeWidth, (canvas.height - 520) / routeHeight);
              const offsetX = (canvas.width - routeWidth * scale) / 2;
              const offsetY = 290 + (canvas.height - 520 - routeHeight * scale) / 2;
              const projected = projectedSource.map((point) => ({{
                x: offsetX + (point.x - minX) * scale,
                y: offsetY + (maxY - point.y) * scale
              }}));
              const exportDurationMs = 9000;

              function drawBackground() {{
                const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
                gradient.addColorStop(0, "#f8fafc");
                gradient.addColorStop(0.48, "#e2e8f0");
                gradient.addColorStop(1, "#cbd5e1");
                ctx.fillStyle = gradient;
                ctx.fillRect(0, 0, canvas.width, canvas.height);

                ctx.strokeStyle = "rgba(100,116,139,.22)";
                ctx.lineWidth = 3;
                for (let x = -canvas.height; x <= canvas.width + canvas.height; x += 120) {{
                  ctx.beginPath();
                  ctx.moveTo(x, 470);
                  ctx.lineTo(x + canvas.height * 0.55, canvas.height);
                  ctx.stroke();
                }}
                ctx.strokeStyle = "rgba(255,255,255,.72)";
                ctx.lineWidth = 8;
                for (let y = 560; y <= canvas.height; y += 180) {{
                  ctx.beginPath();
                  ctx.moveTo(0, y);
                  ctx.lineTo(canvas.width, y);
                  ctx.stroke();
                }}

                ctx.strokeStyle = "rgba(15,23,42,.08)";
                ctx.lineWidth = 2;
                for (let x = 0; x <= canvas.width; x += 90) {{
                  ctx.beginPath();
                  ctx.moveTo(x, 500);
                  ctx.lineTo(x, canvas.height);
                  ctx.stroke();
                }}
              }}

              function drawText(progress) {{
                const distanceValues = routePoints.map((point) => point.distance).filter((value) => value !== null);
                const totalDistance = distanceValues.length ? Math.max(...distanceValues) : 0;
                ctx.fillStyle = "#fc4c02";
                ctx.font = "900 34px Arial, sans-serif";
                ctx.fillText("MARATHON COACH", 76, 120);
                ctx.fillStyle = "#111827";
                ctx.font = "900 68px Arial, sans-serif";
                const safeTitle = routeTitle.length > 52 ? routeTitle.slice(0, 52) : routeTitle;
                const lines = safeTitle.length > 26 ? [safeTitle.slice(0, 26), safeTitle.slice(26)] : [safeTitle];
                lines.forEach((line, index) => ctx.fillText(line.trim(), 76, 205 + index * 78));
                ctx.fillStyle = "rgba(15,23,42,.66)";
                ctx.font = "700 34px Arial, sans-serif";
                ctx.fillText(`${{Math.round(progress * 100)}}% replayed`, 76, 382);
                if (totalDistance > 0) {{
                  ctx.fillText(`${{totalDistance.toFixed(2)}} km route`, 76, 432);
                }}
              }}

              function drawRoute(progress) {{
                ctx.lineCap = "round";
                ctx.lineJoin = "round";

                ctx.strokeStyle = "rgba(15,23,42,.18)";
                ctx.lineWidth = 46;
                ctx.beginPath();
                projected.forEach((point, index) => {{
                  if (index === 0) ctx.moveTo(point.x, point.y);
                  else ctx.lineTo(point.x, point.y);
                }});
                ctx.stroke();

                ctx.strokeStyle = "#ffffff";
                ctx.lineWidth = 34;
                ctx.beginPath();
                projected.forEach((point, index) => {{
                  if (index === 0) ctx.moveTo(point.x, point.y);
                  else ctx.lineTo(point.x, point.y);
                }});
                ctx.stroke();

                ctx.strokeStyle = "rgba(15,23,42,.36)";
                ctx.lineWidth = 18;
                ctx.beginPath();
                projected.forEach((point, index) => {{
                  if (index === 0) ctx.moveTo(point.x, point.y);
                  else ctx.lineTo(point.x, point.y);
                }});
                ctx.stroke();

                const visibleCount = Math.max(2, Math.floor(progress * (projected.length - 1)) + 1);
                ctx.strokeStyle = "#fc4c02";
                ctx.lineWidth = 22;
                ctx.beginPath();
                projected.slice(0, visibleCount).forEach((point, index) => {{
                  if (index === 0) ctx.moveTo(point.x, point.y);
                  else ctx.lineTo(point.x, point.y);
                }});
                ctx.stroke();

                const startPoint = projected[0];
                const finishPoint = projected[projected.length - 1];
                ctx.fillStyle = "#16a34a";
                ctx.beginPath();
                ctx.arc(startPoint.x, startPoint.y, 24, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = "#111827";
                ctx.beginPath();
                ctx.arc(finishPoint.x, finishPoint.y, 24, 0, Math.PI * 2);
                ctx.fill();

                const runner = projected[Math.min(visibleCount - 1, projected.length - 1)];
                ctx.fillStyle = "#ffffff";
                ctx.beginPath();
                ctx.arc(runner.x, runner.y, 28, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = "#fc4c02";
                ctx.beginPath();
                ctx.arc(runner.x, runner.y, 18, 0, Math.PI * 2);
                ctx.fill();
              }}

              function drawFrame(progress) {{
                drawBackground();
                drawText(progress);
                drawRoute(progress);
              }}

              exportButton.disabled = true;
              exportButton.textContent = "Recording...";
              showExportStatus("Recording social video from route data...");
              const chunks = [];
              const stream = canvas.captureStream(30);
              const preferredType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
                ? "video/webm;codecs=vp9"
                : "video/webm";
              const recorder = new MediaRecorder(stream, {{ mimeType: preferredType }});
              recorder.ondataavailable = (event) => {{
                if (event.data.size > 0) chunks.push(event.data);
              }};
              recorder.onstop = () => {{
                const blob = new Blob(chunks, {{ type: "video/webm" }});
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = url;
                link.download = "route-animation.webm";
                link.click();
                URL.revokeObjectURL(url);
                exportButton.disabled = false;
                exportButton.textContent = "Export video";
                showExportStatus("Export complete. The clip uses route data only, not Google map tiles.");
              }};
              recorder.start();
              drawFrame(0);
              const startedAt = performance.now();

              function tick(now) {{
                const progress = Math.min((now - startedAt) / exportDurationMs, 1);
                drawFrame(progress);
                if (progress < 1) {{
                  requestAnimationFrame(tick);
                }} else {{
                  window.setTimeout(() => recorder.stop(), 300);
                }}
              }}

              requestAnimationFrame(tick);
            }}

            map.fitBounds(bounds);
            google.maps.event.addListenerOnce(map, "idle", () => {{
              map.setTilt(67.5);
              map.setHeading(routeHeading);
              window.setTimeout(animateRoute, 500);
            }});
          }};

          if (window.google && window.google.maps) {{
            window.{init_name}();
          }} else {{
            const script = document.createElement("script");
            script.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent({api_key_json}) + "&callback={init_name}";
            script.async = true;
            script.defer = true;
            document.head.appendChild(script);
          }}
        </script>
        """,
        height=486,
    )
