from pathlib import Path
import re
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
INDEX_FILE = PROJECT_ROOT / "src" / "api" / "static" / "index.html"
BACKUP_FILE = PROJECT_ROOT / "src" / "api" / "static" / "index.before_unified_icebergs.html"


if not INDEX_FILE.exists():
    print(f"ERROR: index.html not found:")
    print(INDEX_FILE)
    sys.exit(1)


# ------------------------------------------------------------
# BACKUP
# ------------------------------------------------------------

if not BACKUP_FILE.exists():
    shutil.copy2(INDEX_FILE, BACKUP_FILE)
    print(f"Backup created:")
    print(BACKUP_FILE)
else:
    print("Backup already exists:")
    print(BACKUP_FILE)


text = INDEX_FILE.read_text(
    encoding="utf-8"
)


def replace_regex_once(
    source: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    updated, count = re.subn(
        pattern,
        lambda _: replacement,
        source,
        count=1,
        flags=re.DOTALL,
    )

    if count != 1:
        raise RuntimeError(
            f"Could not safely replace: {label}. "
            f"Matches found: {count}"
        )

    print(f"UPDATED: {label}")

    return updated


# ============================================================
# 1. UNIFIED ICEBERG CATALOG HTML
# ============================================================

UNIFIED_CATALOG_HTML = r'''
<section class="page-view" id="icebergCatalog">
  <div class="page-inner">

    <div class="page-heading">
      <div>
        <h2>Unified Iceberg Catalog</h2>

        <p>
          Current authoritative USNIC observations,
          supplemental BYU/SCP ASCAT + OSCAT-2 positions,
          and published BYU/NIC historical iceberg tracks.
        </p>
      </div>

      <button
        class="btn btn-secondary btn-small"
        onclick="navigateTo('mapSection')"
      >
        Open Current Map
      </button>
    </div>


    <div class="data-banner">

      <div>ICE</div>

      <div>
        <strong>
          REAL SOURCE-LABELLED ICEBERG DATABASE
        </strong>

        <span id="icebergSourceText">
          Loading unified iceberg database…
        </span>
      </div>

    </div>


    <div
      class="summary-grid"
      style="margin-bottom:16px"
    >

      <div class="summary">
        <div class="k">
          Unique Icebergs
        </div>

        <div
          class="v"
          id="catalogUniqueCount"
        >
          --
        </div>

        <div class="s">
          All stored designations
        </div>
      </div>


      <div class="summary">
        <div class="k">
          Total Observations
        </div>

        <div
          class="v"
          id="catalogObservationCount"
        >
          --
        </div>

        <div class="s">
          Real stored positions
        </div>
      </div>


      <div class="summary">
        <div class="k">
          Official Current
        </div>

        <div
          class="v"
          id="catalogUsnicCount"
        >
          --
        </div>

        <div class="s">
          Latest USNIC snapshot
        </div>
      </div>


      <div class="summary">
        <div class="k">
          Supplemental Current
        </div>

        <div
          class="v"
          id="catalogByuCurrentCount"
        >
          --
        </div>

        <div class="s">
          BYU/SCP ASCAT + OSCAT-2
        </div>
      </div>


      <div class="summary">
        <div class="k">
          Historical Positions
        </div>

        <div
          class="v"
          id="catalogHistoricalCount"
        >
          --
        </div>

        <div class="s">
          BYU/NIC archive
        </div>
      </div>

    </div>


    <article class="card">

      <div class="card-body">

        <div class="search-row">

          <input
            id="icebergSearch"
            placeholder="Search A23A, B15, A68, designation, source or status…"
            oninput="renderIcebergTable()"
          >


          <button
            class="btn btn-secondary btn-small"
            onclick="
              document.getElementById('icebergSearch').value='';
              renderIcebergTable()
            "
          >
            Clear
          </button>


          <button
            class="btn btn-secondary btn-small"
            onclick="loadUnifiedIcebergCatalog()"
          >
            Refresh Catalog
          </button>

        </div>


        <div
          class="table-wrap"
          style="max-height:650px"
        >

          <table>

            <thead>

              <tr>
                <th>Designation</th>
                <th>Status</th>
                <th>First Observation</th>
                <th>Latest Stored Observation</th>
                <th>Positions</th>
                <th>Sources</th>
                <th>Historical Track</th>
                <th>Action</th>
              </tr>

            </thead>


            <tbody id="icebergTable">

              <tr>
                <td colspan="8">
                  LOADING UNIFIED ICEBERG DATABASE…
                </td>
              </tr>

            </tbody>

          </table>

        </div>


        <div
          class="hint"
          style="margin-top:10px"
        >
          USNIC remains the authoritative source for current
          named Antarctic iceberg positions. BYU/SCP positions
          are supplemental current observations. Historical
          positions are retained for track analysis and research
          and are not automatically treated as present-day
          navigation hazards.
        </div>

      </div>

    </article>

  </div>
</section>
'''.strip()


text = replace_regex_once(
    text,
    (
        r'<section class="page-view" id="icebergCatalog">'
        r'.*?</section>\s*'
        r'(?=<section class="page-view" id="vesselCatalog">)'
    ),
    UNIFIED_CATALOG_HTML + "\n      ",
    "Unified Iceberg Catalog HTML",
)


# ============================================================
# 2. PAGE DESCRIPTION
# ============================================================

text = re.sub(
    (
        r"icebergCatalog:\['Iceberg Catalog',"
        r"'[^']*'\],"
    ),
    (
        "icebergCatalog:["
        "'Unified Iceberg Catalog',"
        "'USNIC current, BYU/SCP supplemental current, "
        "and BYU/NIC historical iceberg observations.'"
        "],"
    ),
    text,
    count=1,
)

print("UPDATED: Iceberg Catalog page metadata")


# ============================================================
# 3. STATE STORAGE
# ============================================================

if "allIcebergs:" not in text:

    target = (
        "locations:[],icebergs:[],"
        "icebergMeta:null,vessels:[]"
    )

    replacement = (
        "locations:[],"
        "icebergs:[],"
        "icebergMeta:null,"
        "allIcebergs:[],"
        "allIcebergMeta:null,"
        "vessels:[]"
    )

    if target not in text:
        raise RuntimeError(
            "Could not locate state iceberg fields."
        )

    text = text.replace(
        target,
        replacement,
        1,
    )

    print("UPDATED: Unified iceberg state")

else:
    print(
        "OK: Unified iceberg state "
        "already exists"
    )


# ============================================================
# 4. GENERAL ICEBERG SERIES LABEL
# ============================================================

text = text.replace(
    "||'Other USNIC series'",
    "||'Other iceberg series'",
)


# ============================================================
# 5. LOAD CURRENT USNIC + FULL CATALOG SEPARATELY
# ============================================================

ICEBERG_LOADERS = r'''
async function loadUnifiedIcebergCatalog() {
  try {

    const d = await getJson(
      '/api/data/icebergs/all/catalog?limit=5000'
    );

    state.allIcebergMeta = d;

    state.allIcebergs =
      Array.isArray(d.catalog)
        ? d.catalog
        : [];


    /*
     * Keep the Historical Replay catalogue synchronized
     * with exactly the same real database summary.
     */
    state.historyCatalog = d;


    if (q('catalogUniqueCount')) {
      q('catalogUniqueCount').textContent =
        Number(
          d.unique_icebergs || 0
        ).toLocaleString();
    }


    if (q('catalogObservationCount')) {
      q('catalogObservationCount').textContent =
        Number(
          d.observation_rows || 0
        ).toLocaleString();
    }


    if (q('catalogUsnicCount')) {
      q('catalogUsnicCount').textContent =
        Number(
          d.current_usnic_designations || 0
        ).toLocaleString();
    }


    if (q('catalogByuCurrentCount')) {
      q('catalogByuCurrentCount').textContent =
        Number(
          d.current_byu_designations || 0
        ).toLocaleString();
    }


    if (q('catalogHistoricalCount')) {
      q('catalogHistoricalCount').textContent =
        Number(
          d.historical_rows || 0
        ).toLocaleString();
    }


    if (q('icebergSourceText')) {

      q('icebergSourceText').textContent =
        `${Number(
          d.unique_icebergs || 0
        ).toLocaleString()} iceberg designations · ` +

        `${Number(
          d.observation_rows || 0
        ).toLocaleString()} real stored observations · ` +

        `${Number(
          d.current_usnic_designations || 0
        ).toLocaleString()} official-current USNIC · ` +

        `${Number(
          d.current_byu_designations || 0
        ).toLocaleString()} supplemental-current BYU/SCP · ` +

        `${Number(
          d.historical_rows || 0
        ).toLocaleString()} historical positions.`;
    }


    renderIcebergTable();

    renderHistoryCatalog();

    renderHomeStatus();

  } catch (e) {

    console.error(
      'Unified iceberg catalog failed:',
      e
    );


    state.allIcebergs = [];

    state.allIcebergMeta = null;


    if (q('icebergSourceText')) {
      q('icebergSourceText').textContent =
        'Unified iceberg database unavailable.';
    }


    if (q('catalogUniqueCount')) {
      q('catalogUniqueCount').textContent = '--';
    }

    if (q('catalogObservationCount')) {
      q('catalogObservationCount').textContent = '--';
    }

    if (q('catalogUsnicCount')) {
      q('catalogUsnicCount').textContent = '--';
    }

    if (q('catalogByuCurrentCount')) {
      q('catalogByuCurrentCount').textContent = '--';
    }

    if (q('catalogHistoricalCount')) {
      q('catalogHistoricalCount').textContent = '--';
    }


    renderIcebergTable();

    renderHomeStatus();
  }
}


async function loadIcebergs() {

  /*
   * IMPORTANT:
   *
   * state.icebergs is deliberately ONLY the official
   * current USNIC navigation layer.
   *
   * state.allIcebergs is the complete database catalogue.
   */

  try {

    const d = await getJson(
      '/api/data/icebergs'
    );


    state.icebergMeta = d;


    state.icebergs = (
      d.icebergs?.features || []
    )
      .map(f => {

        const p =
          f.properties || {};

        const c =
          f.geometry?.coordinates || [];


        return {

          id:
            p.id ||
            p.iceberg_id ||
            'UNKNOWN',

          lat:
            Number(c[1]),

          lon:
            normLon(
              Number(c[0])
            ),

          observed:
            p.date_observed ||
            d.timestamp ||
            'N/A',

          age:
            Number(
              p.observation_age_hours
            ),

          lengthNm:
            p.length_nm == null
              ? null
              : Number(
                  p.length_nm
                ),

          widthNm:
            p.width_nm == null
              ? null
              : Number(
                  p.width_nm
                ),

          uncertaintyKm:
            p.position_uncertainty_km == null
              ? null
              : Number(
                  p.position_uncertainty_km
                ),

          source:
            p.source ||
            d.source ||
            'USNIC',

          coordinatePrecision:
            p.coordinate_precision ||
            'As published by USNIC',

          positionType:
            p.position_type ||
            'OFFICIAL_OBSERVATION'
        };
      })
      .filter(
        validPoint
      );


    /*
     * These functions use official-current USNIC positions.
     * Do NOT replace them with historical observations.
     */
    renderIceMarkers();

    populateIcebergDetailSelect();

    renderHomeStatus();

    updateRouteDependentPanels();


    if (state.origin) {
      updateNearby();
    }

  } catch (e) {

    console.error(
      'USNIC current iceberg feed failed:',
      e
    );


    state.icebergs = [];

    state.icebergMeta = null;


    renderIceMarkers();

    populateIcebergDetailSelect();

    renderHomeStatus();

    updateRouteDependentPanels();
  }


  /*
   * Load the much larger catalogue separately.
   *
   * Failure of this request must never remove the official
   * current navigation layer from the Antarctic map.
   */
  await loadUnifiedIcebergCatalog();
}
'''.strip()


if "async function loadUnifiedIcebergCatalog()" in text:

    text = replace_regex_once(
        text,
        (
            r'async function loadUnifiedIcebergCatalog\(\)'
            r'\s*\{.*?'
            r'(?=\nasync function loadIcebergs\(\))'
            r'async function loadIcebergs\(\).*?'
            r'(?=\nfunction aisScanReference)'
        ),
        ICEBERG_LOADERS + "\n",
        "Iceberg data loaders",
    )

else:

    text = replace_regex_once(
        text,
        (
            r'async function loadIcebergs\(\).*?'
            r'(?=\nfunction aisScanReference)'
        ),
        ICEBERG_LOADERS + "\n",
        "Iceberg data loaders",
    )


# ============================================================
# 6. FULL CATALOG TABLE
# ============================================================

ICEBERG_TABLE_FUNCTIONS = r'''
function renderIcebergTable() {

  const input =
    q('icebergSearch');


  const search = (
    input?.value || ''
  )
    .trim()
    .toLowerCase();


  const rows = (
    state.allIcebergs || []
  ).filter(item => {

    if (!search) {
      return true;
    }


    const searchable = [

      item.iceberg_id,

      item.current_status,

      icebergSeries(
        item.iceberg_id
      ),

      ...(
        Array.isArray(
          item.sources
        )
          ? item.sources
          : []
      )

    ];


    return searchable.some(
      value =>
        String(
          value || ''
        )
          .toLowerCase()
          .includes(
            search
          )
    );
  });


  if (!q('icebergTable')) {
    return;
  }


  q('icebergTable').innerHTML =
    rows.length

      ? rows.map(item => {

          const id =
            String(
              item.iceberg_id ||
              'UNKNOWN'
            );


          const status =
            String(
              item.current_status ||
              'UNKNOWN'
            );


          let statusLabel =
            status;


          let statusClass =
            '';


          if (
            status ===
            'OFFICIAL_CURRENT'
          ) {

            statusLabel =
              'OFFICIAL CURRENT';

            statusClass =
              'risk-low';
          }

          else if (
            status ===
            'SUPPLEMENTAL_CURRENT'
          ) {

            statusLabel =
              'SUPPLEMENTAL CURRENT';

            statusClass =
              'risk-moderate';
          }

          else if (
            status ===
            'HISTORICAL_ONLY'
          ) {

            statusLabel =
              'HISTORICAL ONLY';
          }


          const sources =
            Array.isArray(
              item.sources
            )
              ? item.sources.join(
                  ', '
                )
              : 'N/A';


          const first =
            item.first_observed_at
              ? String(
                  item.first_observed_at
                ).slice(
                  0,
                  10
                )
              : 'N/A';


          const last =
            item.last_observed_at
              ? String(
                  item.last_observed_at
                ).slice(
                  0,
                  10
                )
              : 'N/A';


          const count =
            Number(
              item.observation_count ||
              0
            );


          const mapButton =
            item.currently_in_usnic_database

              ? `
                <button
                  class="btn btn-secondary btn-small"
                  onclick="focusIceberg('${esc(id)}')"
                >
                  Current Map
                </button>
              `

              : '';


          const historyLabel =
            item.has_historical_track
              ? 'AVAILABLE'
              : (
                  item.currently_in_usnic_database ||
                  item.currently_in_byu_scp_database

                    ? 'CURRENT RECORD ONLY'

                    : 'NO STORED TRACK'
                );


          return `
            <tr>

              <td>
                <strong>
                  ${esc(id)}
                </strong>

                <br>

                <span class="hint">
                  ${esc(
                    icebergSeries(id)
                  )}
                </span>
              </td>


              <td>
                <strong class="${statusClass}">
                  ${esc(statusLabel)}
                </strong>

                ${
                  item.currently_in_usnic_database &&
                  item.currently_in_byu_scp_database

                    ? `
                      <br>
                      <span class="hint">
                        Also present in BYU/SCP current page
                      </span>
                    `

                    : ''
                }
              </td>


              <td>
                ${esc(first)}
              </td>


              <td>
                ${esc(last)}
              </td>


              <td>
                <strong>
                  ${count.toLocaleString()}
                </strong>
              </td>


              <td>
                ${esc(sources)}
              </td>


              <td>
                ${esc(historyLabel)}
              </td>


              <td>

                <div
                  class="actions"
                  style="margin:0"
                >

                  ${mapButton}

                  <button
                    class="btn btn-secondary btn-small"
                    onclick="openIcebergHistoryFromCatalog('${esc(id)}')"
                  >
                    Full Track
                  </button>

                </div>

              </td>

            </tr>
          `;
        }).join('')

      : `
        <tr>
          <td colspan="8">
            NO MATCHING ICEBERG RECORDS
          </td>
        </tr>
      `;
}


async function openIcebergHistoryFromCatalog(
  icebergId
) {

  const id =
    String(
      icebergId || ''
    )
      .trim()
      .toUpperCase();


  if (!id) {
    return;
  }


  navigateTo(
    'historicalSection'
  );


  const search =
    q('historyCatalogSearch');


  if (search) {
    search.value = id;
  }


  renderHistoryCatalog();


  await viewHistoricalTrack(
    id
  );
}
'''.strip()


text = replace_regex_once(
    text,
    (
        r'function renderIcebergTable\(\).*?'
        r'(?=\nfunction renderVesselTable)'
    ),
    ICEBERG_TABLE_FUNCTIONS + "\n",
    "Unified iceberg table renderer",
)


# ============================================================
# 7. HOME COUNTER
# ============================================================

HOME_STATUS = r'''
function renderHomeStatus() {

  const currentUsnic =
    state.icebergs?.length || 0;


  const catalogCount =
    Number(
      state.allIcebergMeta
        ?.unique_icebergs || 0
    );


  const vs =
    state.vessels?.length || 0;


  const ds =
    state.health?.datasets || {};


  if (q('homeIcebergCount')) {

    if (catalogCount > 0) {

      q('homeIcebergCount').textContent =
        `${catalogCount.toLocaleString()} catalog · ` +
        `${currentUsnic.toLocaleString()} official current`;

    } else if (currentUsnic > 0) {

      q('homeIcebergCount').textContent =
        `${currentUsnic.toLocaleString()} official current`;

    } else {

      q('homeIcebergCount').textContent =
        'DATA UNAVAILABLE';
    }
  }


  if (q('homeAisCount')) {

    q('homeAisCount').textContent =
      vs
        ? String(vs)
        : 'NO CURRENT POSITIONS';
  }


  if (q('homeSurfaceStatus')) {

    q('homeSurfaceStatus').textContent =
      state.health
        ?.navigation_surface
        ?.available

        ? 'READY'
        : 'UNAVAILABLE';
  }


  if (q('homeDatasetStatus')) {

    const available =
      Object.values(ds)
        .filter(Boolean)
        .length;


    const total =
      Object.keys(ds)
        .length;


    q('homeDatasetStatus').textContent =
      total
        ? `${available}/${total} loaded`
        : 'checking…';
  }


  if (q('homeDataMode')) {

    q('homeDataMode').textContent =
      state.provenance
        ?.data_mode ||
      'Checking scientific provenance…';
  }
}
'''.strip()


text = replace_regex_once(
    text,
    (
        r'function renderHomeStatus\(\)\{.*?'
        r'(?=\nfunction activeRoute)'
    ),
    HOME_STATUS + "\n",
    "Home iceberg counter",
)


# ============================================================
# 8. HISTORICAL CATALOG USES SAME UNIFIED DATABASE
# ============================================================

HISTORY_FUNCTIONS = r'''
async function loadHistoryCatalog() {

  try {

    const d = await getJson(
      '/api/data/icebergs/all/catalog?limit=5000'
    );


    state.historyCatalog = d;


    /*
     * Share the exact same database payload with the
     * Unified Iceberg Catalog page.
     */
    state.allIcebergMeta = d;

    state.allIcebergs =
      Array.isArray(d.catalog)
        ? d.catalog
        : [];


    if (q('historyCatalogStatus')) {

      q('historyCatalogStatus').textContent =
        `${Number(
          d.unique_icebergs || 0
        ).toLocaleString()} designations · ` +

        `${Number(
          d.observation_rows || 0
        ).toLocaleString()} stored positions · ` +

        `${Number(
          d.historical_rows || 0
        ).toLocaleString()} historical · ` +

        `${Number(
          d.current_usnic_designations || 0
        ).toLocaleString()} official-current USNIC · ` +

        `${Number(
          d.current_byu_designations || 0
        ).toLocaleString()} supplemental-current BYU/SCP`;
    }


    renderHistoryCatalog();

    renderIcebergTable();

    renderHomeStatus();

  } catch (e) {

    state.historyCatalog = null;


    if (q('historyCatalogStatus')) {

      q('historyCatalogStatus').textContent =
        `Historical catalogue unavailable: ${e.message}`;
    }


    if (q('historyCatalogTable')) {

      q('historyCatalogTable').innerHTML =
        '<tr><td colspan="6">HISTORICAL DATA UNAVAILABLE</td></tr>';
    }
  }
}


function renderHistoryCatalog() {

  const body =
    q('historyCatalogTable');


  if (!body) {
    return;
  }


  const term = (
    q('historyCatalogSearch')
      ?.value || ''
  )
    .trim()
    .toLowerCase();


  const rows = (
    state.historyCatalog
      ?.catalog || []
  ).filter(
    row =>
      !term ||
      String(
        row.iceberg_id || ''
      )
        .toLowerCase()
        .includes(term)
  );


  body.innerHTML =
    rows.length

      ? rows
          .slice(
            0,
            5000
          )
          .map(row => {

            let currentState =
              'HISTORICAL ONLY';


            if (
              row.current_status ===
              'OFFICIAL_CURRENT'
            ) {

              currentState =
                '<span class="state-pill state-ok">USNIC CURRENT</span>';
            }

            else if (
              row.current_status ===
              'SUPPLEMENTAL_CURRENT'
            ) {

              currentState =
                '<span class="risk-moderate"><strong>BYU/SCP CURRENT</strong></span>';
            }


            return `
              <tr>

                <td>
                  <strong>
                    ${esc(
                      row.iceberg_id
                    )}
                  </strong>
                </td>

                <td>
                  ${esc(
                    (
                      row.first_observed_at ||
                      'N/A'
                    ).slice(
                      0,
                      10
                    )
                  )}
                </td>

                <td>
                  ${esc(
                    (
                      row.last_observed_at ||
                      'N/A'
                    ).slice(
                      0,
                      10
                    )
                  )}
                </td>

                <td>
                  ${Number(
                    row.observation_count ||
                    0
                  ).toLocaleString()}
                </td>

                <td>
                  ${currentState}
                </td>

                <td>
                  <button
                    class="btn btn-secondary btn-small"
                    onclick="viewHistoricalTrack('${esc(
                      row.iceberg_id
                    )}')"
                  >
                    Track
                  </button>
                </td>

              </tr>
            `;
          })
          .join('')

      : `
        <tr>
          <td colspan="6">
            NO MATCHING ICEBERG TRACKS
          </td>
        </tr>
      `;
}


async function viewHistoricalTrack(
  icebergId
) {

  try {

    const id =
      String(
        icebergId || ''
      )
        .trim()
        .toUpperCase();


    const result =
      await getJson(
        `/api/data/icebergs/all/${encodeURIComponent(id)}/track`
      );


    state.historyTrack =
      result;


    const obs =
      Array.isArray(
        result.positions
      )
        ? result.positions
        : [];


    if (q('historyTrackStatus')) {

      q('historyTrackStatus').textContent =
        `${result.iceberg_id || id} · ` +

        `${Number(
          obs.length
        ).toLocaleString()} stored source-labelled positions · ` +

        'USNIC authoritative for current named iceberg positions';
    }


    if (q('historyTrackTable')) {

      q('historyTrackTable').innerHTML =
        obs.length

          ? obs
              .slice()
              .reverse()
              .slice(
                0,
                3000
              )
              .map(o => `

                <tr>

                  <td>
                    ${esc(
                      o.date ||
                      (
                        o.timestamp
                          ? String(
                              o.timestamp
                            ).slice(
                              0,
                              10
                            )
                          : 'N/A'
                      )
                    )}
                  </td>

                  <td>
                    ${esc(
                      fmtCoord(
                        o.latitude,
                        o.longitude
                      )
                    )}
                  </td>

                  <td>
                    ${esc(
                      o.source ||
                      'N/A'
                    )}
                  </td>

                  <td>
                    ${esc(
                      o.sensor ||
                      o.position_type ||
                      'published fix'
                    )}
                  </td>

                </tr>

              `)
              .join('')

          : `
            <tr>
              <td colspan="4">
                NO STORED TRACK POSITIONS
              </td>
            </tr>
          `;
    }


    drawHistoricalTrack(
      obs
    );


    navigateTo(
      'historicalSection'
    );

  } catch (e) {

    if (q('historyTrackStatus')) {

      q('historyTrackStatus').textContent =
        `Track unavailable: ${e.message}`;
    }
  }
}
'''.strip()


text = replace_regex_once(
    text,
    (
        r'async function loadHistoryCatalog\(\).*?'
        r'(?=\nfunction drawHistoricalTrack)'
    ),
    HISTORY_FUNCTIONS + "\n",
    "Historical catalogue and track functions",
)


# ============================================================
# 9. HISTORY SCREEN WORDING
# ============================================================

text = text.replace(
    (
        "Published historical BYU/NIC tracks plus "
        "current authoritative USNIC observations. "
        "Historical positions are never treated as "
        "current hazards."
    ),
    (
        "Published BYU/NIC historical tracks, "
        "current authoritative USNIC observations, "
        "and supplemental BYU/SCP current positions. "
        "Historical positions are never treated as "
        "current hazards."
    ),
)


text = text.replace(
    "<th>Current USNIC?</th>",
    "<th>Current state</th>",
)


# ============================================================
# 10. SHOW-VIEW TRACK REFERENCE
# ============================================================

text = text.replace(
    (
        "if(id==='historicalSection')"
        "setTimeout(()=>{"
        "if(state.archive)renderHistoricalReplay();"
        "if(state.historyCatalog)renderHistoryCatalog();"
        "if(state.historyTrack)"
        "drawHistoricalTrack("
        "state.historyTrack.observations||[]"
        ");},20);"
    ),
    (
        "if(id==='historicalSection')"
        "setTimeout(()=>{"
        "if(state.archive)renderHistoricalReplay();"
        "if(state.historyCatalog)renderHistoryCatalog();"
        "if(state.historyTrack)"
        "drawHistoricalTrack("
        "state.historyTrack.positions||[]"
        ");},20);"
    ),
)


# Ensure catalog page renders when opened.
if (
    "if(id==='icebergCatalog')" not in text
):

    marker = (
        "if(id==='dataObservatory')"
        "setTimeout(renderDataObservatory,20);"
    )

    addition = (
        "if(id==='icebergCatalog')"
        "setTimeout(()=>{"
        "if(state.allIcebergMeta)"
        "renderIcebergTable();"
        "else "
        "loadUnifiedIcebergCatalog();"
        "},20);\n  "
        + marker
    )

    if marker not in text:
        raise RuntimeError(
            "Could not find showView insertion point."
        )

    text = text.replace(
        marker,
        addition,
        1,
    )

    print(
        "UPDATED: Catalog navigation loader"
    )


# ============================================================
# 11. GLOBAL SEARCH
# ============================================================

GLOBAL_SEARCH = r'''
function globalSearch() {

  const term = (
    q('globalSearch')
      ?.value || ''
  )
    .trim()
    .toLowerCase();


  if (!term) {
    return;
  }


  const pages =
    Object.entries(
      viewMeta
    );


  const pageHit =
    pages.find(
      ([, meta]) =>
        meta
          .join(' ')
          .toLowerCase()
          .includes(term)
    );


  if (pageHit) {

    navigateTo(
      pageHit[0]
    );

    return;
  }


  /*
   * Search the full 649+ designation database,
   * not only current USNIC hazards.
   */
  const allIceberg =
    (
      state.allIcebergs ||
      []
    ).find(
      x =>
        String(
          x.iceberg_id || ''
        )
          .toLowerCase()
          .includes(term)
    );


  if (allIceberg) {

    navigateTo(
      'icebergCatalog'
    );


    if (q('icebergSearch')) {

      q('icebergSearch').value =
        allIceberg.iceberg_id;
    }


    renderIcebergTable();

    return;
  }


  const currentIceberg =
    state.icebergs.find(
      x =>
        String(
          x.id || ''
        )
          .toLowerCase()
          .includes(term)
    );


  if (currentIceberg) {

    navigateTo(
      'riskDetails'
    );


    if (q('riskIcebergSelect')) {

      q('riskIcebergSelect').value =
        currentIceberg.id;
    }


    loadSelectedIcebergDetails(
      'risk'
    );

    return;
  }


  const vessel =
    state.vessels.find(
      x =>
        [
          x.name,
          x.mmsi,
          x.imo,
          x.call_sign
        ].some(
          value =>
            String(
              value || ''
            )
              .toLowerCase()
              .includes(term)
        )
    );


  if (vessel) {

    navigateTo(
      'vesselCatalog'
    );


    if (q('vesselSearch')) {
      q('vesselSearch').value =
        term;
    }


    renderVesselTable();

    return;
  }


  const historical =
    (
      state.historyCatalog
        ?.catalog || []
    ).find(
      x =>
        String(
          x.iceberg_id || ''
        )
          .toLowerCase()
          .includes(term)
    );


  if (historical) {

    navigateTo(
      'historicalSection'
    );


    if (q('historyCatalogSearch')) {

      q('historyCatalogSearch').value =
        historical.iceberg_id;
    }


    renderHistoryCatalog();

    return;
  }


  if (q('globalSearch')) {

    q('globalSearch').setCustomValidity(
      (
        'No matching NAV-X page, iceberg, '
        'historical track, or received AIS vessel.'
      )
    );


    q('globalSearch').reportValidity();


    setTimeout(
      () =>
        q('globalSearch')
          ?.setCustomValidity(''),
      1200,
    );
  }
}
'''.strip()


text = replace_regex_once(
    text,
    (
        r'function globalSearch\(\).*?'
        r'(?=\nfunction toggleAutoRefresh)'
    ),
    GLOBAL_SEARCH + "\n",
    "Global unified iceberg search",
)


# ============================================================
# 12. EXPOSE MODULE FUNCTIONS TO INLINE HTML BUTTONS
# ============================================================

assign_match = re.search(
    r'Object\.assign\(window,\{([^\n]+)\}\);',
    text,
)


if assign_match is None:
    raise RuntimeError(
        "Could not locate Object.assign(window, {...})."
    )


current_names = [
    item.strip()
    for item
    in assign_match.group(1).split(",")
    if item.strip()
]


for required_name in [
    "loadUnifiedIcebergCatalog",
    "openIcebergHistoryFromCatalog",
]:
    if (
        required_name
        not in current_names
    ):
        current_names.append(
            required_name
        )


new_assign = (
    "Object.assign(window,{"
    + ",".join(
        current_names
    )
    + "});"
)


text = (
    text[:assign_match.start()]
    + new_assign
    + text[assign_match.end():]
)

print(
    "UPDATED: Browser-visible "
    "catalog functions"
)


# ============================================================
# 13. FINAL SANITY CHECKS
# ============================================================

required_strings = [
    "/api/data/icebergs/all/catalog?limit=5000",
    "state.allIcebergs",
    "current_usnic_designations",
    "current_byu_designations",
    "openIcebergHistoryFromCatalog",
    "/api/data/icebergs/all/${encodeURIComponent(id)}/track",
    "loadUnifiedIcebergCatalog",
]


for required in required_strings:

    if required not in text:
        raise RuntimeError(
            "Final validation failed. "
            f"Missing: {required}"
        )


# Old USNIC-only table renderer must be gone.
if (
    "rows=state.icebergs.filter"
    in text
):
    raise RuntimeError(
        "Old USNIC-only Iceberg Catalog "
        "renderer still exists."
    )


# ============================================================
# SAVE
# ============================================================

INDEX_FILE.write_text(
    text,
    encoding="utf-8",
)


print()
print("=" * 68)
print("PATCH COMPLETE")
print("=" * 68)

print()
print("Updated:")
print(INDEX_FILE)

print()
print("Backup:")
print(BACKUP_FILE)

print()
print(
    "The navigation map still uses current USNIC "
    "positions only."
)

print(
    "The Iceberg Catalog now uses the unified "
    "current + supplemental + historical database."
)

print()
print("Next:")
print(
    "1. Restart Uvicorn"
)
print(
    "2. Ctrl+F5 in browser"
)
print(
    "3. Open Unified Iceberg Catalog"
)