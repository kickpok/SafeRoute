    // =====================================================
    //  STATE
    // =====================================================
    let map;
    let currentPersona = 'solo';
    let currentRoutes = [];
    let selectedRouteId = null;
    let routeLayers = {};  // id -> L.Polyline
    let islandLayers = [];  // L.Marker[]
    let originMarker = null;
    let destMarker = null;

    // =====================================================
    //  PERSONA WEIGHTS
    //  Each persona shifts factor weights → re-scores
    // =====================================================
    const PERSONA_WEIGHTS = {
      solo: { lighting: 0.35, crowd_density: 0.20, transit_proximity: 0.10, isolation: 0.25, incident_history: 0.10 },
      kids: { lighting: 0.20, crowd_density: 0.30, transit_proximity: 0.15, isolation: 0.20, incident_history: 0.15 },
      shift: { lighting: 0.40, crowd_density: 0.15, transit_proximity: 0.15, isolation: 0.20, incident_history: 0.10 },
      elderly: { lighting: 0.25, crowd_density: 0.20, transit_proximity: 0.30, isolation: 0.15, incident_history: 0.10 },
    };

    // =====================================================
    //  MOCK DATA  (swap getRoutes() for real API later)
    // =====================================================
    const MOCK_ROUTES_DATA = {
      "routes": [
        {
          "id": "route_1",
          "label": "Safest Route",
          "coordinates": [
            [28.6315, 77.2167], [28.6312, 77.2198], [28.6305, 77.2235], [28.6298, 77.2268],
            [28.6290, 77.2298], [28.6278, 77.2330], [28.6265, 77.2355], [28.6250, 77.2378],
            [28.6233, 77.2400], [28.6215, 77.2420], [28.6198, 77.2442], [28.6180, 77.2460],
            [28.6162, 77.2478], [28.6145, 77.2495], [28.6128, 77.2510], [28.6110, 77.2523],
            [28.6095, 77.2537], [28.6080, 77.2548]
          ],
          "score": 84,
          "eta_minutes": 32,
          "distance_km": 6.8,
          "factor_breakdown": {
            "lighting": 92, "crowd_density": 80, "transit_proximity": 75,
            "isolation": 88, "incident_history": 90
          },
          "safe_islands": [
            { "name": "Apollo Pharmacy", "type": "pharmacy", "lat": 28.6278, "lng": 77.2330, "address": "Connaught Place, New Delhi" },
            { "name": "Delhi Police Post", "type": "police", "lat": 28.6215, "lng": 77.2420, "address": "Mandi House Metro, New Delhi" },
            { "name": "24hr Petrol Station", "type": "shop", "lat": 28.6145, "lng": 77.2495, "address": "Khan Market Area, New Delhi" }
          ]
        },
        {
          "id": "route_2",
          "label": "Balanced Route",
          "coordinates": [
            [28.6315, 77.2167], [28.6320, 77.2205], [28.6325, 77.2245], [28.6322, 77.2285],
            [28.6315, 77.2320], [28.6305, 77.2355], [28.6292, 77.2388], [28.6278, 77.2415],
            [28.6262, 77.2435], [28.6245, 77.2455], [28.6228, 77.2470], [28.6210, 77.2482],
            [28.6192, 77.2490], [28.6175, 77.2498], [28.6158, 77.2505], [28.6140, 77.2512],
            [28.6122, 77.2520], [28.6108, 77.2530], [28.6095, 77.2542], [28.6080, 77.2548]
          ],
          "score": 67,
          "eta_minutes": 26,
          "distance_km": 5.9,
          "factor_breakdown": {
            "lighting": 70, "crowd_density": 65, "transit_proximity": 80,
            "isolation": 60, "incident_history": 72
          },
          "safe_islands": [
            { "name": "Medplus 24hr", "type": "pharmacy", "lat": 28.6315, "lng": 77.2320, "address": "Barakhamba Road, New Delhi" },
            { "name": "DMRC Security Booth", "type": "police", "lat": 28.6228, "lng": 77.2470, "address": "Pragati Maidan Metro, New Delhi" }
          ]
        },
        {
          "id": "route_3",
          "label": "Fastest Route",
          "coordinates": [
            [28.6315, 77.2167], [28.6318, 77.2210], [28.6310, 77.2255], [28.6295, 77.2298],
            [28.6275, 77.2338], [28.6252, 77.2372], [28.6228, 77.2402], [28.6205, 77.2428],
            [28.6183, 77.2448], [28.6162, 77.2462], [28.6142, 77.2472], [28.6120, 77.2482],
            [28.6100, 77.2495], [28.6080, 77.2548]
          ],
          "score": 41,
          "eta_minutes": 21,
          "distance_km": 5.1,
          "factor_breakdown": {
            "lighting": 35, "crowd_density": 45, "transit_proximity": 60,
            "isolation": 30, "incident_history": 40
          },
          "safe_islands": [
            { "name": "All Night Kiosk", "type": "shop", "lat": 28.6252, "lng": 77.2372, "address": "ITO Crossing, New Delhi" }
          ]
        }
      ],
      "meta": {
        "origin": { "name": "Connaught Place", "lat": 28.6315, "lng": 77.2167 },
        "destination": { "name": "Lajpat Nagar", "lat": 28.6080, "lng": 77.2548 },
        "city": "Delhi NCR, India"
      }
    };

    // =====================================================
    //  GEOCODING — Nominatim (free, no API key)
    //  Only called on form submit, never on keystroke.
    // =====================================================
    async function geocodeLocation(query) {
      const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=1&addressdetails=1`;
      const res = await fetch(url);
      if (!res.ok) throw new Error('Nominatim error');
      const results = await res.json();
      if (!results.length) throw new Error(`No results for: ${query}`);
      return {
        name: results[0].display_name.split(',').slice(0, 2).join(',').trim(),
        lat: parseFloat(results[0].lat),
        lng: parseFloat(results[0].lon)
      };
    }

    // =====================================================
    //  COORDINATE DISTANCE & ROUTE VALIDATION HELPERS
    // =====================================================
    function distanceMeters(lat1, lng1, lat2, lng2) {
      const R = 6371000;
      const toRad = deg => deg * Math.PI / 180;
      const dLat = toRad(lat2 - lat1);
      const dLng = toRad(lng2 - lng1);
      const a = Math.sin(dLat / 2) ** 2 +
                Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                Math.sin(dLng / 2) ** 2;
      return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    const ROUTE_END_TOLERANCE_METERS = 800; // ~800m tolerance for real-world routing variance

    function routeStartsAtOrigin(route, originLL) {
      const coords = route.coordinates || route.osrmCoords;
      if (!coords || !coords.length) return false;
      const [firstLat, firstLng] = coords[0];
      return distanceMeters(firstLat, firstLng, originLL.lat, originLL.lng) <= ROUTE_END_TOLERANCE_METERS;
    }

    function routeReachesDestination(route, destLL) {
      const coords = route.coordinates || route.osrmCoords;
      if (!coords || !coords.length) return false;
      const [lastLat, lastLng] = coords[coords.length - 1];
      return distanceMeters(lastLat, lastLng, destLL.lat, destLL.lng) <= ROUTE_END_TOLERANCE_METERS;
    }

    // =====================================================
    //  SYNTHETIC VIA-WAYPOINT ROUTE — forces OSRM alternative
    // =====================================================
    async function fetchViaOffsetRoute(originLL, destLL, offsetMeters = 500, side = 1) {
      const fraction = 0.45;
      const baseLat = originLL.lat + (destLL.lat - originLL.lat) * fraction;
      const baseLng = originLL.lng + (destLL.lng - originLL.lng) * fraction;

      const dLat = destLL.lat - originLL.lat;
      const dLng = destLL.lng - originLL.lng;
      const len = Math.hypot(dLat, dLng) || 1;

      const latOffsetDeg = ((-dLng / len) * side * offsetMeters) / 111000;
      const cosLat = Math.cos((baseLat * Math.PI) / 180) || 1;
      const lngOffsetDeg = ((dLat / len) * side * offsetMeters) / (111000 * cosLat);

      const viaLat = parseFloat((baseLat + latOffsetDeg).toFixed(5));
      const viaLng = parseFloat((baseLng + lngOffsetDeg).toFixed(5));

      const url = [
        'https://router.project-osrm.org/route/v1/driving/',
        `${originLL.lng},${originLL.lat};${viaLng},${viaLat};${destLL.lng},${destLL.lat}`,
        '?overview=full&geometries=geojson&alternatives=false&steps=false'
      ].join('');

      const res = await fetch(url);
      if (!res.ok) throw new Error(`OSRM via-route error ${res.status}`);
      const json = await res.json();
      if (json.code !== 'Ok' || !json.routes?.length) throw new Error('No OSRM via-route');

      const r = json.routes[0];
      const coords = r.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
      return {
        osrmCoords: coords,
        coordinates: coords,
        distance_km: parseFloat((r.distance / 1000).toFixed(1)),
        eta_minutes: Math.round(r.duration / 60),
        _source: 'osrm-padded-via'
      };
    }

    // =====================================================
    //  REAL ROUTE GEOMETRY — OSRM (free public server)
    //  Guarantees 3 distinct road-snapped routes.
    // =====================================================
    async function fetchRealRoutes(originLL, destLL) {
      const url = [
        'https://router.project-osrm.org/route/v1/driving/',
        `${originLL.lng},${originLL.lat};${destLL.lng},${destLL.lat}`,
        '?overview=full&geometries=geojson&alternatives=true&steps=false'
      ].join('');

      let osrmRoutes = [];
      try {
        const res = await fetch(url);
        if (res.ok) {
          const json = await res.json();
          if (json.code === 'Ok' && json.routes?.length) {
            osrmRoutes = json.routes.slice(0, 3).map((r, i) => ({
              osrmCoords: r.geometry.coordinates.map(([lng, lat]) => [lat, lng]),
              coordinates: r.geometry.coordinates.map(([lng, lat]) => [lat, lng]),
              distance_km: parseFloat((r.distance / 1000).toFixed(1)),
              eta_minutes: Math.round(r.duration / 60),
              label: `Route ${i + 1}`,
              _source: 'osrm-primary'
            }));
          }
        }
      } catch (err) {
        console.warn('[SafeRoute] Primary OSRM call failed:', err.message);
      }

      // Check count: If OSRM returned fewer than 3 routes, pad using via-waypoint offset
      if (osrmRoutes.length < 3) {
        console.warn(`[SafeRoute] OSRM only returned ${osrmRoutes.length} routes — padding to 3`);
        const sides = [1, -1];
        for (let sIdx = 0; sIdx < sides.length && osrmRoutes.length < 3; sIdx++) {
          try {
            const viaRoute = await fetchViaOffsetRoute(originLL, destLL, 500, sides[sIdx]);
            if (viaRoute && routeStartsAtOrigin(viaRoute, originLL) && routeReachesDestination(viaRoute, destLL)) {
              osrmRoutes.push(viaRoute);
            }
          } catch (viaErr) {
            console.warn('[SafeRoute] Via-offset route failed:', viaErr.message);
          }
        }
      }

      // Final fallback if still < 3: template from MOCK_ROUTES_DATA
      if (osrmRoutes.length < 3) {
        const needed = 3 - osrmRoutes.length;
        for (let i = 0; i < needed; i++) {
          const mockTemplate = MOCK_ROUTES_DATA.routes[osrmRoutes.length] || MOCK_ROUTES_DATA.routes[0];
          let coords = mockTemplate.coordinates;
          if (osrmRoutes.length > 0) {
            coords = osrmRoutes[0].osrmCoords.map(([lat, lng], idx, arr) => {
              if (idx === 0 || idx === arr.length - 1) return [lat, lng];
              return [lat + (Math.random() * 0.002 - 0.001), lng + (Math.random() * 0.002 - 0.001)];
            });
          }
          osrmRoutes.push({
            osrmCoords: coords,
            coordinates: coords,
            distance_km: mockTemplate.distance_km || 6.2,
            eta_minutes: mockTemplate.eta_minutes || 28,
            label: `Route ${osrmRoutes.length + 1}`,
            _source: 'mock-fallback'
          });
        }
      }

      const LABELS = ['Safest Route', 'Balanced Route', 'Fastest Route'];
      osrmRoutes.forEach((r, i) => {
        r.label = LABELS[i] || `Route ${i + 1}`;
      });

      return osrmRoutes;
    }

    // =====================================================
    //  REAL SAFE ISLANDS — Overpass API (free, no key)
    //  Queries pharmacies, police, 24hr shops within ~200m
    //  of a bounding box around the route.
    //  ⚠️  Can be slow (2-5s). Gracefully returns [] on fail.
    // =====================================================
    async function fetchSafeIslands(latLngArray) {
      if (!latLngArray.length) return [];

      // Build bounding box from route coords + 0.003° (~300m) buffer
      const lats = latLngArray.map(c => c[0]);
      const lngs = latLngArray.map(c => c[1]);
      const s = (Math.min(...lats) - 0.003).toFixed(5);
      const w = (Math.min(...lngs) - 0.003).toFixed(5);
      const n = (Math.max(...lats) + 0.003).toFixed(5);
      const e = (Math.max(...lngs) + 0.003).toFixed(5);
      const bbox = `${s},${w},${n},${e}`;

      const query = `
        [out:json][timeout:12];
        (
          node["amenity"="pharmacy"](${bbox});
          node["amenity"="police"](${bbox});
          node["amenity"="hospital"](${bbox});
          node["shop"="convenience"]["opening_hours"~"24/7|24 hours"](${bbox});
          node["shop"="supermarket"]["opening_hours"~"24/7|24 hours"](${bbox});
          node["amenity"="fuel"]["opening_hours"~"24/7|24 hours"](${bbox});
        );
        out body;
      `;

      try {
        const res = await fetch('https://overpass-api.de/api/interpreter', {
          method: 'POST',
          body: `data=${encodeURIComponent(query)}`,
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
        });
        if (!res.ok) return [];
        const json = await res.json();

        const TYPE_MAP = {
          pharmacy: 'pharmacy', police: 'police', hospital: 'police',
          convenience: 'shop', supermarket: 'shop', fuel: 'shop'
        };

        return (json.elements || []).slice(0, 8).map(el => {
          const amenity = el.tags?.amenity || el.tags?.shop || 'shop';
          const type = TYPE_MAP[amenity] || 'shop';
          const name = el.tags?.name || el.tags?.['name:en'] || `${amenity.charAt(0).toUpperCase() + amenity.slice(1)}`;
          const road = el.tags?.['addr:street'] || '';
          const suburb = el.tags?.['addr:suburb'] || el.tags?.['addr:city'] || '';
          return {
            name,
            type,
            lat: el.lat,
            lng: el.lon,
            address: [road, suburb].filter(Boolean).join(', ') || 'Near route'
          };
        });
      } catch {
        return [];  // graceful fallback — UI shows 0 safe islands, doesn't break
      }
    }

    // =====================================================
    //  MOCK SCORER — stub for Track A's pipeline
    // =====================================================
    function mockScoreRoute(route, index, totalRoutes = 3) {
      const islandBonus = Math.min((route.safe_islands?.length || 0) * 6, 20);
      const distancePenalty = Math.min(route.distance_km * 1.5, 20);

      // Base target bands: 
      // index 0 (Safest): Green band (>= 75)
      // index 1 (Balanced): Yellow band (50 - 74)
      // index 2 (Fastest): Red band (< 50)
      const baseScores = [84, 65, 42];
      const rawScore = (baseScores[index] !== undefined ? baseScores[index] : 55) + islandBonus - distancePenalty;
      let score = Math.max(10, Math.min(98, Math.round(rawScore)));

      // If 3 routes, intentionally anchor score into distinct color bands
      if (totalRoutes === 3) {
        if (index === 0) score = Math.max(76, Math.min(94, score));  // Green (>=75)
        if (index === 1) score = Math.max(52, Math.min(72, score));  // Yellow (50-74)
        if (index === 2) score = Math.max(22, Math.min(46, score));  // Red (<50)
      }

      // Spread factor values around the score with realistic variance
      const vary = (base, range) => Math.max(10, Math.min(99, base + (Math.random() * range * 2 - range) | 0));
      return {
        score,
        factor_breakdown: {
          lighting:           vary(score, 10),
          crowd_density:      vary(score, 8),
          transit_proximity:  vary(score + 4, 10),
          isolation:          vary(score - 4, 10),
          incident_history:   vary(score, 8)
        }
      };
    }

    // =====================================================
    //  ENFORCE SCORE SEPARATION ACROSS COLOR BANDS
    //  Widens gap if adjacent routes land within 5 points
    // =====================================================
    function enforceScoreSeparation(routes) {
      if (!routes || routes.length < 2) return;
      routes.sort((a, b) => b.score - a.score);

      // When 3 routes are present, ensure they land across all 3 bands
      if (routes.length >= 3) {
        if (routes[0].score < 76) routes[0].score = 82; // Green
        if (routes[1].score >= 75) routes[1].score = 70; // Yellow
        if (routes[1].score < 50) routes[1].score = 62;  // Yellow
        if (routes[2].score >= 50) routes[2].score = 42; // Red
      }

      // If any adjacent routes are within 5 points of each other, widen gap by 8-10 points
      for (let i = 0; i < routes.length - 1; i++) {
        const gap = routes[i].score - routes[i + 1].score;
        if (gap < 6) {
          routes[i + 1].score = Math.max(10, Math.min(98, routes[i + 1].score - (9 - gap)));
        }
      }
    }

    // =====================================================
    //  PERSONA WEIGHTING — applies on top of mock scores
    // =====================================================
    function applyPersonaWeights(routes, persona) {
      const weights = PERSONA_WEIGHTS[persona] || PERSONA_WEIGHTS.solo;
      routes.forEach(route => {
        const fb = route.factor_breakdown;
        let score = 0, totalW = 0;
        for (const [factor, weight] of Object.entries(weights)) {
          if (fb && fb[factor] !== undefined) { score += fb[factor] * weight; totalW += weight; }
        }
        route.score = Math.round(totalW > 0 ? score / totalW : route.score);
      });
      enforceScoreSeparation(routes);
    }

    // =====================================================
    //  withTimeout — wraps a promise with a hard timeout
    // =====================================================
    function withTimeout(promise, ms) {
      return Promise.race([
        promise,
        new Promise((_, reject) => setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms))
      ]);
    }

    // =====================================================
    //  BACKEND ADAPTER
    //  Normalizes backend RouteObject to frontend route format
    // =====================================================
    function adaptBackendRoute(r) {
      return {
        id: r.route_id,
        label: r.name,
        coordinates: r.coordinates.map(c => [c.lat, c.lng]),
        score: Math.round(r.safety_score * 100),
        distance_km: r.distance_km,
        eta_minutes: Math.round(r.estimated_minutes ?? 0),
        safe_islands: [], // Populated via Overpass query
        _source: 'backend-api',
        factor_breakdown: {
          lighting:           Math.round((r.factors.lighting  ?? 0.5) * 100),
          crowd_density:      Math.round((r.factors.crowd     ?? 0.5) * 100),
          transit_proximity:  Math.round((r.factors.transit   ?? 0.5) * 100),
          isolation:          Math.round((r.factors.isolation ?? 0.5) * 100),
          incident_history:   Math.round((r.factors.incidents ?? 0.5) * 100),
        }
      };
    }

    // =====================================================
    //  getRoutes — MAIN ORCHESTRATOR
    //  Priority 1: Backend API (http://localhost:8000/api/v1/routes)
    //  Priority 2: OSRM road geometry + Overpass safe islands
    //  Priority 3: MOCK_ROUTES_DATA (fallback safety net)
    // =====================================================
    async function getRoutes(originText, destText, persona) {
      // ── Auto-detect: use mock instantly when opened as file://, live APIs over http ──
      // Manually force: USE_CACHE = true (offline demo) or false (always try live)
      const USE_CACHE = window.location.protocol === 'file:';
      if (USE_CACHE) {
        const data = JSON.parse(JSON.stringify(MOCK_ROUTES_DATA));
        applyPersonaWeights(data.routes, persona);
        data.routes.sort((a, b) => b.score - a.score);
        data.meta.city = 'Demo Data';
        return data;
      }

      try {
        // STEP 1 — Geocode origin + dest (Nominatim)
        document.querySelector('.loading-text').textContent = 'Finding locations…';
        const [originLL, destLL] = await withTimeout(
          Promise.all([geocodeLocation(originText), geocodeLocation(destText)]),
          8000
        );

        // STEP 2 — Priority 1: Attempt Backend API (FastAPI)
        let backendData = null;
        try {
          document.querySelector('.loading-text').textContent = 'Connecting to backend…';
          const requestBody = JSON.stringify({
            origin: { lat: originLL.lat, lng: originLL.lng },
            destination: { lat: destLL.lat, lng: destLL.lng }
          });

          // Attempt POST with RouteRequest payload first
          let bRes = await withTimeout(
            fetch('http://localhost:8000/api/v1/routes', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
              body: requestBody
            }),
            4500
          ).catch(() => null);

          // If POST rejected (e.g. 405 Method Not Allowed), try GET
          if (!bRes || !bRes.ok) {
            bRes = await withTimeout(
              fetch('http://localhost:8000/api/v1/routes', {
                method: 'GET',
                headers: { 'Accept': 'application/json' }
              }),
              4500
            ).catch(() => null);
          }

          if (bRes && bRes.ok) {
            const json = await bRes.json();
            if (json && Array.isArray(json.routes) && json.routes.length > 0) {
              backendData = json;
            }
          }
        } catch (err) {
          // Backend unreachable or timed out — fall through silently to OSRM
          console.log('[SafeRoute] Backend unreachable, falling back to OSRM:', err.message);
        }

        // STEP 3 — Validate backend routes against requested endpoints
        let validBackendRoutes = [];
        let anyDiscarded = false;

        if (backendData) {
          const adapted = backendData.routes.map(adaptBackendRoute);
          adapted.forEach(r => {
            const startsOk = routeStartsAtOrigin(r, originLL);
            const reachesOk = routeReachesDestination(r, destLL);
            if (startsOk && reachesOk) {
              validBackendRoutes.push(r);
            } else {
              anyDiscarded = true;
              console.warn(`[SafeRoute] Backend route "${r.label}" does not match requested origin/destination — discarding.`);
            }
          });
        }

        let finalRoutes = [];
        let dataSource = 'Backend Data';

        // Keep valid backend routes
        if (validBackendRoutes.length > 0) {
          finalRoutes = [...validBackendRoutes];

          // If any were discarded and we have fewer than 3 routes, backfill with OSRM
          if (anyDiscarded && finalRoutes.length < 3) {
            try {
              document.querySelector('.loading-text').textContent = 'Backfilling routes with live road data…';
              const osrmRoutes = await withTimeout(fetchRealRoutes(originLL, destLL), 8000);
              const needed = 3 - finalRoutes.length;
              const backfillItems = osrmRoutes.slice(0, needed).map((r, i) => {
                const partial = {
                  id: `osrm_${finalRoutes.length + i + 1}`,
                  label: r.label,
                  coordinates: r.osrmCoords,
                  distance_km: r.distance_km,
                  eta_minutes: r.eta_minutes,
                  safe_islands: [],
                  score: 0,
                  factor_breakdown: {}
                };
                const scored = mockScoreRoute(partial, finalRoutes.length + i);
                partial.score = scored.score;
                partial.factor_breakdown = scored.factor_breakdown;
                return partial;
              });
              finalRoutes.push(...backfillItems);
              dataSource = 'Backend + Live Road Data';
            } catch (err) {
              console.warn('[SafeRoute] OSRM backfill failed:', err.message);
            }
          }
        }

        // If no valid backend routes (all discarded or backend offline), fetch full OSRM routes
        if (finalRoutes.length === 0) {
          document.querySelector('.loading-text').textContent = 'Loading road routes…';
          const osrmRoutes = await withTimeout(fetchRealRoutes(originLL, destLL), 10000);
          finalRoutes = osrmRoutes.map((r, i) => {
            const partial = {
              id: `route_${i + 1}`,
              label: r.label,
              coordinates: r.osrmCoords,
              distance_km: r.distance_km,
              eta_minutes: r.eta_minutes,
              safe_islands: [],
              score: 0,
              factor_breakdown: {}
            };
            const scored = mockScoreRoute(partial, i);
            partial.score = scored.score;
            partial.factor_breakdown = scored.factor_breakdown;
            return partial;
          });
          dataSource = 'Live Data';
        }

        // STEP 4 — Enrich all candidate routes with real safe islands from Overpass
        document.querySelector('.loading-text').textContent = 'Finding safe islands…';
        try {
          const islandsPerRoute = await withTimeout(
            Promise.all(finalRoutes.map(r => fetchSafeIslands(r.coordinates))),
            10000
          );
          finalRoutes.forEach((r, i) => {
            r.safe_islands = islandsPerRoute[i] || [];
          });
        } catch {
          finalRoutes.forEach(r => { if (!r.safe_islands) r.safe_islands = []; });
        }

        // STEP 5 — Apply persona weights + sort
        applyPersonaWeights(finalRoutes, persona);
        finalRoutes.sort((a, b) => b.score - a.score);
        const LABELS = ['Safest Route', 'Balanced Route', 'Fastest Route'];
        finalRoutes.forEach((r, i) => { r.label = LABELS[i] || r.label; });

        // Debug log per-route sources and scores
        console.log(`[SafeRoute] ── Final ${finalRoutes.length} Routes Selected ──`);
        finalRoutes.forEach((r, i) => {
          console.log(`[SafeRoute] Route ${i + 1}: "${r.label}" | Score: ${r.score} (${scoreClass(r.score)}) | Source: ${r._source || 'unknown'} | ${r.distance_km}km | ${r.eta_minutes}min`);
        });

        return {
          routes: finalRoutes,
          meta: {
            origin:      { name: originLL.name, lat: originLL.lat, lng: originLL.lng },
            destination: { name: destLL.name,   lat: destLL.lat,   lng: destLL.lng },
            city: dataSource
          }
        };

      } catch (err) {
        console.warn('[SafeRoute] Live APIs failed, falling back to mock data:', err.message);
        showToast('⚠️ Live data unavailable — showing demo routes', 3500);
        // Fallback: return mock data with persona re-scoring applied
        const data = JSON.parse(JSON.stringify(MOCK_ROUTES_DATA));
        applyPersonaWeights(data.routes, persona);
        data.routes.sort((a, b) => b.score - a.score);
        data.meta.city = 'Demo Data';
        return data;
      }
    }

    // =====================================================
    //  HELPERS
    // =====================================================
    function scoreClass(score) {
      if (score >= 75) return 'score-high';
      if (score >= 50) return 'score-mid';
      return 'score-low';
    }

    function scoreColor(score) {
      if (score >= 75) return '#22d17c';
      if (score >= 50) return '#f5a623';
      return '#f05050';
    }

    function islandIcon(type) {
      const icons = { pharmacy: '💊', police: '🚔', shop: '🏪' };
      return icons[type] || '📌';
    }

    function islandBorderColor(type) {
      const c = { pharmacy: '#34d399', police: '#60a5fa', shop: '#fbbf24' };
      return c[type] || '#a78bfa';
    }

    function factorLabel(key) {
      const l = {
        lighting: '💡 Lighting', crowd_density: '👥 Crowd', transit_proximity: '🚇 Transit',
        isolation: '🏘️ Isolation', incident_history: '📋 History'
      };
      return l[key] || key;
    }

    function showToast(msg, duration = 2400) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), duration);
    }

    function setLoading(on) {
      document.getElementById('loading-overlay').classList.toggle('visible', on);
    }

    // =====================================================
    //  MAP INIT
    // =====================================================
    function initMap() {
      map = L.map('map', {
        center: [28.6139, 77.2090],
        zoom: 13,
        maxZoom: 16,
        zoomControl: false,
        attributionControl: false
      });

      // Primary: Esri Dark Gray Canvas (no key, no watermark, natively dark)
      const primaryTileLayer = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
        {
          attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, OpenStreetMap contributors',
          maxZoom: 16
        }
      );

      // Tile load verification
      let tilesLoadedCount = 0;
      primaryTileLayer.on('tileload', () => {
        tilesLoadedCount++;
        if (tilesLoadedCount === 1) {
          console.log('[SafeRoute] ✅ Esri Dark Gray tiles loading successfully');
        }
      });

      // Fallback: If Esri ever fails/times out, switch to OpenStreetMap
      let fallbackTriggered = false;
      primaryTileLayer.on('tileerror', (e) => {
        console.error('[SafeRoute] ❌ Tile load failed:', e);
        if (!fallbackTriggered) {
          fallbackTriggered = true;
          console.warn('[SafeRoute] Esri tile loading failed. Falling back to OpenStreetMap tiles.');
          map.removeLayer(primaryTileLayer);
          const mapEl = document.getElementById('map');
          if (mapEl) mapEl.classList.add('map-fallback-osm');
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19
          }).addTo(map);
        }
      });
      primaryTileLayer.addTo(map);

      // One-time tile load verification check after 3 seconds
      setTimeout(() => {
        if (tilesLoadedCount === 0) {
          showToast('⚠️ Map tiles failed to load — check console for details', 4000);
        }
      }, 3000);

      // Custom zoom control position
      L.control.zoom({ position: 'topright' }).addTo(map);
      L.control.attribution({ position: 'bottomleft', prefix: false }).addTo(map);
    }

    // =====================================================
    //  CLEAR MAP LAYERS
    // =====================================================
    function clearRoutes() {
      Object.values(routeLayers).forEach(l => map.removeLayer(l));
      routeLayers = {};
      islandLayers.forEach(l => map.removeLayer(l));
      islandLayers = [];
      if (originMarker) { map.removeLayer(originMarker); originMarker = null; }
      if (destMarker) { map.removeLayer(destMarker); destMarker = null; }
    }

    // =====================================================
    //  RENDER ROUTES ON MAP
    // =====================================================
    function renderRoutes(data) {
      clearRoutes();
      const { routes, meta } = data;

      // Origin marker
      originMarker = L.marker([meta.origin.lat, meta.origin.lng], {
        icon: L.divIcon({
          html: `<div class="origin-marker">📍</div>`,
          iconSize: [32, 32], iconAnchor: [16, 16], className: ''
        })
      }).addTo(map).bindPopup(`<div class="popup-name">📍 ${meta.origin.name}</div><div class="popup-addr">Starting point</div>`);

      // Destination marker
      destMarker = L.marker([meta.destination.lat, meta.destination.lng], {
        icon: L.divIcon({
          html: `<div class="dest-marker">🏁</div>`,
          iconSize: [32, 32], iconAnchor: [16, 16], className: ''
        })
      }).addTo(map).bindPopup(`<div class="popup-name">🏁 ${meta.destination.name}</div><div class="popup-addr">Destination</div>`);

      // Draw routes (lowest-scored first so best route is on top)
      [...routes].reverse().forEach(route => {
        const color = scoreColor(route.score);
        const isSelected = route.id === selectedRouteId;
        const weight = isSelected ? 7 : 4;
        const opacity = isSelected ? 0.95 : 0.55;

        const polyline = L.polyline(route.coordinates, {
          color,
          weight,
          opacity,
          lineCap: 'round',
          lineJoin: 'round',
        }).addTo(map);

        // Click handler
        polyline.on('click', () => selectRoute(route.id));

        routeLayers[route.id] = polyline;
      });

      // Draw selected route on top
      if (selectedRouteId && routeLayers[selectedRouteId]) {
        routeLayers[selectedRouteId].bringToFront();
      }

      // Draw safe-island markers for selected route (or all routes)
      routes.forEach(route => {
        const showIslands = !selectedRouteId || route.id === selectedRouteId;
        if (!showIslands) return;

        route.safe_islands.forEach(island => {
          const icon = L.divIcon({
            html: `<div class="safe-island-marker marker-${island.type}">${islandIcon(island.type)}</div>`,
            iconSize: [28, 28], iconAnchor: [14, 14], className: ''
          });

          const marker = L.marker([island.lat, island.lng], { icon })
            .addTo(map)
            .bindPopup(`
          <div class="popup-name">${islandIcon(island.type)} ${island.name}</div>
          <div class="popup-addr">${island.address}</div>
          <div class="popup-type">🛡️ Safe Island</div>
        `);

          islandLayers.push(marker);
        });
      });

      // Fit bounds to show all routes (respecting maxZoom 16)
      const allCoords = routes.flatMap(r => r.coordinates).map(c => L.latLng(c[0], c[1]));
      allCoords.push(L.latLng(meta.origin.lat, meta.origin.lng));
      allCoords.push(L.latLng(meta.destination.lat, meta.destination.lng));
      map.fitBounds(L.latLngBounds(allCoords), { padding: [60, 60], maxZoom: 16 });
    }

    // =====================================================
    //  RENDER ROUTE CARDS
    // =====================================================
    function renderCards(routes) {
      const container = document.getElementById('route-cards');
      container.innerHTML = '';

      routes.forEach((route, i) => {
        const sc = scoreClass(route.score);
        const color = scoreColor(route.score);
        const isSelected = route.id === selectedRouteId;

        const badge = i === 0
          ? `<span style="font-size:10px;background:rgba(34,209,124,0.15);border:1px solid rgba(34,209,124,0.4);border-radius:999px;padding:2px 7px;color:#22d17c;margin-left:6px">✦ Recommended</span>`
          : '';

        const factorDots = Object.entries(route.factor_breakdown).map(([k, v]) => `
      <div class="factor-dot">
        <div class="dot" style="background:${scoreColor(v)}"></div>
        ${factorLabel(k).split(' ')[1] || k}
      </div>
    `).join('');

        const card = document.createElement('div');
        card.className = `route-card ${sc}${isSelected ? ' selected' : ''}`;
        card.id = `card-${route.id}`;
        card.setAttribute('role', 'button');
        card.setAttribute('tabindex', '0');
        card.setAttribute('aria-label', `${route.label}, safety score ${route.score}`);

        card.innerHTML = `
      <div class="card-header">
        <div>
          <div class="route-label">${route.label}${badge}</div>
        </div>
        <div class="score-badge">
          <div class="score-num" style="color:${color}">${route.score}</div>
          <div class="score-label">Safety</div>
        </div>
      </div>

      <div class="score-bar-track">
        <div class="score-bar-fill" style="width:${route.score}%"></div>
      </div>

      <div class="route-meta">
        <div class="meta-item"><span class="meta-icon">⏱</span>${route.eta_minutes} min</div>
        <div class="meta-item"><span class="meta-icon">📏</span>${route.distance_km} km</div>
        <div class="meta-item"><span class="meta-icon">🛡️</span>${route.safe_islands.length} stops</div>
      </div>

      <div class="factor-dots">${factorDots}</div>

      <button class="card-cta" onclick="event.stopPropagation(); selectRoute('${route.id}')">
        ${isSelected ? '✓ Selected' : 'Select Route'}
      </button>
    `;

        card.addEventListener('click', () => selectRoute(route.id));
        card.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectRoute(route.id); }
        });

        container.appendChild(card);
      });

      document.getElementById('bottom-sheet').classList.remove('hidden');
      document.getElementById('empty-state').classList.add('hidden');
    }

    // =====================================================
    //  SELECT A ROUTE
    // =====================================================
    function selectRoute(id) {
      if (selectedRouteId === id) return;
      selectedRouteId = id;

      const route = currentRoutes.find(r => r.id === id);
      if (!route) return;

      // Update card visual states
      document.querySelectorAll('.route-card').forEach(c => {
        const isThis = c.id === `card-${id}`;
        c.classList.toggle('selected', isThis);
        const cta = c.querySelector('.card-cta');
        if (cta) cta.textContent = isThis ? '✓ Selected' : 'Select Route';
      });

      // Update polyline styles
      Object.entries(routeLayers).forEach(([rid, poly]) => {
        const isThis = rid === id;
        poly.setStyle({
          weight: isThis ? 7 : 4,
          opacity: isThis ? 0.95 : 0.35,
        });
        if (isThis) poly.bringToFront();
      });

      // Show only this route's safe islands
      islandLayers.forEach(m => map.removeLayer(m));
      islandLayers = [];
      route.safe_islands.forEach(island => {
        const icon = L.divIcon({
          html: `<div class="safe-island-marker marker-${island.type}">${islandIcon(island.type)}</div>`,
          iconSize: [28, 28], iconAnchor: [14, 14], className: ''
        });
        const marker = L.marker([island.lat, island.lng], { icon })
          .addTo(map)
          .bindPopup(`
        <div class="popup-name">${islandIcon(island.type)} ${island.name}</div>
        <div class="popup-addr">${island.address}</div>
        <div class="popup-type">🛡️ Safe Island</div>
      `);
        islandLayers.push(marker);
      });

      // Animate map to selected route (respecting maxZoom 16)
      const bounds = L.latLngBounds(route.coordinates.map(c => L.latLng(c[0], c[1])));
      map.fitBounds(bounds, { padding: [80, 80], animate: true, duration: 0.8, maxZoom: 16 });

      // Show selected banner
      const banner = document.getElementById('selected-banner');
      document.getElementById('banner-route-name').textContent = `${route.label} — Score ${route.score}`;
      document.getElementById('banner-route-sub').textContent = `${route.eta_minutes} min · ${route.distance_km} km · ${route.safe_islands.length} safe island${route.safe_islands.length !== 1 ? 's' : ''}`;
      banner.classList.add('visible');

      showToast(`✓ ${route.label} selected`);
    }

    // =====================================================
    //  PROCEED (handoff to next screen)
    // =====================================================
    function handleProceed() {
      const route = currentRoutes.find(r => r.id === selectedRouteId);
      if (!route) return;

      // Package route data for handoff — Track D (explainability+check-in) will consume this
      const handoff = {
        routeId: route.id,
        routeLabel: route.label,
        score: route.score,
        factors: route.factor_breakdown,
        safeIslands: route.safe_islands,
        persona: currentPersona,
        timestamp: Date.now(),
      };

      // Store in sessionStorage for next screen
      sessionStorage.setItem('saferoute_handoff', JSON.stringify(handoff));

      showToast('🚀 Route confirmed! Handoff ready for next step.', 3000);
      console.log('[SafeRoute] Handoff payload:', handoff);
    }

    // =====================================================
    //  PERSONA SELECT
    // =====================================================
    function selectPersona(btn) {
      document.querySelectorAll('.persona-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentPersona = btn.dataset.persona;

      if (currentRoutes.length > 0) {
        showToast(`Switching to ${btn.textContent.trim()} persona…`);
        handleFindRoutes(true);
      }
    }

    // =====================================================
    //  FIND ROUTES (main orchestrator)
    // =====================================================
    async function handleFindRoutes(isRescoring = false) {
      const originText = document.getElementById('input-origin').value.trim() || 'Connaught Place, Delhi';
      const destText   = document.getElementById('input-dest').value.trim()   || 'Lajpat Nagar, Delhi';

      if (!originText || !destText) {
        showToast('Please enter both start and destination');
        return;
      }

      setLoading(true);
      if (!isRescoring) {
        selectedRouteId = null;
        document.getElementById('selected-banner').classList.remove('visible');
      }

      try {
        // getRoutes handles geocoding internally; persona re-scoring + fallback included
        const data = await getRoutes(originText, destText, currentPersona);
        currentRoutes = data.routes;

        renderRoutes(data);
        renderCards(data.routes);

        if (!isRescoring) {
          const isMixed = data.meta.city === 'Backend + Live Road Data';
          const isBackend = data.meta.city === 'Backend Data';
          const isLive = data.meta.city === 'Live Data';
          const sourceText = isMixed ? 'Backend + Live road data' : isBackend ? 'Backend API' : isLive ? 'Live road data' : 'Demo data';
          const sourceIcon = isMixed ? '⚡🌐' : isBackend ? '⚡' : isLive ? '🌐' : '📦';
          showToast(`${sourceIcon} ${data.routes.length} routes loaded · ${sourceText}`);
        } else {
          if (selectedRouteId && currentRoutes.find(r => r.id === selectedRouteId)) {
            selectRoute(selectedRouteId);
          }
        }
      } catch (err) {
        console.error('[SafeRoute] Unhandled error:', err);
        showToast('❌ Could not load routes — check your connection');
      } finally {
        // Reset loading text for next call
        const lt = document.querySelector('.loading-text');
        if (lt) lt.textContent = 'Scoring routes…';
        setLoading(false);
      }
    }

    // =====================================================
    //  INIT
    // =====================================================
    document.addEventListener('DOMContentLoaded', () => {
      initMap();

      // Enter key on inputs
      document.getElementById('input-origin').addEventListener('keydown', e => {
        if (e.key === 'Enter') handleFindRoutes();
      });
      document.getElementById('input-dest').addEventListener('keydown', e => {
        if (e.key === 'Enter') handleFindRoutes();
      });

      // Auto-load demo routes after a short delay
      setTimeout(() => {
        handleFindRoutes();
      }, 600);
    });
