import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

function RouteMap({ geometry, label }) {
  const container = useRef(null);

  useEffect(() => {
    const map = L.map(container.current, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>',
    }).addTo(map);
    const route = L.geoJSON(geometry, { style: { className: "map-route", interactive: false } });
    map.fitBounds(route.getBounds(), { padding: [34, 34], maxZoom: 16 });
    route.addTo(map);
    const [start, end] = [geometry.coordinates[0], geometry.coordinates.at(-1)];
    for (const [point, marker, kind, direction] of [[start, "A", "start", "left"], [end, "B", "end", "right"]]) {
      L.circleMarker(L.GeoJSON.coordsToLatLng(point), { radius: 5, className: `map-pin ${kind}` })
        .addTo(map)
        .bindTooltip(marker, { permanent: true, direction, offset: [direction === "left" ? -6 : 6, 0] });
    }

    const resize = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resize.observe(container.current);
    return () => {
      resize.disconnect();
      map.remove();
    };
  }, [geometry]);

  return <div ref={container} className="map-view" role="region" aria-label={label} />;
}

export default function MapsPanel({ result, claimText, fresh }) {
  const flagged = result.exceeds_tolerance;
  const fallback = result.source === "straight_line_fallback";
  const hasClaimedTime = result.claimed_minutes !== undefined;
  const verdict = fallback ? "Estimate only" : !hasClaimedTime ? "Route estimate" :
    flagged ? "Not possible in claimed time" : "Plausible";
  return (
    <article className={`maps-panel ${flagged ? "flagged" : ""} ${fresh ? "fresh" : ""}`}>
      <header>
        <span className="eyebrow">Maps check</span>
        <span className={`map-verdict ${flagged && !fallback ? "bad" : ""}`}>{verdict}</span>
      </header>
      {result.route_geometry ? (
        <RouteMap geometry={result.route_geometry}
          label={`Route from ${result.origin} to ${result.destination}, ${result.distance_km} km`} />
      ) : (
        <div className="map-view map-unavailable muted small">
          {fallback ? "Road route unavailable. Showing a straight-line estimate." : "Route map unavailable for this check."}
        </div>
      )}
      <dl className="map-facts">
        <div className="span-2"><dt>A</dt><dd>{result.origin_matched || result.origin}</dd></div>
        <div className="span-2"><dt>B</dt><dd>{result.destination_matched || result.destination}</dd></div>
        <div><dt>Distance</dt><dd>{result.distance_km} km</dd></div>
        <div><dt>Estimated</dt><dd>{result.actual_minutes} min</dd></div>
        {hasClaimedTime && <div><dt>Claimed</dt><dd>{result.claimed_minutes} min</dd></div>}
        {result.gap_minutes !== undefined && (
          <div><dt>Gap</dt><dd className={flagged ? "bad" : ""}>{result.gap_minutes > 0 ? "+" : ""}{result.gap_minutes} min</dd></div>
        )}
      </dl>
      <p className="muted small">{claimText}{result.assumed_speed_kmh ? ` · assumes ${result.assumed_speed_kmh} km/h in town` : ""}</p>
    </article>
  );
}
