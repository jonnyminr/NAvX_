from pathlib import Path
import re
import shutil
import sys


ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "src" / "api" / "static" / "index.html"
BACKUP_FILE = ROOT / "src" / "api" / "static" / "index.before_route_speed_fix.html"


if not INDEX_FILE.exists():
    print("ERROR: index.html not found:")
    print(INDEX_FILE)
    sys.exit(1)


if not BACKUP_FILE.exists():
    shutil.copy2(INDEX_FILE, BACKUP_FILE)
    print("Backup created:")
    print(BACKUP_FILE)
else:
    print("Backup already exists:")
    print(BACKUP_FILE)


text = INDEX_FILE.read_text(encoding="utf-8")


def replace_between(start_marker, end_marker, replacement, label):
    global text

    start = text.find(start_marker)
    if start == -1:
        print(f"ERROR: Could not find start marker for {label}")
        print(start_marker)
        sys.exit(1)

    end = text.find(end_marker, start)
    if end == -1:
        print(f"ERROR: Could not find end marker for {label}")
        print(end_marker)
        sys.exit(1)

    text = text[:start] + replacement + "\n" + text[end:]
    print(f"UPDATED: {label}")


# ============================================================
# 1. SPEED UP FORECAST COUNT
# ============================================================

text, c1 = re.subn(
    r"const MAX_INITIAL_FORECASTS\s*=\s*\d+\s*;",
    "const MAX_INITIAL_FORECASTS=4;",
    text,
    count=1,
)

text, c2 = re.subn(
    r"const MAX_REFINEMENT_FORECASTS\s*=\s*\d+\s*;",
    "const MAX_REFINEMENT_FORECASTS=2;",
    text,
    count=1,
)

if c1 != 1 or c2 != 1:
    print("ERROR: Could not update forecast limits.")
    sys.exit(1)

print("UPDATED: Forecast limits")


# ============================================================
# 2. FIX REFERENCE-ONLY DESTINATIONS
# ============================================================

SELECT_NAMED_LOCATION = r'''
function selectNamedLocation(kind, id) {

    invalidateRoute(
        kind === 'origin'
            ? 'Start changed'
            : 'Destination changed'
    );


    const loc = state.locations.find(
        item => item.id === id
    );


    if (!loc) {

        if (kind === 'origin') {

            state.origin = null;

            if (q('startLocationInfo')) {
                q('startLocationInfo').innerHTML =
                    locationInfoHtml(null);
            }
        }

        else {

            state.destination = null;

            if (q('destinationLocationInfo')) {
                q('destinationLocationInfo').innerHTML =
                    locationInfoHtml(null);
            }
        }

        return;
    }


    /*
     * Some Antarctic points are reference-only stations
     * or no-data locations. Do not waste time routing to
     * them unless a verified marine access point exists.
     */

    if (loc.routing_eligible === false) {

        const message =
            `${loc.name} is reference-only. ` +
            `No verified CMEMS + NSIDC marine access point was found. ` +
            `Use Pick on Map and select a nearby validated ocean cell.`;

        if (kind === 'origin') {

            state.origin = null;

            if (q('startLocationInfo')) {
                q('startLocationInfo').innerHTML =
                    `<div class="location-name">${esc(loc.name)}</div>` +
                    `<div class="location-meta">${esc(message)}</div>`;
            }
        }

        else {

            state.destination = null;

            if (q('destinationLocationInfo')) {
                q('destinationLocationInfo').innerHTML =
                    `<div class="location-name">${esc(loc.name)}</div>` +
                    `<div class="location-meta">${esc(message)}</div>`;
            }
        }

        if (q('areaWarning')) {
            q('areaWarning').textContent =
                message;
        }

        setAnalysis(
            'REFERENCE-ONLY LOCATION — PICK A NEARBY OCEAN CELL',
            'error'
        );

        return;
    }


    const routeLat = Number(
        loc.route_lat ?? loc.lat
    );

    const routeLon = normLon(
        Number(
            loc.route_lon ?? loc.lon
        )
    );


    if (
        !Number.isFinite(routeLat)
        ||
        !Number.isFinite(routeLon)
    ) {

        const message =
            `${loc.name} does not have valid routing coordinates.`;

        if (q('areaWarning')) {
            q('areaWarning').textContent =
                message;
        }

        setAnalysis(
            message,
            'error'
        );

        return;
    }


    const point = {
        ...loc,

        lat:
            routeLat,

        lon:
            routeLon,

        reference_lat:
            Number(
                loc.reference_lat ?? loc.lat
            ),

        reference_lon:
            Number(
                loc.reference_lon ?? loc.lon
            ),

        route_anchor_distance_km:
            Number(
                loc.route_anchor?.distance_km ?? 0
            )
    };


    if (kind === 'origin') {

        state.origin =
            point;

        if (q('originLat')) {
            q('originLat').value =
                point.lat.toFixed(6);
        }

        if (q('originLon')) {
            q('originLon').value =
                point.lon.toFixed(6);
        }

        if (q('startLocationInfo')) {
            q('startLocationInfo').innerHTML =
                locationInfoHtml(point);
        }

        renderOrigin();

        updateNearby();
    }

    else {

        state.destination =
            point;

        if (q('destinationLat')) {
            q('destinationLat').value =
                point.lat.toFixed(6);
        }

        if (q('destinationLon')) {
            q('destinationLon').value =
                point.lon.toFixed(6);
        }

        if (q('destinationLocationInfo')) {
            q('destinationLocationInfo').innerHTML =
                locationInfoHtml(point);
        }

        renderDestination();
    }


    if (q('areaWarning')) {

        if (
            loc.routing_mode ===
            'NEAREST_VALIDATED_MARINE_ACCESS'
        ) {

            q('areaWarning').textContent =
                `${loc.name}: routing uses nearest verified marine access point ` +
                `${Number(loc.route_anchor?.distance_km ?? 0).toFixed(1)} km ` +
                `from the reference coordinate.`;
        }

        else if (
            loc.routing_mode ===
            'DIRECT_VALIDATED_REFERENCE'
        ) {

            q('areaWarning').textContent =
                `${loc.name}: selected coordinate is already a validated marine route point.`;
        }

        else {

            q('areaWarning').textContent =
                `Selected ${loc.name}: ${fmtCoord(point.lat, point.lon)}`;
        }
    }


    setAnalysis(
        'VALID ROUTE POINT SELECTED',
        'ok'
    );
}
'''.strip()


replace_between(
    "function selectNamedLocation",
    "function beginMapPick",
    SELECT_NAMED_LOCATION,
    "selectNamedLocation()"
)


# ============================================================
# 3. ADD ADAPTIVE ROUTING HELPERS
# ============================================================

HELPERS = r'''
function departureIso() {

  const value =
    q('departureTime')?.value;

  if (!value) {
    return new Date().toISOString();
  }

  const parsed =
    new Date(value);

  if (
    Number.isNaN(
      parsed.getTime()
    )
  ) {
    return new Date().toISOString();
  }

  return parsed.toISOString();
}


function routeDistanceKm() {

  if (
    !state.origin ||
    !state.destination
  ) {
    return 0;
  }

  return hav(
    state.origin.lat,
    state.origin.lon,
    state.destination.lat,
    state.destination.lon
  );
}


function adaptiveGridNodes(distanceKm) {

  const distance =
    Number(distanceKm || 0);

  if (distance < 1000) {
    return 60;
  }

  if (distance < 2500) {
    return 90;
  }

  if (distance < 4500) {
    return 120;
  }

  return 160;
}


function availableRouteFromResult(result) {

  const routes =
    Array.isArray(result?.routes)
      ? result.routes
      : [];

  return (
    routes.find(
      route =>
        route.profile === result.recommended_profile
        &&
        route.available !== false
    )

    ||

    routes.find(
      route =>
        route.available !== false
    )

    ||

    null
  );
}


async function optimizeWithAdaptiveGrid(
  payloadBuilder,
  label = 'route'
) {

  const distance =
    routeDistanceKm();

  const baseGrid =
    adaptiveGridNodes(distance);

  const attempts = [
    baseGrid,
    Math.min(180, baseGrid + 30),
    Math.min(220, baseGrid + 60)
  ];

  let lastResult =
    null;

  let lastError =
    null;


  for (const gridNodes of attempts) {

    try {

      setAnalysis(
        (
          `CALCULATING ${label.toUpperCase()} · ` +
          `GRID ${gridNodes} · ` +
          `${distance.toFixed(0)} KM`
        ),
        'busy'
      );

      const result =
        await postJson(
          '/api/navigation/optimize',
          payloadBuilder(gridNodes)
        );

      result.route_search = {
        mode:
          label,

        grid_nodes:
          gridNodes,

        route_distance_km:
          distance,

        adaptive:
          true
      };

      lastResult =
        result;

      if (
        availableRouteFromResult(result)
      ) {
        return result;
      }
    }

    catch (error) {

      lastError =
        error;

      if (
        error.payload?.routes
      ) {

        lastResult = {
          routes:
            error.payload.routes,

          recommended_profile:
            error.payload.recommended_profile,

          comparison_metrics:
            error.payload.comparison_metrics || [],

          route_search: {
            mode:
              label,

            grid_nodes:
              gridNodes,

            route_distance_km:
              distance,

            adaptive:
              true,

            error:
              error.message
          }
        };
      }
    }
  }


  if (
    lastResult
  ) {
    return lastResult;
  }


  throw (
    lastError ||
    new Error(
      'No verified route was returned by the routing engine.'
    )
  );
}
'''.strip()


if "function departureIso" in text:
    replace_between(
        "function departureIso",
        "async function computeRoutes",
        HELPERS,
        "adaptive routing helpers"
    )
else:
    pos = text.find("async function computeRoutes")
    if pos == -1:
        print("ERROR: Could not find computeRoutes insertion point.")
        sys.exit(1)

    text = text[:pos] + HELPERS + "\n\n" + text[pos:]
    print("UPDATED: adaptive routing helpers")


# ============================================================
# 4. UPDATED COMPUTE ROUTES
# ============================================================

COMPUTE_ROUTES = r'''
async function computeRoutes() {

  try {

    if (
      !state.origin ||
      !state.destination
    ) {
      throw new Error(
        'Select both Start and Destination before calculating routes.'
      );
    }


    checkAntarctic(
      state.origin,
      'Start'
    );

    checkAntarctic(
      state.destination,
      'Destination'
    );


    const speed =
      Number(
        q('shipSpeed').value
      );

    const safety =
      Number(
        q('safetyBuffer').value
      );


    if (
      !Number.isFinite(speed)
      ||
      speed < 1
      ||
      speed > 70
    ) {
      throw new Error(
        'Vessel speed must be a number between 1 and 70 km/h.'
      );
    }


    if (
      !Number.isFinite(safety)
      ||
      safety < 5
      ||
      safety > 150
    ) {
      throw new Error(
        'Safety buffer must be between 5 and 150 km.'
      );
    }


    const departure =
      departureIso();


    const directKm =
      hav(
        state.origin.lat,
        state.origin.lon,
        state.destination.lat,
        state.destination.lon
      );


    if (
      !Number.isFinite(directKm)
      ||
      directKm < 1
    ) {
      throw new Error(
        'Start and Destination must be different navigable positions.'
      );
    }


    invalidateRoute(
      'New route calculation started'
    );


    setAnalysis(
      'VALIDATING ROUTE INPUTS…',
      'busy'
    );


    updateNearby();


    function buildPayload(
      gridNodes,
      icebergs
    ) {

      return {
        origin:
          state.origin,

        destination:
          state.destination,

        speed_kmh:
          speed,

        safety_threshold_km:
          safety,

        grid_nodes:
          gridNodes,

        icebergs:
          icebergs || [],

        vessel_type:
          q('vesselType').value,

        departure_utc:
          departure
      };
    }


    /*
     * Stage 1:
     * Route first with no iceberg forecast delay.
     */

    state.forecasts =
      [];


    state.routeResult =
      await optimizeWithAdaptiveGrid(
        gridNodes =>
          buildPayload(
            gridNodes,
            []
          ),
        'surface route'
      );


    state.activeProfile =
      state.routeResult.recommended_profile
      ||
      (
        (
          state.routeResult.routes || []
        ).find(
          route =>
            route.available !== false
        )?.profile
      )
      ||
      null;


    renderRouteResult();

    renderAllRoutes(true);

    drawRouteGraph();

    updateRouteDependentPanels();

    renderRouteComparisonTable();


    const provisionalRoute =
      routeByProfile(
        state.activeProfile
      );


    if (
      !provisionalRoute
    ) {

      setAnalysis(
        'NO VERIFIED ROUTE AVAILABLE',
        'error'
      );

      return;
    }


    /*
     * Stage 2:
     * Forecast only icebergs close to provisional route.
     */

    if (
      provisionalRoute.route?.length
    ) {

      setAnalysis(
        'ROUTE FOUND · REFINING ICEBERG HAZARDS…',
        'busy'
      );


      await forecastNearby(
        provisionalRoute.route,
        false,
        MAX_INITIAL_FORECASTS
      );


      if (
        state.forecasts.length
      ) {

        state.routeResult =
          await optimizeWithAdaptiveGrid(
            gridNodes =>
              buildPayload(
                gridNodes,
                state.forecasts
              ),
            'hazard refined route'
          );


        state.activeProfile =
          state.routeResult.recommended_profile
          ||
          (
            (
              state.routeResult.routes || []
            ).find(
              route =>
                route.available !== false
            )?.profile
          )
          ||
          state.activeProfile;


        renderRouteResult();

        renderAllRoutes(true);

        renderForecastAtHorizon();

        drawRouteGraph();

        updateRouteDependentPanels();

        renderRouteComparisonTable();
      }
    }


    loadAiDecision();

    setAnalysis(
      'ANALYSIS COMPLETE',
      'ok'
    );

  }

  catch (error) {

    state.routeResult =
      error.payload?.routes

        ? {
            routes:
              error.payload.routes,

            comparison_metrics:
              error.payload.comparison_metrics || []
          }

        : state.routeResult;


    renderRouteResult();

    renderAllRoutes(false);

    drawRouteGraph();


    setAnalysis(
      (
        String(error.message).includes('No ocean-safe')
        ||
        String(error.message).includes('No verified')
      )

        ? 'NO VERIFIED ROUTE AVAILABLE'

        : `ROUTE ANALYSIS FAILED — ${error.message}`,
      'error'
    );


    if (q('routeDecisionTitle')) {
      q('routeDecisionTitle').textContent =
        'NO VERIFIED ROUTE AVAILABLE';
    }

    if (q('routeDecisionText')) {
      q('routeDecisionText').textContent =
        error.message || String(error);
    }

    if (q('explainList')) {
      q('explainList').innerHTML =
        `<li>${esc(error.message || String(error))}</li>`;
    }

    if (q('mapStatusText')) {
      q('mapStatusText').textContent =
        error.message || String(error);
    }
  }
}
'''.strip()


replace_between(
    "async function computeRoutes",
    "function routeByProfile",
    COMPUTE_ROUTES,
    "computeRoutes()"
)


# ============================================================
# 5. UPDATED SCENARIO SIMULATOR
# ============================================================

RUN_SCENARIO = r'''
async function runScenario() {

  const box =
    q('scenarioStatus');


  if (
    !box
  ) {
    return;
  }


  function scenarioStatus(
    message,
    type = ''
  ) {

    box.textContent =
      message;

    box.className =
      'analysis-status' +
      (
        type
          ? ` ${type}`
          : ''
      );
  }


  if (
    !state.origin ||
    !state.destination
  ) {

    scenarioStatus(
      (
        'Select Start and Destination in Voyage Planner first. ' +
        'You do not need to generate the main route before running a scenario.'
      ),
      'error'
    );

    return;
  }


  const speed =
    Number(
      q('scenarioSpeed').value
    );

  const safety =
    Number(
      q('scenarioSafety').value
    );


  if (
    !Number.isFinite(speed)
    ||
    speed < 1
    ||
    speed > 70
  ) {

    scenarioStatus(
      'Scenario vessel speed must be between 1 and 70 km/h.',
      'error'
    );

    return;
  }


  if (
    !Number.isFinite(safety)
    ||
    safety < 5
    ||
    safety > 150
  ) {

    scenarioStatus(
      'Scenario safety buffer must be between 5 and 150 km.',
      'error'
    );

    return;
  }


  try {

    checkAntarctic(
      state.origin,
      'Scenario start'
    );

    checkAntarctic(
      state.destination,
      'Scenario destination'
    );


    const directKm =
      hav(
        state.origin.lat,
        state.origin.lon,
        state.destination.lat,
        state.destination.lon
      );


    if (
      !Number.isFinite(directKm)
      ||
      directKm < 1
    ) {
      throw new Error(
        'Scenario Start and Destination must be different valid Antarctic positions.'
      );
    }


    scenarioStatus(
      'RUNNING WHAT-IF ROUTE…',
      'busy'
    );


    const departureUtc =
      departureIso();


    function buildScenarioPayload(
      gridNodes
    ) {

      return {
        origin:
          state.origin,

        destination:
          state.destination,

        speed_kmh:
          speed,

        safety_threshold_km:
          safety,

        grid_nodes:
          gridNodes,

        icebergs:
          state.forecasts || [],

        vessel_type:
          q('vesselType')?.value || 'Other',

        departure_utc:
          departureUtc
      };
    }


    const result =
      await optimizeWithAdaptiveGrid(
        buildScenarioPayload,
        'scenario'
      );


    state.scenarioResult =
      result;


    const scenarioRoute =
      availableRouteFromResult(
        result
      );


    if (
      !scenarioRoute
    ) {

      if (q('scenarioProfile')) {
        q('scenarioProfile').textContent =
          'UNAVAILABLE';
      }

      if (q('scenarioRisk')) {
        q('scenarioRisk').textContent =
          'N/A';
      }

      if (q('scenarioEta')) {
        q('scenarioEta').textContent =
          'N/A';
      }

      if (q('scenarioDistance')) {
        q('scenarioDistance').textContent =
          'N/A';
      }

      if (q('scenarioDelta')) {
        q('scenarioDelta').textContent =
          'No verified route was returned for this scenario.';
      }


      scenarioStatus(
        'NO VERIFIED ROUTE AVAILABLE FOR THIS SCENARIO',
        'error'
      );

      return;
    }


    const base =
      activeRoute();


    if (q('scenarioRisk')) {

      q('scenarioRisk').textContent =
        scenarioRoute.risk_score == null

          ? 'N/A'

          : (
              Number(
                scenarioRoute.risk_score
              ).toFixed(0)
              +
              '/100'
            );
    }


    if (q('scenarioEta')) {

      q('scenarioEta').textContent =
        formatDuration(
          scenarioRoute.eta_hours
        );
    }


    if (q('scenarioDistance')) {

      q('scenarioDistance').textContent =
        `${Number(
          scenarioRoute.distance_km
        ).toFixed(1)} km`;
    }


    if (q('scenarioProfile')) {

      q('scenarioProfile').textContent =
        routeLabel(
          scenarioRoute.profile
        );
    }


    if (q('scenarioDelta')) {

      q('scenarioDelta').innerHTML =
        base

          ? (
              `Compared with current ${esc(
                routeLabel(
                  base.profile
                )
              )}: ` +
              `risk ${deltaText(
                scenarioRoute.risk_score,
                base.risk_score,
                ''
              )}, ` +
              `ETA ${deltaText(
                scenarioRoute.eta_hours,
                base.eta_hours,
                ' h'
              )}, ` +
              `distance ${deltaText(
                scenarioRoute.distance_km,
                base.distance_km,
                ' km'
              )}.`
            )

          : (
              'Standalone scenario completed. ' +
              'No baseline route is currently selected.'
            );
    }


    scenarioStatus(
      (
        'WHAT-IF MODEL OUTPUT COMPLETE — ' +
        'uses verified source data with changed operator parameters.'
      ),
      'ok'
    );

  }

  catch (error) {

    console.error(
      'Scenario error:',
      error
    );


    scenarioStatus(
      `SCENARIO UNAVAILABLE — ${error.message}`,
      'error'
    );


    if (q('scenarioDelta')) {
      q('scenarioDelta').textContent =
        error.message || String(error);
    }
  }
}
'''.strip()


replace_between(
    "async function runScenario",
    "function deltaText",
    RUN_SCENARIO,
    "runScenario()"
)


# ============================================================
# 6. FINAL CHECKS
# ============================================================

required = [
    "const MAX_INITIAL_FORECASTS=4;",
    "const MAX_REFINEMENT_FORECASTS=2;",
    "function adaptiveGridNodes",
    "function optimizeWithAdaptiveGrid",
    "async function computeRoutes()",
    "async function runScenario()",
    "REFERENCE-ONLY LOCATION",
    "ROUTE FOUND · REFINING ICEBERG HAZARDS",
]


for item in required:
    if item not in text:
        print("ERROR: Missing after patch:", item)
        print("No file written.")
        sys.exit(1)


INDEX_FILE.write_text(text, encoding="utf-8")


print()
print("=" * 72)
print("UPDATED index.html SUCCESSFULLY")
print("=" * 72)
print()
print("Updated:")
print(INDEX_FILE)
print()
print("Backup:")
print(BACKUP_FILE)
print()
print("Done.")
