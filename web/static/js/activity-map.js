(() => {
  const element = document.getElementById("activity-route-map");
  if (!element) return;

  const points = JSON.parse(element.dataset.route || "[]");
  const button = document.getElementById("activity-route-replay");
  const progress = document.getElementById("activity-route-progress");
  const status = document.getElementById("activity-route-status");
  let runner;
  let progressLine;
  let frame;

  function fail(message) {
    if (status) status.textContent = message;
    element.setAttribute("aria-label", message);
    if (button) button.hidden = true;
  }

  function replay() {
    if (frame) cancelAnimationFrame(frame);
    const duration = Math.min(Math.max(points.length * 22, 4500), 14000);
    const start = performance.now();
    progressLine.setPath([points[0]]);
    runner.setPosition(points[0]);

    function tick(now) {
      const fraction = Math.min((now - start) / duration, 1);
      const scaled = fraction * (points.length - 1);
      const index = Math.floor(scaled);
      const next = Math.min(index + 1, points.length - 1);
      const part = scaled - index;
      const current = {
        lat: points[index].lat + (points[next].lat - points[index].lat) * part,
        lng: points[index].lng + (points[next].lng - points[index].lng) * part,
      };
      progressLine.setPath(points.slice(0, index + 1).concat(current));
      runner.setPosition(current);
      progress.value = Math.round(fraction * 100);
      if (fraction < 1) frame = requestAnimationFrame(tick);
    }

    frame = requestAnimationFrame(tick);
  }

  window.initActivityRouteMap = () => {
    if (!window.google?.maps || points.length < 2) {
      fail("The route map could not be loaded.");
      return;
    }
    const map = new google.maps.Map(element, {
      mapTypeId: "hybrid",
      tilt: 45,
      mapId: element.dataset.mapId || undefined,
      streetViewControl: false,
      fullscreenControl: true,
      gestureHandling: "greedy",
      mapTypeControl: true,
    });
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
    new google.maps.Marker({ position: points[0], map, label: "S", title: "Start" });
    new google.maps.Marker({ position: points.at(-1), map, label: "F", title: "Finish" });
    runner = new google.maps.Marker({
      position: points[0],
      map,
      title: "Runner position",
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 7,
        fillColor: "#fc4c02",
        fillOpacity: 1,
        strokeColor: "#ffffff",
        strokeWeight: 2,
      },
    });

    button.disabled = false;
    button.textContent = "Replay route";
    button.addEventListener("click", replay);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      progressLine.setPath(points);
      runner.setPosition(points.at(-1));
      progress.value = 100;
    } else {
      google.maps.event.addListenerOnce(map, "idle", replay);
    }
    element.setAttribute("aria-label", "Run route map loaded. Use Replay route to animate the recorded GPS path.");
  };

  const script = document.createElement("script");
  script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(element.dataset.apiKey)}&callback=initActivityRouteMap&loading=async`;
  script.async = true;
  script.onerror = () => fail("Google Maps could not be reached. Check your connection or map key.");
  document.head.appendChild(script);
})();
