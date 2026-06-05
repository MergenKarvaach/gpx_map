import streamlit as st
import gpxpy
import h3
import json
import os
from datetime import datetime
import folium
from folium import GeoJson, GeoJsonTooltip, Element
from streamlit_folium import st_folium

SAVE_FILE = "visited_hexes_11.json"
RESOLUTION = 11
parse = lambda t: datetime.fromisoformat(t) if t else None


def load_db():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_db(db):
    with open(SAVE_FILE, "w") as f:
        json.dump(db, f, indent=2)


def interpolate(lat1, lon1, lat2, lon2, steps=10):
    return [
        (
            lat1 + (lat2 - lat1) * i / steps,
            lon1 + (lon2 - lon1) * i / steps,
        )
        for i in range(steps + 1)
    ]


def process_gpx(db, file_name, gpx_text):
    gpx = gpxpy.parse(gpx_text)
    last_hex = None

    for track in gpx.tracks:
        for segment in track.segments:

            pts = segment.points

            for i in range(len(pts) - 1):

                p1 = pts[i]
                p2 = pts[i + 1]

                if p1.latitude is None or p1.longitude is None:
                    continue
                if p2.latitude is None or p2.longitude is None:
                    continue

                path = interpolate(
                    p1.latitude,
                    p1.longitude,
                    p2.latitude,
                    p2.longitude,
                    steps=20
                )

                for lat, lon in path:

                    hex_id = h3.latlng_to_cell(lat, lon, RESOLUTION)
                    if hex_id == last_hex:
                        continue
                    last_hex = hex_id

                    ts = p1.time.isoformat() if p1.time else None

                    if hex_id not in db:
                        db[hex_id] = {
                            "source_files": {},
                            "first_seen": ts,
                            "last_seen": ts
                        }

                    if file_name not in db[hex_id]["source_files"]:
                        db[hex_id]["source_files"][file_name] = ts

                    t = parse(ts)

                    if t:
                        first = parse(db[hex_id]["first_seen"])
                        last = parse(db[hex_id]["last_seen"])

                        if first is None or t < first:
                            db[hex_id]["first_seen"] = ts

                        if last is None or t > last:
                            db[hex_id]["last_seen"] = ts

    for h in db:
        db[h]["visits"] = len(db[h]["source_files"])

    return db


def delete_gpx(db, gpx_name):
    to_delete = []

    for hex_id, data in db.items():
        sf = data.get("source_files", {})

        if gpx_name in sf:
            del sf[gpx_name]

        if len(sf) == 0:
            to_delete.append(hex_id)

    for h in to_delete:
        del db[h]

    return db


def format_trips(source_files):
    items = []

    for name, ts in source_files.items():

        if ts is None:
            continue

        items.append((ts, name))

    items.sort()

    return "<br>".join(f"{ts} → {name}" for ts, name in items)


def hex_to_feature(hex_id, data):
    boundary = h3.cell_to_boundary(hex_id)

    coords = [[lon, lat] for lat, lon in boundary]

    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [coords]
        },
        "properties": {
            "hex": hex_id,
            "trips": list(data.get("source_files", {}).keys()),
            "source": format_trips(data.get("source_files", {})),
            "first_seen": data.get("first_seen"),
            "last_seen": data.get("last_seen"),
            "visits": data.get("visits", 1)
        }
    }


def render_map(db):
    if not db:
        return None

    def weighted_center(db):
        lat_sum = 0
        lon_sum = 0
        weight_sum = 0

        for hex_id, data in db.items():
            lat, lon = h3.cell_to_latlng(hex_id)
            w = data.get("visits", 1)

            lat_sum += lat * w
            lon_sum += lon * w
            weight_sum += w

        return [lat_sum / weight_sum, lon_sum / weight_sum]

    center = weighted_center(db)

    m = folium.Map(
        location=center,
        zoom_start=14,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr=" ",
        control_scale=True,
        prefer_canvas=True,
        attribution_control=False
    )

    map_id = m.get_name()

    center_lat, center_lon = center

    center_button = f"""
    <style>
    #centerBtn {{
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 9999;

        background: rgba(20, 20, 20, 0.85);
        color: white;

        padding: 10px 16px;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);

        cursor: pointer;
        user-select: none;

        font-family: Arial;
        font-size: 14px;
    }}

    #centerBtn:active {{
        transform: translateX(-50%) scale(0.95);
    }}
    </style>

    <div id="centerBtn" onclick="centerMap(event)">
    Center Map
    </div>

    <script>
    function centerMap(e) {{
        e.preventDefault();

        var map = {map_id};
        map.setView([{center_lat}, {center_lon}], 14);

        // fix "stuck cursor / drag state"
        map.dragging.enable();
        map.scrollWheelZoom.enable();
    }}
    </script>
    """

    m.get_root().html.add_child(Element(center_button))

    features = []

    for hex_id, data in db.items():

        features.append(hex_to_feature(hex_id, data))

    geojson_data = {
        "type": "FeatureCollection",
        "features": features
    }

    GeoJson(
        geojson_data,
        style_function=lambda f: {
            "fillColor": "#00FFFF",
            "color": "#000000",
            "weight": 0,
            "fillOpacity": min(
                0.25 + f["properties"].get("visits", 1) * 0.25,
                1
            ),
        },
        highlight_function=lambda f: {
            "fillColor": "#FFFFFF",
            "color": "#FFFFFF",
            "weight": 2,
            "fillOpacity": 0.7,
        },
        tooltip=GeoJsonTooltip(
            fields=["source", "hex", "first_seen", "last_seen", "visits"],
            aliases=["Trips:", "Hex:", "First seen:", "Last seen:", "Visits:"],
            sticky=True,
            localize=False
        ),
        popup=folium.GeoJsonPopup(
            fields=["source", "hex", "first_seen", "last_seen", "visits"],
            aliases=["Trip:", "Hex:", "First:", "Last:", "Visits:"]
        )
    ).add_to(m)

    map_id = m.get_name()

    trip_js = f"""
    <script>

    setTimeout(() => {{

        var map = {map_id};

        let geoLayer = null;

        // find ONLY GeoJSON layer
        map.eachLayer(function(layer) {{
            if (layer instanceof L.GeoJSON) {{
                geoLayer = layer;
            }}
        }});

        if (!geoLayer) return;

        let trips = new Set();

        geoLayer.eachLayer(function(l) {{
            let t = l.feature?.properties?.trips || [];
            t.forEach(x => trips.add(x));
        }});

        let control = L.control({{position: 'topright'}});
        control.onAdd = function() {{
            let div = L.DomUtil.create('div', '');
            div.innerHTML = `
                <select id="tripSelect" style="padding:6px;">
                    <option value="ALL">ALL</option>
                </select>
            `;
            return div;
        }};
        control.addTo(map);

        let select = document.getElementById("tripSelect");

        Array.from(trips).sort().forEach(t => {{
            let opt = document.createElement("option");
            opt.value = t;
            opt.text = t;
            select.appendChild(opt);
        }});

        function applyFilter(value) {{
            geoLayer.eachLayer(function(l) {{

                let t = l.feature?.properties?.trips || [];

                if (value === "ALL" || t.includes(value)) {{
                    l.addTo(map);
                }} else {{
                    map.removeLayer(l);
                }}
            }});
        }}

        select.addEventListener("change", function(e) {{
            applyFilter(e.target.value);
        }});

    }}, 1200);

    </script>
    """

    m.get_root().html.add_child(Element(trip_js))

    return m


st.title("GPX Hex Database Manager")

db = load_db()

all_times = []


for v in db.values():
    if v.get("first_seen"):
        all_times.append(parse(v["first_seen"]))
    if v.get("last_seen"):
        all_times.append(parse(v["last_seen"]))


all_trips = set()

for hex_id, data in db.items():
    all_trips.update(data.get("source_files", {}).keys())

trip_list = sorted(all_trips)

selected_trips = st.multiselect(
    "Select Trips",
    trip_list
)

st.caption("Currently displaying: **" + ", ".join(selected_trips) + "**")


def filter_db_by_trips(db, trips):

    if not trips:
        return db

    filtered = {}

    for hex_id, data in db.items():
        sf = data.get("source_files", {})

        matched = set(sf.keys()) & set(trips)

        if matched:
            filtered[hex_id] = {
                **data,
                "source_files": {t: sf[t] for t in matched},
                "visits": len(matched)
            }

    return filtered


uploaded = st.file_uploader("Upload GPX", type=["gpx"])

if uploaded:
    name = uploaded.name
    text = uploaded.read().decode("utf-8")

    db = process_gpx(db, name, text)
    save_db(db)
    st.success(f"Processed {name}")


all_files = set()
for v in db.values():
    all_files.update(v.get("source_files", {}).keys())

delete_choice = st.selectbox("Delete GPX from DB", sorted(all_files) if all_files else [])

if st.button("Delete"):
    db = delete_gpx(db, delete_choice)
    save_db(db)
    st.warning(f"Deleted {delete_choice}")


st.write(f"Hex count: {len(db)}")
st.write(f"Tracked GPX files: {len(all_files)}")


filtered_db = filter_db_by_trips(db, selected_trips)

m = render_map(filtered_db)

if m:
    st_folium(m, width=1000, height=650)

if st.button("Save Map"):
    st.success("Map saved as map.html")
    m.save("map.html")
