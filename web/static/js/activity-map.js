(() => {
  const element = document.getElementById("activity-route-map");
  if (!element) return;

  const routeData = JSON.parse(element.dataset.route || "[]");
  const points = Array.isArray(routeData)
    ? routeData.filter((point) => Number.isFinite(point?.lat) && Number.isFinite(point?.lng))
    : [];
  const button = document.getElementById("activity-route-replay");
  const progress = document.getElementById("activity-route-progress");
  const status = document.getElementById("activity-route-status");
  let runner;
  let progressLine;
  let frame;
  let map;
  let replayToken = 0;

  function fail(message) {
    if (status) status.textContent = message;
    element.setAttribute("aria-label", message);
    if (button) button.hidden = true;
  }

  function replay() {
    if (points.length < 2 || !progressLine || !runner) return;
    const token = ++replayToken;
    if (frame) cancelAnimationFrame(frame);
    const duration = Math.min(Math.max(points.length * 22, 4500), 14000);
    const start = performance.now();
    progressLine.setPath([points[0]]);
    runner.setPosition(points[0]);

    function tick(now) {
      if (token !== replayToken) return;
      const fraction = Math.max(0, Math.min((now - start) / duration, 1));
      const lastIndex = points.length - 1;
      const scaled = Math.min(fraction * lastIndex, lastIndex);
      const index = Math.min(Math.floor(scaled), lastIndex);
      const next = Math.min(index + 1, lastIndex);
      const from = points[index] ?? points[lastIndex];
      const to = points[next] ?? from;
      if (!from || !to) {
        replayToken += 1;
        fail("The GPS route could not be replayed.");
        return;
      }
      const part = scaled - index;
      const current = {
        lat: from.lat + (to.lat - from.lat) * part,
        lng: from.lng + (to.lng - from.lng) * part,
      };
      progressLine.setPath(points.slice(0, index + 1).concat(current));
      runner.setPosition(current);
      progress.value = Math.round(fraction * 100);
      if (fraction < 1) frame = requestAnimationFrame(tick);
      else frame = null;
    }

    frame = requestAnimationFrame(tick);
  }

  function createOverlay(position, label, kind) {
    class RouteMarker extends google.maps.OverlayView {
      constructor() {
        super();
        this.position = new google.maps.LatLng(position);
        this.element = document.createElement("span");
        this.element.className = `v2-route-pin v2-route-overlay-pin v2-route-pin-${kind}`;
        this.element.textContent = label;
        this.setMap(map);
      }

      onAdd() {
        this.getPanes().overlayMouseTarget.appendChild(this.element);
      }

      draw() {
        const pixel = this.getProjection().fromLatLngToDivPixel(this.position);
        if (!pixel) return;
        this.element.style.left = `${pixel.x}px`;
        this.element.style.top = `${pixel.y}px`;
      }

      onRemove() {
        this.element.remove();
      }

      setPosition(nextPosition) {
        this.position = new google.maps.LatLng(nextPosition);
        this.draw();
      }
    }
    return new RouteMarker();
  }

  function createAdvancedMarker(AdvancedMarkerElement, position, label, kind, title) {
    const content = document.createElement("span");
    content.className = `v2-route-pin v2-route-pin-${kind}`;
    content.textContent = label;
    const marker = new AdvancedMarkerElement({
      map, position, title, anchorLeft: "-50%", anchorTop: "-50%",
    });
    marker.append(content);
    return {
      setPosition(nextPosition) {
        marker.position = nextPosition;
      },
    };
  }

  window.initActivityRouteMap = async () => {
    if (!window.google?.maps || points.length < 2) {
      fail("The route map could not be loaded.");
      return;
    }
    const mapOptions = {
      mapTypeId: "hybrid",
      renderingType: google.maps.RenderingType.VECTOR,
      streetViewControl: false,
      fullscreenControl: true,
      gestureHandling: "greedy",
      mapTypeControl: true,
    };
    if (element.dataset.mapId) mapOptions.mapId = element.dataset.mapId;
    map = new google.maps.Map(element, mapOptions);
    const bounds = new google.maps.LatLngBounds();
    points.forEach((point) => bounds.extend(point));
    map.fitBounds(bounds);

    new google.maps.Polyline({
      path: points,
      geodesic: true,
      strokeColor: "#ffffff",
      strokeOpacity: 0.85,
      strokeWeight: 6,
      map,
    });
    progressLine = new google.maps.Polyline({
      path: [points[0]],
      geodesic: true,
      strokeColor: "#fc4c02",
      strokeOpacity: 1,
      strokeWeight: 5,
      map,
    });
    if (element.dataset.mapId) {
      const {AdvancedMarkerElement} = await google.maps.importLibrary("marker");
      createAdvancedMarker(AdvancedMarkerElement, points[0], "S", "start", "Start");
      createAdvancedMarker(AdvancedMarkerElement, points.at(-1), "F", "finish", "Finish");
      runner = createAdvancedMarker(AdvancedMarkerElement, points[0], "", "runner", "Runner position");
    } else {
      createOverlay(points[0], "S", "start");
      createOverlay(points.at(-1), "F", "finish");
      runner = createOverlay(points[0], "", "runner");
    }

    button.disabled = false;
    button.textContent = "Replay route";
    button.addEventListener("click", replay);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      progressLine.setPath(points);
      runner.setPosition(points.at(-1));
      progress.value = 100;
    } else {
      google.maps.event.addListenerOnce(map, "idle", () => {
        replay();
      });
    }
    element.setAttribute("aria-label", "Run route map loaded. Use Replay route to animate the recorded GPS path.");
  };

  const script = document.createElement("script");
  script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(element.dataset.apiKey)}&callback=initActivityRouteMap&loading=async`;
  script.async = true;
  script.onerror = () => fail("Google Maps could not be reached. Check your connection or map key.");
  document.head.appendChild(script);
})();
