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
) -> None:
    """Render the activity route as a Google Maps 3D-style hybrid map."""

    route = track_points.dropna(subset=["latitude", "longitude"]).copy()
    if route.empty:
        st.info("No GPS coordinates are stored for this activity yet.")
        return

    route = downsample_route(route)
    points = [{"lat": float(row.latitude), "lng": float(row.longitude)} for row in route.itertuples()]
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
    html(
        f"""
        <div style="position:relative;height:460px;width:100%;border-radius:26px;overflow:hidden;">
          <div id="activity-google-map" style="height:100%;width:100%;"></div>
          <div style="
            position:absolute;
            left:16px;
            top:16px;
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
            <button id="activity-replay" style="
              border:0;
              border-radius:999px;
              background:#fc4c02;
              color:white;
              font-weight:800;
              padding:8px 12px;
              cursor:pointer;
            ">Replay</button>
            <div style="width:160px;height:6px;border-radius:999px;background:rgba(255,255,255,0.22);overflow:hidden;">
              <div id="activity-progress" style="height:100%;width:0%;background:#fc4c02;border-radius:999px;"></div>
            </div>
          </div>
        </div>
        <script>
          const routePoints = {points_json};
          const mapCenter = {center_json};
          const mapId = {map_id_json};
          const routeHeading = {route_heading_json};
          let animationFrame = null;

          function initActivityMap() {{
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

            const map = new google.maps.Map(document.getElementById("activity-google-map"), mapOptions);

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

            const progressBar = document.getElementById("activity-progress");
            const replayButton = document.getElementById("activity-replay");
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

            replayButton.addEventListener("click", animateRoute);
            map.fitBounds(bounds);
            google.maps.event.addListenerOnce(map, "idle", () => {{
              map.setTilt(67.5);
              map.setHeading(routeHeading);
              window.setTimeout(animateRoute, 500);
            }});
          }}

          const script = document.createElement("script");
          script.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent({api_key_json}) + "&callback=initActivityMap";
          script.async = true;
          script.defer = true;
          document.head.appendChild(script);
        </script>
        """,
        height=450,
    )
