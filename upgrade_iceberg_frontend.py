from pathlib import Path
import re
import shutil
import sys


# ============================================================
# NAV-X FRONTEND ICEBERG CATALOG UPGRADE
#
# This script updates only:
# - Home iceberg count
# - Iceberg Catalog page
# - Unified catalog loading
#
# It intentionally DOES NOT change:
# - USNIC current map hazards
# - routing
# - AIS
# - GPS
# - CMEMS
# - ERA5
# - NSIDC
# - ML / forecast logic
# ============================================================


ROOT = Path(__file__).resolve().parent

INDEX_FILE = (
    ROOT
    / "src"
    / "api"
    / "static"
    / "index.html"
)

BACKUP_FILE = (
    ROOT
    / "src"
    / "api"
    / "static"
    / "index.before_iceberg_catalog_upgrade.html"
)


# ============================================================
# CHECK FILE
# ============================================================

if not INDEX_FILE.exists():
    print()
    print("ERROR")
    print("index.html was not found:")
    print(INDEX_FILE)
    print()

    sys.exit(1)


# ============================================================
# BACKUP
# ============================================================

if not BACKUP_FILE.exists():

    shutil.copy2(
        INDEX_FILE,
        BACKUP_FILE,
    )

    print(
        "Backup created:",
        BACKUP_FILE,
    )

else:

    print(
        "Backup already exists:",
        BACKUP_FILE,
    )


text = INDEX_FILE.read_text(
    encoding="utf-8"
)


# ============================================================
# SAFE REPLACEMENT HELPER
# ============================================================

def replace_once(
    source: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:

    result, count = re.subn(
        pattern,
        lambda match: replacement,
        source,
        count=1,
        flags=re.DOTALL,
    )

    if count != 1:

        print()
        print(
            f"ERROR: Could not safely replace {label}"
        )

        print(
            f"Matches found: {count}"
        )

        print(
            "Original index.html has NOT been deleted."
        )

        sys.exit(1)

    print(
        f"UPDATED: {label}"
    )

    return result


# ============================================================
# 1. HOME FEATURE CARD WORDING
# ============================================================

text = text.replace(
    "<strong>Physics + ML Forecasting</strong>",
    "<strong>Iceberg Intelligence</strong>",
    1,
)


text = text.replace(
    (
        "<p>Official USNIC transitions train a gated ML "
        "residual model on top of the physics baseline.</p>"
    ),
    (
        "<p>Unified real iceberg catalogue with official current "
        "observations, supplemental current positions and "
        "published historical tracks.</p>"
    ),
    1,
)


print(
    "UPDATED: Home iceberg card"
)


# ============================================================
# 2. PAGE TITLE / SIDEBAR METADATA
# ============================================================

text = re.sub(
    (
        r"icebergCatalog:\["
        r"'Iceberg Catalog',"
        r"'[^']*'"
        r"\]"
    ),
    (
        "icebergCatalog:["
        "'Unified Iceberg Catalog',"
        "'USNIC official current, BYU/SCP supplemental current "
        "and BYU/NIC historical iceberg observations.'"
        "]"
    ),
    text,
    count=1,
)


print(
    "UPDATED: Iceberg page title"
)


# ============================================================
# 3. COMPLETE ICEBERG CATALOG HTML
# ============================================================

CATALOG_HTML = r'''
<section class="page-view" id="icebergCatalog">

  <div class="page-inner">

    <div class="page-heading">

      <div>

        <h2>
          Unified Iceberg Catalog
        </h2>

        <p>
          Source-labelled Antarctic iceberg records combining
          authoritative current USNIC observations,
          supplemental BYU/SCP ASCAT + OSCAT-2 observations,
          and published BYU/NIC historical tracks.
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

      <div>
        ICE
      </div>

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
      style="
        grid-template-columns:
        repeat(5,minmax(0,1fr));
        margin-bottom:16px
      "
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
          Stored designations
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
          Source-labelled positions
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
          BYU/SCP
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
            placeholder="Search A23A, B15, A68, source or status…"
            oninput="renderIcebergTable()"
          >


          <button
            class="btn btn-secondary btn-small"
            onclick="
              document.getElementById(
                'icebergSearch'
              ).value='';

              renderIcebergTable();
            "
          >
            Clear
          </button>


          <button
            class="btn btn-secondary btn-small"
            onclick="loadHistoryCatalog()"
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

                <th>
                  Designation
                </th>

                <th>
                  Status
                </th>

                <th>
                  First Observation
                </th>

                <th>
                  Latest Observation
                </th>

                <th>
                  Positions
                </th>

                <th>
                  Sources
                </th>

                <th>
                  Historical Track
                </th>

                <th>
                  Actions
                </th>

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

          USNIC remains the authoritative current source.
          BYU/SCP is displayed as supplemental current data.
          Historical BYU/NIC positions are available for
          research and track replay and are not automatically
          treated as present-day navigation hazards.

        </div>

      </div>

    </article>

  </div>

</section>
'''.strip()


text = replace_once(
    text,
    (
        r'<section class="page-view" '
        r'id="icebergCatalog">'
        r'.*?'
        r'</section>\s*'
        r'(?='
        r'<section class="page-view" '
        r'id="vesselCatalog">'
        r')'
    ),
    CATALOG_HTML + "\n      ",
    "Iceberg Catalog HTML",
)


# ============================================================
# 4. KEEP CURRENT USNIC LOAD SEPARATE
# ============================================================

LOAD_ICEBERGS = r'''
async function loadIcebergs() {

  /*
   * CURRENT NAVIGATION LAYER
   *
   * This function intentionally continues to use
   * /api/data/icebergs.
   *
   * state.icebergs therefore contains ONLY the current
   * official USNIC navigation observations.
   *
   * Historical observations are never inserted into this
   * array and therefore cannot accidentally become hazards.
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
            Number(
              c[1]
            ),

          lon:
            normLon(
              Number(
                c[0]
              )
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


    renderIceMarkers();

    populateIcebergDetailSelect();

    renderHomeStatus();

    updateRouteDependentPanels();


    if (
      state.origin
    ) {

      updateNearby();
    }

  }

  catch (e) {

    console.error(
      'Current USNIC iceberg feed unavailable:',
      e
    );


    state.icebergs = [];

    state.icebergMeta = null;


    renderIceMarkers();

    populateIcebergDetailSelect();

    renderHomeStatus();

    updateRouteDependentPanels();
  }
}
'''.strip()


text = replace_once(
    text,
    (
        r'async function loadIcebergs\(\)'
        r'.*?'
        r'(?=\nfunction aisScanReference)'
    ),
    LOAD_ICEBERGS + "\n",
    "Current USNIC loader",
)


# ============================================================
# 5. LOAD FULL 649-DESIGNATION CATALOG
# ============================================================

LOAD_HISTORY_CATALOG = r'''
async function loadHistoryCatalog() {

  try {

    /*
     * Unified database endpoint.
     *
     * This is separate from the current USNIC navigation
     * endpoint used by loadIcebergs().
     */

    const h = await getJson(
      '/api/data/icebergs/all/catalog?limit=5000'
    );


    state.historyCatalog =
      h;


    const unique =
      Number(
        h.unique_icebergs || 0
      );


    const observations =
      Number(
        h.observation_rows || 0
      );


    const historical =
      Number(
        h.historical_rows || 0
      );


    const usnicCurrent =
      Number(
        h.current_usnic_designations || 0
      );


    const byuCurrent =
      Number(
        h.current_byu_designations || 0
      );


    if (
      q('historyCatalogStatus')
    ) {

      q(
        'historyCatalogStatus'
      ).textContent =

        `${unique.toLocaleString()} designations · ` +

        `${observations.toLocaleString()} stored positions · ` +

        `${historical.toLocaleString()} historical · ` +

        `${usnicCurrent.toLocaleString()} official-current USNIC · ` +

        `${byuCurrent.toLocaleString()} supplemental-current BYU/SCP`;
    }


    if (
      q('icebergSourceText')
    ) {

      q(
        'icebergSourceText'
      ).textContent =

        `${unique.toLocaleString()} unique iceberg designations · ` +

        `${observations.toLocaleString()} real stored observations · ` +

        `${usnicCurrent.toLocaleString()} official-current USNIC · ` +

        `${byuCurrent.toLocaleString()} supplemental-current BYU/SCP · ` +

        `${historical.toLocaleString()} historical positions`;
    }


    if (
      q('catalogUniqueCount')
    ) {

      q(
        'catalogUniqueCount'
      ).textContent =
        unique.toLocaleString();
    }


    if (
      q('catalogObservationCount')
    ) {

      q(
        'catalogObservationCount'
      ).textContent =
        observations.toLocaleString();
    }


    if (
      q('catalogUsnicCount')
    ) {

      q(
        'catalogUsnicCount'
      ).textContent =
        usnicCurrent.toLocaleString();
    }


    if (
      q('catalogByuCurrentCount')
    ) {

      q(
        'catalogByuCurrentCount'
      ).textContent =
        byuCurrent.toLocaleString();
    }


    if (
      q('catalogHistoricalCount')
    ) {

      q(
        'catalogHistoricalCount'
      ).textContent =
        historical.toLocaleString();
    }


    renderHistoryCatalog();

    renderIcebergTable();

    renderHomeStatus();

  }

  catch (e) {

    console.error(
      'Unified iceberg catalogue unavailable:',
      e
    );


    state.historyCatalog =
      null;


    if (
      q('historyCatalogStatus')
    ) {

      q(
        'historyCatalogStatus'
      ).textContent =
        `Historical catalogue unavailable: ${e.message}`;
    }


    if (
      q('historyCatalogTable')
    ) {

      q(
        'historyCatalogTable'
      ).innerHTML =
        (
          '<tr>' +
          '<td colspan="6">' +
          'HISTORICAL DATA UNAVAILABLE' +
          '</td>' +
          '</tr>'
        );
    }


    if (
      q('icebergSourceText')
    ) {

      q(
        'icebergSourceText'
      ).textContent =
        'Unified iceberg database unavailable.';
    }


    renderIcebergTable();

    renderHomeStatus();
  }
}
'''.strip()


text = replace_once(
    text,
    (
        r'async function loadHistoryCatalog\(\)'
        r'.*?'
        r'(?=\nfunction renderHistoryCatalog)'
    ),
    LOAD_HISTORY_CATALOG + "\n",
    "Unified catalog loader",
)


# ============================================================
# 6. ICEBERG CATALOG TABLE
# ============================================================

RENDER_ICEBERG_TABLE = r'''
function renderIcebergTable() {

  const search = (
    q('icebergSearch')
      ?.value || ''
  )
    .trim()
    .toLowerCase();


  const catalog =
    state.historyCatalog
      ?.catalog || [];


  const rows =
    catalog.filter(item => {

      if (
        !search
      ) {

        return true;
      }


      const fields = [

        item.iceberg_id,

        item.current_status,

        ...(
          Array.isArray(
            item.sources
          )
            ? item.sources
            : []
        )

      ];


      return fields.some(
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


  const table =
    q('icebergTable');


  if (
    !table
  ) {

    return;
  }


  if (
    !state.historyCatalog
  ) {

    table.innerHTML =
      (
        '<tr>' +
        '<td colspan="8">' +
        'LOADING UNIFIED ICEBERG DATABASE…' +
        '</td>' +
        '</tr>'
      );

    return;
  }


  table.innerHTML =
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


          let statusText =
            status;


          let statusClass =
            '';


          if (
            status ===
            'OFFICIAL_CURRENT'
          ) {

            statusText =
              'OFFICIAL CURRENT';

            statusClass =
              'risk-low';
          }


          else if (
            status ===
            'SUPPLEMENTAL_CURRENT'
          ) {

            statusText =
              'SUPPLEMENTAL CURRENT';

            statusClass =
              'risk-moderate';
          }


          else if (
            status ===
            'HISTORICAL_ONLY'
          ) {

            statusText =
              'HISTORICAL ONLY';
          }


          const first =
            item.first_observed_at
              ? String(
                  item.first_observed_at
                ).slice(
                  0,
                  10
                )
              : 'N/A';


          const latest =
            item.last_observed_at
              ? String(
                  item.last_observed_at
                ).slice(
                  0,
                  10
                )
              : 'N/A';


          const positions =
            Number(
              item.observation_count ||
              0
            );


          const sources =
            Array.isArray(
              item.sources
            )
              ? item.sources.join(
                  ', '
                )
              : 'N/A';


          const history =
            item.has_historical_track
              ? 'AVAILABLE'
              : 'NO HISTORICAL TRACK';


          const currentMapButton =
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
                  ${esc(statusText)}
                </strong>

                ${
                  item.currently_in_usnic_database &&
                  item.currently_in_byu_scp_database

                    ? `
                      <br>
                      <span class="hint">
                        Also in BYU/SCP current data
                      </span>
                    `

                    : ''
                }

              </td>


              <td>
                ${esc(first)}
              </td>


              <td>
                ${esc(latest)}
              </td>


              <td>

                <strong>
                  ${positions.toLocaleString()}
                </strong>

              </td>


              <td>
                ${esc(sources)}
              </td>


              <td>
                ${esc(history)}
              </td>


              <td>

                <div
                  class="actions"
                  style="margin:0"
                >

                  ${currentMapButton}


                  <button
                    class="btn btn-secondary btn-small"
                    onclick="viewHistoricalTrack('${esc(id)}')"
                  >
                    Full Track
                  </button>

                </div>

              </td>

            </tr>

          `;

        }).join('')

      : (
          '<tr>' +
          '<td colspan="8">' +
          'NO MATCHING ICEBERG RECORDS' +
          '</td>' +
          '</tr>'
        );
}
'''.strip()


text = replace_once(
    text,
    (
        r'function renderIcebergTable\(\)'
        r'.*?'
        r'(?=\nfunction renderVesselTable)'
    ),
    RENDER_ICEBERG_TABLE + "\n",
    "Unified Iceberg Catalog renderer",
)


# ============================================================
# 7. HOME COUNT
# ============================================================

RENDER_HOME = r'''
function renderHomeStatus() {

  /*
   * state.icebergs = official current USNIC map hazards
   *
   * state.historyCatalog = entire source-labelled
   * iceberg database.
   */

  const currentUsnic =
    Number(
      state.icebergs
        ?.length || 0
    );


  const totalCatalog =
    Number(
      state.historyCatalog
        ?.unique_icebergs || 0
    );


  const observations =
    Number(
      state.historyCatalog
        ?.observation_rows || 0
    );


  const byuCurrent =
    Number(
      state.historyCatalog
        ?.current_byu_designations || 0
    );


  const vs =
    Number(
      state.vessels
        ?.length || 0
    );


  const ds =
    state.health
      ?.datasets || {};


  # ----------------------------------------------------------
  # NOTE:
  # This is JavaScript inserted as text.
  # The Python comments above are removed below.
  # ----------------------------------------------------------
}
'''.strip()


# Build this separately so there can be no accidental
# Python-style comment inside JavaScript.

RENDER_HOME = r'''
function renderHomeStatus() {

  const currentUsnic =
    Number(
      state.icebergs
        ?.length || 0
    );


  const totalCatalog =
    Number(
      state.historyCatalog
        ?.unique_icebergs || 0
    );


  const observations =
    Number(
      state.historyCatalog
        ?.observation_rows || 0
    );


  const byuCurrent =
    Number(
      state.historyCatalog
        ?.current_byu_designations || 0
    );


  const vessels =
    Number(
      state.vessels
        ?.length || 0
    );


  const datasets =
    state.health
      ?.datasets || {};


  if (
    q('homeIcebergCount')
  ) {

    if (
      totalCatalog > 0
    ) {

      q(
        'homeIcebergCount'
      ).textContent =

        `${totalCatalog.toLocaleString()} catalog · ` +

        `${currentUsnic.toLocaleString()} current`;


      q(
        'homeIcebergCount'
      ).title =

        `${totalCatalog.toLocaleString()} unique iceberg designations · ` +

        `${observations.toLocaleString()} stored observations · ` +

        `${currentUsnic.toLocaleString()} official-current USNIC · ` +

        `${byuCurrent.toLocaleString()} supplemental-current BYU/SCP`;
    }


    else if (
      currentUsnic > 0
    ) {

      q(
        'homeIcebergCount'
      ).textContent =

        `${currentUsnic.toLocaleString()} current`;
    }


    else {

      q(
        'homeIcebergCount'
      ).textContent =
        'DATA UNAVAILABLE';
    }
  }


  if (
    q('homeAisCount')
  ) {

    q(
      'homeAisCount'
    ).textContent =

      vessels
        ? String(
            vessels
          )
        : 'NO CURRENT POSITIONS';
  }


  if (
    q('homeSurfaceStatus')
  ) {

    q(
      'homeSurfaceStatus'
    ).textContent =

      state.health
        ?.navigation_surface
        ?.available

        ? 'READY'

        : 'UNAVAILABLE';
  }


  if (
    q('homeDatasetStatus')
  ) {

    const available =
      Object.values(
        datasets
      )
        .filter(
          Boolean
        )
        .length;


    const total =
      Object.keys(
        datasets
      )
        .length;


    q(
      'homeDatasetStatus'
    ).textContent =

      total
        ? `${available}/${total} loaded`
        : 'checking…';
  }


  if (
    q('homeDataMode')
  ) {

    q(
      'homeDataMode'
    ).textContent =

      state.provenance
        ?.data_mode

      ||

      'Checking scientific provenance…';
  }
}
'''.strip()


text = replace_once(
    text,
    (
        r'function renderHomeStatus\(\)'
        r'.*?'
        r'(?=\nfunction activeRoute)'
    ),
    RENDER_HOME + "\n",
    "Home iceberg database counter",
)


# ============================================================
# 8. UPDATE HISTORICAL TABLE STATUS TEXT
# ============================================================

text = text.replace(
    "<th>Current USNIC?</th>",
    "<th>Current state</th>",
    1,
)


# ============================================================
# 9. FINAL VALIDATION
# ============================================================

checks = {

    "Unified endpoint":
        "/api/data/icebergs/all/catalog?limit=5000",

    "649-capable catalog":
        "state.historyCatalog",

    "Current USNIC separation":
        "/api/data/icebergs",

    "Catalog total":
        "catalogUniqueCount",

    "Official current total":
        "catalogUsnicCount",

    "BYU current total":
        "catalogByuCurrentCount",

    "Historical total":
        "catalogHistoricalCount",

    "Home catalog count":
        "totalCatalog",

}


for label, value in checks.items():

    if value not in text:

        print()
        print(
            f"VALIDATION FAILED: {label}"
        )

        print(
            f"Missing: {value}"
        )

        sys.exit(1)


# Ensure exactly one main catalog section exists.

catalog_section_count = (
    text.count(
        'id="icebergCatalog"'
    )
)


if catalog_section_count != 1:

    print()
    print(
        "VALIDATION FAILED:"
    )

    print(
        "Expected exactly one icebergCatalog section."
    )

    print(
        "Found:",
        catalog_section_count,
    )

    sys.exit(1)


# ============================================================
# 10. WRITE COMPLETE UPDATED INDEX.HTML
# ============================================================

INDEX_FILE.write_text(
    text,
    encoding="utf-8",
)


print()
print(
    "=" * 72
)

print(
    "NAV-X ICEBERG FRONTEND UPGRADE COMPLETE"
)

print(
    "=" * 72
)

print()

print(
    "Updated file:"
)

print(
    INDEX_FILE
)

print()

print(
    "Backup file:"
)

print(
    BACKUP_FILE
)

print()

print(
    "EXPECTED DATABASE VALUES FROM YOUR CURRENT BACKEND:"
)

print(
    "Unique iceberg designations : 649"
)

print(
    "Total observations          : 516,411"
)

print(
    "Historical positions        : 516,307"
)

print(
    "Official current USNIC      : 33"
)

print(
    "Supplemental BYU/SCP        : 38"
)

print()

print(
    "IMPORTANT:"
)

print(
    "The Live Map and routing hazard engine still use "
    "the official-current USNIC feed only."
)

print(
    "Historical records are displayed in the catalogue "
    "and track views, not as present-day hazards."
)

print()