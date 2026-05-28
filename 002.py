import streamlit as st
import gpxpy
import h3
import json
import os
from datetime import datetime
import folium
from folium import GeoJson, GeoJsonTooltip

SAVE_FILE = "visited_hexes_11.json"
RESOLUTION = 11
parse = lambda t: datetime.fromisoformat(t) if t else None


# ----------------------------
# LOAD DB
# ----------------------------
def load_db():
    def parse(t):
        return datetime.fromisoformat(t) if t else None
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_db(db):
    with open(SAVE_FILE, "w") as f:
        json.dump(db, f, indent=2)


# ----------------------------
# GPX PROCESSING
# ----------------------------
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

    for track in gpx.tracks:
        for segment in track.segments:

            pts = segment.points

            for i in range(len(pts) - 1):

                p1 = pts[i]
                p2 = pts[i + 1]

                # skip invalid points
                if not p1.latitude or not p1.longitude:
                    continue
                if not p2.latitude or not p2.longitude:
                    continue

                # fill the gap between p1 and p2
                path = interpolate(
                    p1.latitude,
                    p1.longitude,
                    p2.latitude,
                    p2.longitude,
                    steps=20
                )

                for lat, lon in path:

                    hex_id = h3.latlng_to_cell(lat, lon, RESOLUTION)

                    ts = p1.time.isoformat() if p1.time else None

                    # INIT HEX
                    if hex_id not in db:
                        db[hex_id] = {
                            "source_files": {},
                            "first_seen": ts,
                            "last_seen": ts
                        }

                    # ADD FILE ONLY ONCE
                    if file_name not in db[hex_id]["source_files"]:
                        db[hex_id]["source_files"][file_name] = ts

                    # UPDATE TIME RANGE
                    t = parse(ts)

                    if t:
                        first = parse(db[hex_id]["first_seen"])
                        last = parse(db[hex_id]["last_seen"])

                        if first is None or t < first:
                            db[hex_id]["first_seen"] = ts

                        if last is None or t > last:
                            db[hex_id]["last_seen"] = ts

    # recompute visits
    for h in db:
        db[h]["visits"] = len(db[h]["source_files"])

    return db


# ----------------------------
# DELETE GPX FROM DB
# ----------------------------
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
            "source": format_trips(data.get("source_files", {})),
            "first_seen": data.get("first_seen"),
            "last_seen": data.get("last_seen"),
            "visits": data.get("visits", 1)
        }
    }


# ----------------------------
# MAP RENDER
# ----------------------------
def render_map(db):
    if not db:
        return None

    first_hex = next(iter(db))
    coords = h3.cell_to_latlng(first_hex)

    m = folium.Map(
        location=coords,
        zoom_start=14,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr=" ",
        control_scale=True,
        prefer_canvas=True,
        attribution_control=False
    )

    def style(f):
        v = f["properties"]["visits"]
        return {
            "fillColor": "#00FFFF",
            "color": "#00FFFF",
            "weight": 1,
            "fillOpacity": min(0.1 + v * 0.15, 0.7),
        }

    features = []

    for hex_id, data in db.items():
        boundary = h3.cell_to_boundary(hex_id)
        coords = [[lon, lat] for lat, lon in boundary]

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

    return m


# ----------------------------
# UI
# ----------------------------
st.title("GPX Hex Database Manager")

db = load_db()

all_times = []

for v in db.values():
    if v.get("first_seen"):
        all_times.append(datetime.fromisoformat(v["first_seen"]))
    if v.get("last_seen"):
        all_times.append(datetime.fromisoformat(v["last_seen"]))

if all_times:
    min_time = min(all_times)
    max_time = max(all_times)
else:
    min_time = datetime.now()
    max_time = datetime.now()

time_range = st.slider(
    "Time filter",
    min_value=min_time,
    max_value=max_time,
    value=(min_time, max_time),
    format="YYYY-MM-DD HH:mm"
)

# Upload GPX
uploaded = st.file_uploader("Upload GPX", type=["gpx"])

if uploaded:
    name = uploaded.name
    text = uploaded.read().decode("utf-8")

    db = process_gpx(db, name, text)
    save_db(db)
    st.success(f"Processed {name}")

# Delete GPX
all_files = set()
for v in db.values():
    all_files.update(v.get("source_files", {}).keys())

delete_choice = st.selectbox("Delete GPX from DB", sorted(all_files) if all_files else [])

if st.button("Delete"):
    db = delete_gpx(db, delete_choice)
    save_db(db)
    st.warning(f"Deleted {delete_choice}")

# Show stats
st.write(f"Hex count: {len(db)}")
st.write(f"Tracked GPX files: {len(all_files)}")

# Map
if st.button("Render Map"):

    filtered_db = {}

    start, end = time_range

    for hex_id, data in db.items():
        first = data.get("first_seen")
        last = data.get("last_seen")

        if not first or not last:
            continue

        first_t = datetime.fromisoformat(first)
        last_t = datetime.fromisoformat(last)

        # overlap check
        if last_t >= start and first_t <= end:
            filtered_db[hex_id] = data

    m = render_map(filtered_db)

    if m:
        m.save("map.html")
        st.success("Map saved as map.html")
