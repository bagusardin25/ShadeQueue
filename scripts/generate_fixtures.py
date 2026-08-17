"""One-shot generator for ShadeQueue deterministic fixtures.

Writes fixtures/ at the repository root. Stdlib only so it can run on any Python.
All values are synthetic and exist solely to exercise the adapter contract.
"""

import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures"
OUT.mkdir(exist_ok=True)

# stop_id, name, context, lon, lat, shelters, ridership, exceedance_hours, svi
STOPS = [
    ("SQ-101", "Central Ave & Roosevelt St", "Arts District", -112.07392, 33.45873, 0, 1640, 7.8, 0.61),
    ("SQ-102", "Central Ave & McDowell Rd", "Library approach", -112.07383, 33.46512, 0, 1810, 6.1, 0.72),
    ("SQ-103", "Central Ave & Thomas Rd", "Medical campus", -112.07369, 33.48071, 0, 1490, 9.4, 0.86),
    ("SQ-104", "Central Ave & Osborn Rd", "Midtown transfer", -112.07353, 33.48754, 0, 1370, 10.2, 0.91),
    ("SQ-105", "Central Ave & Indian School Rd", "Northbound platform", -112.07332, 33.49505, 0, 2025, 5.7, 0.58),
    ("SQ-106", "Central Ave & Campbell Ave", "Neighborhood connector", -112.0731, 33.50152, 0, 1080, 11.6, 0.94),
    ("SQ-107", "Central Ave & Highland Ave", "Retail frontage", -112.07286, 33.50582, 1, 1330, 8.8, 0.67),
    ("SQ-108", "7th Ave & Van Buren St", "West transfer", -112.08292, 33.45142, 0, 1260, 10.7, 0.82),
    ("SQ-109", "7th Ave & Roosevelt St", "Community services", -112.08267, 33.45895, 0, 930, 12.4, 0.96),
    ("SQ-110", "7th Ave & McDowell Rd", "Southbound platform", -112.08242, 33.46533, 0, 1760, 6.4, 0.69),
    ("SQ-111", "7th Ave & Thomas Rd", "Hospital connector", -112.08198, 33.48083, 0, 1180, 10.9, 0.88),
    ("SQ-112", "7th Ave & Osborn Rd", "School crossing", -112.08171, 33.48771, 0, 990, 11.8, 0.92),
    ("SQ-113", "7th Ave & Indian School Rd", "Civic center approach", -112.08143, 33.49516, 0, 1580, 7.1, 0.74),
    ("SQ-114", "7th Ave & Camelback Rd", "North transfer", -112.08109, 33.50914, 1, 2180, 5.2, 0.54),
    ("SQ-115", "1st Ave & Jefferson St", "Downtown connector", -112.07592, 33.44651, 0, 1875, 6.8, 0.63),
    ("SQ-116", "1st Ave & Fillmore St", "Senior services", -112.0756, 33.45412, 0, 850, 12.8, 0.98),
]

# Grid bounds sit strictly inside the predeclared AOI envelope in app/domain/aoi.py.
LON_MIN, LON_MAX = -112.0940, -112.0660
LAT_MIN, LAT_MAX = 33.4410, 33.5140
CELL = 0.0025


def frange(start, stop, step):
    n = round((stop - start) / step)
    return [round(start + i * step, 7) for i in range(n)]


def nearest_stop(lon, lat):
    best, best_d = None, None
    for s in STOPS:
        d = math.hypot(lon - s[3], lat - s[4])
        if best_d is None or d < best_d:
            best, best_d = s, d
    return best, best_d


def build_heat_features():
    features = []
    lons = frange(LON_MIN, LON_MAX, CELL)
    lats = frange(LAT_MIN, LAT_MAX, CELL)
    max_d = 0.02
    for i, lon in enumerate(lons):
        for j, lat in enumerate(lats):
            clon, clat = lon + CELL / 2, lat + CELL / 2
            stop, dist = nearest_stop(clon, clat)
            decay = min(1.0, dist / max_d)
            value = round(max(0.0, stop[7] * (1.0 - 0.35 * decay)), 2)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [round(lon, 7), round(lat, 7)],
                            [round(lon + CELL, 7), round(lat, 7)],
                            [round(lon + CELL, 7), round(lat + CELL, 7)],
                            [round(lon, 7), round(lat + CELL, 7)],
                            [round(lon, 7), round(lat, 7)],
                        ]]
                    },
                    "properties": {
                        "cell_id": f"c{i:03d}{j:03d}",
                        "exceedance_hours": value,
                    },
                }
            )
    return features, lons, lats


def force_stop_cells(features, lons, lats):
    """Guarantee the cell containing each stop carries that stop's exact value."""
    index = {}
    for idx, feature in enumerate(features):
        ring = feature["geometry"]["coordinates"][0]
        index[(ring[0][0], ring[0][1])] = idx

    forced = 0
    for s in STOPS:
        lon, lat = s[3], s[4]
        ci = math.floor((lon - LON_MIN) / CELL)
        cj = math.floor((lat - LAT_MIN) / CELL)
        key = (lons[ci], lats[cj])
        idx = index[key]
        ring = features[idx]["geometry"]["coordinates"][0]
        assert ring[0][0] <= lon <= ring[1][0], (s[0], "lon outside cell")
        assert ring[0][1] <= lat <= ring[2][1], (s[0], "lat outside cell")
        features[idx]["properties"]["exceedance_hours"] = s[7]
        features[idx]["properties"]["anchor_stop_id"] = s[0]
        forced += 1
    return forced


def build_svi_tracts():
    half_lon, half_lat = 0.0035, 0.0020
    tracts = []
    for n, s in enumerate(STOPS, start=1):
        lon, lat = s[3], s[4]
        minx, maxx = round(lon - half_lon, 7), round(lon + half_lon, 7)
        miny, maxy = round(lat - half_lat, 7), round(lat + half_lat, 7)
        tracts.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[
                        [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny],
                    ]]],
                },
                "properties": {
                    # Synthetic GEOID shaped like a real 11-digit census tract id
                    # (state 04 = Arizona, county 013 = Maricopa). Not a real tract.
                    "GEOID": f"0401391{n:04d}",
                    "RPL_THEMES": s[8],
                    "anchor_stop_id": s[0],
                },
                "_bbox": (minx, miny, maxx, maxy),
            }
        )

    # No two tracts may overlap, or the stop-to-tract join stops being deterministic.
    for a in range(len(tracts)):
        for b in range(a + 1, len(tracts)):
            ax0, ay0, ax1, ay1 = tracts[a]["_bbox"]
            bx0, by0, bx1, by1 = tracts[b]["_bbox"]
            overlap = ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1
            assert not overlap, f"tracts overlap: {tracts[a]['properties']['GEOID']} / {tracts[b]['properties']['GEOID']}"

    # Each stop must fall inside exactly one tract.
    for s in STOPS:
        hits = [t for t in tracts if t["_bbox"][0] <= s[3] <= t["_bbox"][2] and t["_bbox"][1] <= s[4] <= t["_bbox"][3]]
        assert len(hits) == 1, f"{s[0]} hit {len(hits)} tracts"
        assert hits[0]["properties"]["RPL_THEMES"] == s[8]

    for t in tracts:
        del t["_bbox"]
    return tracts


def write(name, payload):
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


features, lons, lats = build_heat_features()
forced = force_stop_cells(features, lons, lats)
tracts = build_svi_tracts()

ACTIVITY_ID = "fixture-activity-central-phoenix-0001"

write(
    "fortyguard_status_completed.json",
    {
        "activity_id": ACTIVITY_ID,
        "status": "completed",
        "analytic_type": "exceedance",
        "threshold": 40.0,
        "direction": "above",
        "granularity": 100,
        "map_data": {"type": "FeatureCollection", "features": features},
    },
)

write(
    "fortyguard_submit_accepted.json",
    {"activity_id": ACTIVITY_ID, "status": "queued"},
)

write(
    "fortyguard_status_processing.json",
    {"activity_id": ACTIVITY_ID, "status": "processing", "progress": 0.4},
)

write(
    "fortyguard_status_failed.json",
    {
        "activity_id": ACTIVITY_ID,
        "status": "failed",
        "error": "The requested analysis window is not available for this area.",
    },
)

write(
    "fortyguard_status_malformed.json",
    {"activity_id": ACTIVITY_ID, "state": "banana", "map_data": {"type": "FeatureCollection"}},
)

write(
    "bus_stops_demo.geojson",
    {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s[3], s[4]]},
                "properties": {
                    "STOP_ID": s[0],
                    "LOCATION_NAME": f"{s[1]} ({s[2]})",
                    "NBR_SHELTERS": s[5],
                    "RIDERSHIP": s[6],
                },
            }
            for s in STOPS
        ],
    },
)

write("svi_tracts_demo.geojson", {"type": "FeatureCollection", "features": tracts})

print(f"\nheat cells: {len(features)} ({len(lons)} x {len(lats)}), forced stop cells: {forced}")
print(f"svi tracts: {len(tracts)}")
values = [f['properties']['exceedance_hours'] for f in features]
print(f"exceedance range: {min(values)} .. {max(values)}")
