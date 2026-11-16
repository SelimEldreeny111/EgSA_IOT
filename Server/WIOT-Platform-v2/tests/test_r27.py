"""Release 2.7: Earth observation - open Sentinel-2 NDVI, Copernicus catalogue, EUMETSAT Data Store."""
from __future__ import annotations

import io
import json
import math
import struct
import time
import zlib

import pytest

from wiot.services.eo import Cog, OpenSentinel2, boa_offset, polygon_mask, utm_forward

np = pytest.importorskip("numpy")

from tests.conftest import PASSWORDS, login  # noqa: E402
from tests.test_r25 import LAYOUT  # noqa: E402
from wiot.services.farm import FarmLayout  # noqa: E402


# ------------------------------------------------------------------ helpers
def make_tiff(arr, tile=16, compress=True, predictor=True, origin=(0.0, 0.0), res=10.0, epsg=32635, big=False) -> bytes:
    """Minimal tiled GeoTIFF writer (classic or BigTIFF, little-endian) for the reader tests."""
    arr = np.asarray(arr)
    h, w = arr.shape
    bits = arr.dtype.itemsize * 8
    tiles = []
    for ty in range(0, h, tile):
        for tx in range(0, w, tile):
            t = np.zeros((tile, tile), arr.dtype)
            part = arr[ty:ty + tile, tx:tx + tile]
            t[:part.shape[0], :part.shape[1]] = part
            if predictor:
                t = t.copy()
                t[:, 1:] = t[:, 1:] - t[:, :-1]
            raw = t.astype(arr.dtype.newbyteorder("<")).tobytes()
            tiles.append(zlib.compress(raw) if compress else raw)
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, epsg]
    entries = [(256, 4, [w]), (257, 4, [h]), (258, 3, [bits]), (259, 3, [8 if compress else 1]), (262, 3, [1]),
               (277, 3, [1]), (284, 3, [1]), (317, 3, [2 if predictor else 1]), (322, 3, [tile]), (323, 3, [tile]),
               (324, 16 if big else 4, [0] * len(tiles)), (325, 16 if big else 4, [len(t) for t in tiles]),
               (339, 3, [1]), (33550, 12, [res, res, 0.0]), (33922, 12, [0.0, 0.0, 0.0, origin[0], origin[1], 0.0]),
               (34735, 3, geokeys)]
    code = {3: "H", 4: "I", 12: "d", 16: "Q"}
    size = {3: 2, 4: 4, 12: 8, 16: 8}
    ifd_at = 16 if big else 8
    ent_size, inline = (20, 8) if big else (12, 4)
    ifd_len = (8 if big else 2) + len(entries) * ent_size + (8 if big else 4)
    extra_at = ifd_at + ifd_len
    extras, pos = [], extra_at
    for tag, typ, vals in entries:                       # out-of-line values, placed after the IFD
        n = len(vals) * size[typ]
        extras.append(pos if n > inline else None)
        if n > inline:
            pos += n + (n % 2)
    data_at = pos
    offsets, p = [], data_at
    for t in tiles:
        offsets.append(p)
        p += len(t)
    entries[10] = (324, entries[10][1], offsets)
    out = bytearray(b"II" + (struct.pack("<HHHQ", 43, 8, 0, 16) if big else struct.pack("<HI", 42, 8)))
    out += struct.pack("<Q", len(entries)) if big else struct.pack("<H", len(entries))
    blobs = []
    for (tag, typ, vals), where in zip(entries, extras):
        payload = struct.pack("<" + code[typ] * len(vals), *vals)
        head = struct.pack("<HHQ", tag, typ, len(vals)) if big else struct.pack("<HHI", tag, typ, len(vals))
        if where is None:
            out += head + payload.ljust(inline, b"\0")
        else:
            out += head + struct.pack("<Q" if big else "<I", where)
            blobs.append(payload + (b"\0" if len(payload) % 2 else b""))
    out += struct.pack("<Q", 0) if big else struct.pack("<I", 0)
    for b in blobs:
        out += b
    assert len(out) == data_at
    for t in tiles:
        out += t
    return bytes(out)


class Files:
    """Fake HTTP for files with Range support; counts requests per file."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.hits: dict[str, int] = {}

    def get(self, url, headers):
        data = self.files[url]
        self.hits[url] = self.hits.get(url, 0) + 1
        rng = headers.get("Range")
        if not rng:
            return 200, data
        a, b = (int(x) for x in rng.split("=")[1].split("-"))
        return 206, data[a:b + 1]


# ------------------------------------------------------------------ geometry and reader
def test_utm_matches_reference_projection():
    for lat, lon, zone, south, e, n in [(22.25, 28.72, 35, False, 677246.106, 2461506.453),
                                        (30.05, 31.6, 36, False, 365034.235, 3325151.587),
                                        (-33.9, 18.4, 34, True, 259583.222, 6245888.045)]:
        x, y = utm_forward(lat, lon, zone, south)
        assert abs(x - e) < 0.01 and abs(y - n) < 0.01


@pytest.mark.parametrize("compress,predictor,big", [(True, True, False), (False, False, True), (True, False, True)])
def test_cog_reader_reads_exact_windows(compress, predictor, big):
    rng = np.random.default_rng(1)
    src = rng.integers(0, 65535, size=(37, 45), dtype=np.uint16)
    files = Files()
    files.files["https://x/a.tif"] = make_tiff(src, tile=16, compress=compress, predictor=predictor,
                                               origin=(600000.0, 2500020.0), big=big)
    cog = Cog("https://x/a.tif", lambda m, u, h, b, timeout=60: files.get(u, h))
    assert (cog.width, cog.height, cog.tw, cog.epsg) == (45, 37, 16, 32635)
    assert cog.origin == (600000.0, 2500020.0) and cog.res == (10.0, 10.0)
    assert np.array_equal(cog.read(0, 0, 45, 37), src)
    assert np.array_equal(cog.read(10, 5, 20, 20), src[5:25, 10:30])          # spans four tiles
    edge = cog.read(40, 30, 10, 10)                                            # partly outside: zeros
    assert np.array_equal(edge[:7, :5], src[30:37, 40:45]) and not edge[7:, :].any() and not edge[:, 5:].any()
    assert cog.window(600050.0, 2499900.0, 600100.0, 2500000.0) == (5, 2, 5, 10)


def test_polygon_mask_and_offset_rules():
    m = polygon_mask([0, 10, 10, 0, 0], [0, 0, 10, 10, 0], (12, 12))
    assert m.sum() == 100 and m[0, 0] and not m[10, 10]
    ring = [(5 + 4 * math.cos(a), 5 + 4 * math.sin(a)) for a in (2 * math.pi * i / 64 for i in range(65))]
    circle = polygon_mask([p[0] for p in ring], [p[1] for p in ring], (10, 10))
    assert abs(circle.sum() - math.pi * 16) < 6
    assert boa_offset({"s2:processing_baseline": "05.11"}) == 1000
    assert boa_offset({"s2:processing_baseline": "05.11", "earthsearch:boa_offset_applied": True}) == 0
    assert boa_offset({"s2:processing_baseline": "03.01"}) == 0


# ------------------------------------------------------------------ open Sentinel-2 NDVI
def open_archive(settings, cloudy_rows: int = 19):
    """Fake Earth Search: three passes over LAYOUT's pivot (radius 300 m at 22.25 N, 28.72 E)."""
    e, n = utm_forward(22.25, 28.72, 35)
    x0, y0 = math.floor((e - 500) / 20) * 20, math.ceil((n + 500) / 20) * 20
    files = Files()
    scl = np.full((50, 50), 4, np.uint8)
    scl[:cloudy_rows, :] = 9                            # cloud over the northern quarter of the pivot
    feats = []
    for k, (day, props, red, nir, s) in enumerate([
            ("2026-11-02", {"s2:processing_baseline": "05.11"}, 1500, 4500, scl),
            ("2026-11-07", {"s2:processing_baseline": "05.11", "earthsearch:boa_offset_applied": True}, 500, 3500, scl),
            ("2026-11-12", {"s2:processing_baseline": "05.11"}, 1500, 4500, np.full((50, 50), 9, np.uint8))]):
        sid = f"S2C_35QPE_{day.replace('-', '')}_0_L2A"
        for band, arr, res in (("red", np.full((100, 100), red, np.uint16), 10.0),
                               ("green", np.full((100, 100), red + 200, np.uint16), 10.0),
                               ("blue", np.full((100, 100), red + 100, np.uint16), 10.0),
                               ("nir", np.full((100, 100), nir, np.uint16), 10.0), ("scl", s, 20.0)):
            files.files[f"https://cogs/{sid}/{band}.tif"] = make_tiff(arr, tile=32, origin=(x0, y0), res=res)
        feats.append({"id": sid, "bbox": [28.6, 22.1, 28.9, 22.4], "properties": {
            "datetime": f"{day}T08:44:14Z", "eo:cloud_cover": 3.0 + k, "proj:epsg": 32635, "platform": "sentinel-2c", **props},
            "assets": {b: {"href": f"https://cogs/{sid}/{b}.tif"} for b in ("red", "green", "blue", "nir", "scl")}})
    searches = []

    def http(method, url, headers, body, timeout=60):
        if url == settings.earthsearch_url + "/search":
            q = json.loads(body)
            searches.append(q)
            assert q["collections"] == ["sentinel-2-l2a"]
            return 200, json.dumps({"features": feats}).encode()
        return files.get(url, headers)
    return http, files, searches


@pytest.fixture()
def farm(supervisor):
    rt = supervisor.app.state.runtime
    rt.farm.store.put("Company_1", FarmLayout.model_validate(LAYOUT), "test")
    return supervisor


def test_open_archive_ndvi_per_field(farm):
    rt = farm.app.state.runtime
    rt.settings.satellite_provider = "open"
    http, files, searches = open_archive(rt.settings)
    rt.satellite.http = http
    assert rt.satellite.ndvi_provider == "open"
    from datetime import date
    assert rt.satellite.fetch_ndvi("Company_1", 30, today=date(2026, 11, 13)) == 2      # the fully cloudy pass is dropped
    hist = farm.get("/api/v2/satellite/ndvi", params={"company": "Company_1", "days": 1500}).json()["history"]
    assert [h["date"] for h in hist] == ["2026-11-02", "2026-11-07"]
    for h in hist:
        assert h["source"] == "sentinel-2-open" and abs(h["mean"] - 0.75) < 1e-4    # offset handled both ways
        assert 0.6 < h["clear_share"] < 0.97                                         # the cloudy rows are masked
    read = {s["date"]: s["fields"] for s in rt.satellite.open_scenes("Company_1")}
    assert read == {"2026-11-02": 1, "2026-11-07": 1, "2026-11-12": 0}
    before = sum(files.hits.values())
    assert rt.satellite.fetch_ndvi("Company_1", 30, today=date(2026, 11, 13)) == 0      # passes are read only once
    assert sum(files.hits.values()) == before and len(searches) == 2
    assert searches[0]["query"]["eo:cloud_cover"]["lte"] == 60                    # "at most", inclusive
    img = farm.get("/api/v2/satellite/image/P1.png", params={"company": "Company_1", "kind": "truecolor"})
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG", img.text[:200]
    ndvi_png = farm.get("/api/v2/satellite/image/P1.png", params={"company": "Company_1", "kind": "ndvi"})
    assert ndvi_png.status_code == 200 and ndvi_png.content[:4] == b"\x89PNG"


def test_refresh_runs_in_background_and_reports(farm):
    rt = farm.app.state.runtime
    r = farm.post("/api/v2/satellite/ndvi/refresh", params={"company": "Company_1"})
    assert r.status_code == 409 and "WIOT_SATELLITE_PROVIDER=open" in r.json()["detail"]
    rt.settings.satellite_provider = "open"
    http, _, _ = open_archive(rt.settings)
    rt.satellite.http = http
    st = farm.get("/api/v2/satellite/status").json()
    assert st["sentinel"] is True and st["provider"] == "open" and st["sentinelhub"] is False
    r = farm.post("/api/v2/satellite/ndvi/refresh", params={"company": "Company_1", "days": 400}).json()
    assert r["started"] is True
    for _ in range(100):
        job = farm.get("/api/v2/satellite/status").json()["job"]
        if not job["running"]:
            break
        time.sleep(0.05)
    assert job["running"] is False and job["stored"] == 2 and "error" not in job


def test_field_stats_match_independent_count():
    """A 300 m pivot on a 10 m grid holds about 2,827 pixels; the clear share follows the cloud rows."""
    class S:
        earthsearch_url = "https://es"
    http, _, _ = open_archive(S, cloudy_rows=0)
    s2 = OpenSentinel2(S, http)
    scene = s2.search([28.7, 22.24, 28.74, 22.26], None, None, 60)[0]
    from wiot.services.satellite import zone_geometry

    class Z:
        shape, center, radius_m = "circle", (22.25, 28.72), 300.0
    st = s2.field_stats(scene, [("P1", zone_geometry(Z)["coordinates"][0])])[0]
    assert abs(st["pixels"] - math.pi * 300 ** 2 / 100) / (math.pi * 300 ** 2 / 100) < 0.02
    assert st["clear_share"] == 1.0 and st["min"] == st["max"] == 0.75


# ------------------------------------------------------------------ catalogues
def test_copernicus_catalogue_search(farm):
    rt = farm.app.state.runtime
    seen = []

    def http(method, url, headers, body, timeout=60):
        assert method == "POST" and url == rt.settings.cdse_stac_url + "/search"
        q = json.loads(body)
        seen.append(q)
        return 200, json.dumps({"features": [{"id": "S2B_MSIL2A_20261111T084109_N0513_R064_T35QPE_20261111T125522",
                                              "properties": {"datetime": "2026-11-11T08:41:09Z", "platform": "sentinel-2b",
                                                             "eo:cloud_cover": 0.0, "grid:code": "MGRS-35QPE",
                                                             "product:type": "S2MSI2A"}}]}).encode()
    rt.satellite.http = http
    d = farm.get("/api/v2/eo/scenes", params={"company": "Company_1", "days": 30, "max_cloud": 20}).json()
    assert seen[0]["collections"] == ["sentinel-2-l2a"] and seen[0]["sortby"][0]["direction"] == "desc"
    assert seen[0]["filter"]["args"][1] == 20
    sc = d["scenes"][0]
    assert sc["platform"] == "sentinel-2b" and "fromTime=2026-11-11" in sc["browser"] and "datasetId=S2_L2A_CDAS" in sc["browser"]
    assert farm.get("/api/v2/eo/scenes", params={"company": "Company_1", "collection": "landsat"}).status_code == 400
    rt.satellite.http = lambda *a, **k: (503, b"down")
    r = farm.get("/api/v2/eo/scenes", params={"company": "Company_1"})
    assert r.status_code == 502 and "503" in r.json()["detail"]


def test_eumetsat_search_and_download(farm, tmp_path):
    rt = farm.app.state.runtime
    calls = []

    def http(method, url, headers, body, timeout=60):
        calls.append((method, url, headers))
        if "/data/browse/collections" in url:
            return 200, json.dumps({"links": [{"title": "EO:EUM:DAT:1088", "datasetTitle": "Land Surface Temperature - MTG",
                                               "numberOfProducts": 64000},
                                              {"title": "EO:EUM:DAT:0409", "datasetTitle": "OLCI Level 1B Full Resolution"}]}).encode()
        if "/data/search-products/" in url:
            assert "pi=EO%3AEUM%3ADAT%3A1088" in url and "bbox=" in url and "sort=start%2Ctime%2C0" in url
            return 200, json.dumps({"totalResults": 144, "features": [{"properties": {
                "identifier": "W_PT-LSASAF-LISBON,SATELLITE,LSA-007_MTG_MTLST_MTG-FD_C_LPMG_20261112230000",
                "date": "2026-11-12T23:00:07Z/2026-11-12T23:09:23Z", "productInformation": {"productType": "MTLST", "size": 12567},
                "acquisitionInformation": [{"platform": {"platformShortName": "MTI1"}, "instrument": {"instrumentShortName": "FCI"}}]}}]}).encode()
        if url.endswith("/token"):
            assert headers["Authorization"].startswith("Basic ") and body == b"grant_type=client_credentials"
            return 200, json.dumps({"access_token": "eum-tok", "expires_in": 3600}).encode()
        raise AssertionError(url)
    rt.satellite.http = http
    cols = farm.get("/api/v2/eo/eumetsat/collections", params={"q": "temperature"}).json()
    assert cols["total"] == 1 and cols["collections"][0]["id"] == "EO:EUM:DAT:1088"
    d = farm.get("/api/v2/eo/eumetsat/products", params={"collection": "EO:EUM:DAT:1088", "company": "Company_1"}).json()
    p = d["products"][0]
    assert d["total"] == 144 and d["download"] is False and p["platform"] == "MTI1" and p["size_kb"] == 12567
    body = {"collection": "EO:EUM:DAT:1088", "product": p["id"]}
    assert farm.post("/api/v2/eo/eumetsat/download", json=body).status_code == 409           # no API key yet
    from pydantic import SecretStr
    rt.settings.eumetsat_key, rt.settings.eumetsat_secret = "ck", SecretStr("cs")
    got = {}

    def fake_download(url, headers, dest, max_bytes, timeout=120):
        got.update(url=url, auth=headers["Authorization"], max=max_bytes)
        dest.write_bytes(b"PK\x03\x04 product")
        return 200, 16
    rt.satellite.catalogue.download = fake_download
    r = farm.post("/api/v2/eo/eumetsat/download", json=body).json()
    assert r["bytes"] == 16 and r["cached"] is False and r["file"].endswith(".zip")
    assert got["auth"] == "Bearer eum-tok" and "products/W_PT-LSASAF-LISBON%2CSATELLITE" in got["url"]
    assert got["max"] == 200 * 1024 * 1024
    assert farm.post("/api/v2/eo/eumetsat/download", json=body).json()["cached"] is True
    files = farm.get("/api/v2/eo/downloads").json()["downloads"]
    assert len(files) == 1 and files[0]["collection"] == "EO_EUM_DAT_1088"
    bad = farm.post("/api/v2/eo/eumetsat/download", json={"collection": "EO:EUM:DAT:1088", "product": "../../etc/x"})
    assert bad.status_code == 400
    assert farm.get("/api/v2/eo/eumetsat/products", params={"collection": "landsat"}).status_code == 400
    st = farm.get("/api/v2/eo/status").json()
    assert st["eumetsat_download"] is True and st["eumetsat_suggested"][0]["id"] == "EO:EUM:DAT:1088"
    csrf = login(farm, "Super_User", PASSWORDS["WIOT_MONITOR_PASSWORD"])                     # read-only monitor
    farm.headers["X-CSRF-Token"] = csrf
    assert farm.post("/api/v2/eo/eumetsat/download", json=body).status_code == 403


def test_sentinel_hub_clear_share_is_measured_against_the_field(farm):
    """The Statistical API counts the whole bounding box: a fully clear round field must read 100 %, not ~78 %."""
    from pydantic import SecretStr

    from wiot.services.satellite import field_share_of_bbox, zone_geometry
    rt = farm.app.state.runtime
    rt.settings.sentinel_client_id, rt.settings.sentinel_client_secret = "cid", SecretStr("sec")
    zone = rt.farm.store.get("Company_1").zones[0]
    share = field_share_of_bbox(zone_geometry(zone))
    assert 0.74 < share < 0.80                                     # a circle fills about pi/4 of its box
    total = 10000
    outside = round(total * (1 - share))

    def stats(day, cloudy_part):
        nodata = outside + round(total * share * cloudy_part)
        return {"interval": {"from": f"{day}T00:00:00Z"}, "outputs": {"ndvi": {"bands": {"B0": {"stats": {
            "min": 0.2, "max": 0.8, "mean": 0.6, "sampleCount": total, "noDataCount": nodata}}}}}}

    def fake(method, url, headers, body, timeout=60):
        if url.endswith("/token"):
            return 200, json.dumps({"access_token": "tok", "expires_in": 600}).encode()
        return 200, json.dumps({"data": [stats("2026-11-05", 0.0), stats("2026-11-08", 0.4),
                                         stats("2026-11-11", 0.6)]}).encode()
    rt.satellite.http = fake
    assert rt.satellite.fetch_ndvi("Company_1") == 2                              # 60 % cloud is dropped
    hist = {h["date"]: h["clear_share"] for h in rt.satellite.ndvi_history("Company_1", days=3000)}
    assert hist["2026-11-05"] == 1.0 and abs(hist["2026-11-08"] - 0.6) < 0.01 and "2026-11-11" not in hist


# ------------------------------------------------------------------ satellite viewer: layers, overviews, rendering
def make_cog(levels: list, tile=16, origin=(0.0, 0.0), res=10.0, epsg=32635) -> bytes:
    """Tiled GeoTIFF with reduced-resolution overviews (IFD chain, NewSubfileType = 1), DEFLATE + predictor 2."""
    out = bytearray(b"II" + struct.pack("<HI", 42, 8))
    prev_next_at = None
    for li, arr in enumerate(levels):
        arr = np.asarray(arr)
        h, w = arr.shape
        tiles = []
        for ty in range(0, h, tile):
            for tx in range(0, w, tile):
                t = np.zeros((tile, tile), arr.dtype)
                part = arr[ty:ty + tile, tx:tx + tile]
                t[:part.shape[0], :part.shape[1]] = part
                t = t.copy()
                t[:, 1:] = t[:, 1:] - t[:, :-1]
                tiles.append(zlib.compress(t.astype("<u2").tobytes()))
        entries = [(254, 4, [1 if li else 0]), (256, 4, [w]), (257, 4, [h]), (258, 3, [16]), (259, 3, [8]), (277, 3, [1]),
                   (317, 3, [2]), (322, 3, [tile]), (323, 3, [tile]), (324, 4, [0] * len(tiles)),
                   (325, 4, [len(t) for t in tiles]), (339, 3, [1])]
        if li == 0:
            entries += [(33550, 12, [res, res, 0.0]), (33922, 12, [0.0, 0.0, 0.0, origin[0], origin[1], 0.0]),
                        (34735, 3, [1, 1, 0, 1, 3072, 0, 1, epsg])]
        code, size = {3: "H", 4: "I", 12: "d"}, {3: 2, 4: 4, 12: 8}
        ifd_at = len(out)
        if prev_next_at is not None:                               # link the previous IFD to this one
            struct.pack_into("<I", out, prev_next_at, ifd_at)
        pos = ifd_at + 2 + len(entries) * 12 + 4
        where = []
        for _, typ, vals in entries:
            n = len(vals) * size[typ]
            where.append(pos if n > 4 else None)
            if n > 4:
                pos += n
        offsets, p = [], pos
        for t in tiles:
            offsets.append(p)
            p += len(t)
        entries[9] = (324, 4, offsets)
        block = bytearray(struct.pack("<H", len(entries)))
        blobs = b""
        for (tag, typ, vals), wh in zip(entries, where):
            payload = struct.pack("<" + code[typ] * len(vals), *vals)
            block += struct.pack("<HHI", tag, typ, len(vals)) + (payload.ljust(4, b"\0") if wh is None else struct.pack("<I", wh))
            if wh is not None:
                blobs += payload
        prev_next_at = ifd_at + len(block)
        block += struct.pack("<I", 0)
        out += block + blobs + b"".join(tiles)
    return bytes(out)


def test_layer_catalogue_scripts_and_numpy_renderers():
    from wiot.services.eo_layers import LAYERS, bands_needed, custom_script, public_catalogue, render_numpy
    ids = {layer["id"] for layer in LAYERS}
    for want in ("TRUE_COLOR", "FALSE_COLOR", "HIGHLIGHT", "NDVI", "WILDFIRES", "FALSE_COLOR_URBAN", "MOISTURE", "SWIR",
                 "NDWI", "NDSI", "SCL", "CUSTOM"):
        assert want in ids                                          # the Copernicus Browser's Sentinel-2 list
    rng = np.random.default_rng(3)
    bands = {b: rng.uniform(0.01, 0.6, (12, 14)).astype(np.float32) for b in
             ("B02", "B03", "B04", "B05", "B08", "B8A", "B11", "B12")}
    bands["SCL"] = rng.integers(0, 12, (12, 14))
    for layer in LAYERS:
        if layer["script"]:
            assert "evaluatePixel" in layer["script"] and "dataMask" in layer["script"]
        if layer["open"] and layer["id"] != "CUSTOM":
            need = bands_needed(layer["id"])
            assert set(need) <= set(bands)
            img = render_numpy(layer["id"], {k: bands[k] for k in need + ["SCL"]})   # only what the archive reads
            assert img.shape == (12, 14, 3) and float(img.min()) >= 0 and float(img.max()) <= 1, layer["id"]
    img = render_numpy("CUSTOM", bands, {"mode": "index", "bands": ["B08", "B11"]})
    assert img.shape == (12, 14, 3)
    assert "(s.B08 - s.B11)" in custom_script("index", ["B08", "B11"])
    with pytest.raises(ValueError):
        custom_script("composite", ["B04", "B03", "XX"])
    cat = public_catalogue(open_available=True, sentinelhub=False)
    s1 = next(m for m in cat["missions"] if m["id"] == "S1GRD")
    assert s1["renderers"] == [] and next(m for m in cat["missions"] if m["id"] == "S2L2A")["renderers"] == ["open"]


def test_cog_overviews_and_point_sampling():
    full = np.arange(64 * 48, dtype=np.uint16).reshape(48, 64)
    half = full[::2, ::2].copy()
    quarter = full[::4, ::4].copy()
    files = Files()
    files.files["https://x/o.tif"] = make_cog([full, half, quarter], tile=16, origin=(600000.0, 2500000.0), res=10.0)
    cog = Cog("https://x/o.tif", lambda m, u, h, b, timeout=60: files.get(u, h))
    assert [lv["width"] for lv in cog.levels] == [64, 32, 16] and [lv["res"][0] for lv in cog.levels] == [10.0, 20.0, 40.0]
    assert cog.level_for(5) == 0 and cog.level_for(25) == 1 and cog.level_for(100) == 2
    assert np.array_equal(cog.read(3, 2, 10, 9, level=1), half[2:11, 3:13])
    assert np.array_equal(cog.read(0, 0, 16, 12, level=2), quarter)
    xs = np.array([600005.0, 600155.0, 599000.0])                   # the last point is outside the image
    ys = np.array([2499995.0, 2499895.0, 2499995.0])
    assert list(cog.sample(xs, ys, 0)) == [full[0, 0], full[10, 15], 0]
    assert list(cog.sample(xs, ys, 1)) == [half[0, 0], half[5, 7], 0]


def _viewer_fake_sh(calls, png=b"\x89PNG\r\n\x1a\nfake"):
    def fake(method, url, headers, body, timeout=60):
        if url.endswith("/token"):
            return 200, json.dumps({"access_token": "tok", "expires_in": 600}).encode()
        assert url.endswith("/api/v1/process") and headers["Accept"] == "image/png"
        calls.append(json.loads(body))
        return 200, png
    return fake


def test_viewer_renders_layers_through_sentinel_hub_with_cache_and_limits(farm, monkeypatch):
    from pydantic import SecretStr
    rt = farm.app.state.runtime
    rt.settings.sentinel_client_id, rt.settings.sentinel_client_secret = "cid", SecretStr("sec")
    calls = []
    rt.satellite.http = _viewer_fake_sh(calls)
    lay = farm.get("/api/v2/eo/layers", params={"company": "Company_1"}).json()
    assert lay["sentinelhub"] is True and lay["fields"][0]["id"] == "P1" and lay["bbox"]
    ndvi = next(x for x in lay["layers"] if x["id"] == "NDVI")
    assert ndvi["legend"]["kind"] == "ramp" and "sentinelhub" in ndvi["renderers"]
    q = {"mission": "S2L2A", "layer": "NDVI", "west": 28.70, "south": 22.24, "east": 28.74, "north": 22.26,
         "width": 640, "height": 400, "cloud": 20}
    r = farm.get("/api/v2/eo/render.png", params=q)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG") and r.headers["content-type"] == "image/png"
    meta = json.loads(r.headers["x-imagery"])
    assert meta["provider"] == "sentinelhub" and meta["mosaic"] == "leastCC"
    p = calls[0]
    assert p["input"]["bounds"]["properties"]["crs"].endswith("/3857")          # Web Mercator, like the map
    assert p["input"]["data"][0]["type"] == "sentinel-2-l2a" and p["input"]["data"][0]["dataFilter"]["maxCloudCoverage"] == 20
    assert "ColorRampVisualizer" in p["evalscript"] and p["output"]["width"] == 640
    assert farm.get("/api/v2/eo/render.png", params=q).status_code == 200 and len(calls) == 1   # cached on disk
    farm.get("/api/v2/eo/render.png", params={**q, "mission": "S1GRD", "layer": "S1_VV", "date": "2026-11-10"})
    s1 = calls[-1]["input"]["data"][0]
    assert s1["type"] == "sentinel-1-grd" and s1["processing"]["backCoeff"] == "GAMMA0_TERRAIN"
    assert s1["dataFilter"]["timeRange"]["from"].startswith("2026-11-10") and "maxCloudCoverage" not in s1["dataFilter"]
    custom = farm.get("/api/v2/eo/render.png", params={**q, "layer": "CUSTOM", "mode": "composite", "bands": "B12,B08,B04"})
    assert custom.status_code == 200 and '"B12"' in calls[-1]["evalscript"]
    assert farm.get("/api/v2/eo/render.png", params={**q, "layer": "S1_VV"}).status_code == 400      # wrong mission
    script = {**q, "layer": "CUSTOM", "evalscript": "//VERSION=3\nfunction setup(){return {input:[\"B04\"],output:{bands:1}}}\n"
                                                    "function evaluatePixel(s){return [s.B04]}"}
    assert farm.post("/api/v2/eo/render.png", json=script).status_code == 200
    assert farm.post("/api/v2/eo/render.png", json={**script, "evalscript": "not a script"}).status_code == 400

    def failing(method, url, headers, body, timeout=60):
        if url.endswith("/token"):
            return 200, b'{"access_token": "tok", "expires_in": 600}'
        return 400, b'{"error": {"message": "Bad evalscript"}}'
    rt.satellite.http = failing
    bad = farm.get("/api/v2/eo/render.png", params={**q, "layer": "SWIR"})
    assert bad.status_code == 502 and "Bad evalscript" in bad.json()["detail"]
    from wiot.api import eo as eo_api
    monkeypatch.setattr(eo_api, "RENDER_LIMIT", 0)
    assert farm.get("/api/v2/eo/render.png", params=q).status_code == 429
    monkeypatch.setattr(eo_api, "RENDER_LIMIT", 150)
    csrf = login(farm, "Super_User", PASSWORDS["WIOT_MONITOR_PASSWORD"])
    farm.headers["X-CSRF-Token"] = csrf
    assert farm.post("/api/v2/eo/render.png", json=script).status_code == 403               # own evalscript: admins


def test_viewer_renders_from_the_open_archive(farm):
    from PIL import Image

    from wiot.services.eo_layers import NDVI_RAMP, ramp_colors
    rt = farm.app.state.runtime
    rt.settings.satellite_provider = "open"
    http, files, _ = open_archive(rt.settings)
    rt.satellite.http = http
    q = {"mission": "S2L2A", "west": 28.718, "south": 22.248, "east": 28.722, "north": 22.252, "width": 64, "height": 48,
         "date": "2026-11-02"}
    for layer in ("TRUE_COLOR", "NDVI", "SCL"):
        r = farm.get("/api/v2/eo/render.png", params={**q, "layer": layer})
        assert r.status_code == 200, r.text
        img = Image.open(io.BytesIO(r.content))
        assert img.size == (64, 48) and img.mode == "RGBA"
        meta = json.loads(r.headers["x-imagery"])
        assert meta["provider"] == "open" and meta["from"] == "2026-11-02"         # the chosen pass, not the latest
        assert meta["scene"].startswith("S2C_35QPE_20261102") and meta["mosaic"] == "single pass"
    px = np.asarray(Image.open(io.BytesIO(farm.get("/api/v2/eo/render.png", params={**q, "layer": "NDVI"}).content)))
    assert px[:, :, 3].min() == 255                                   # all inside the data
    want = (ramp_colors(np.array([[0.75]]), NDVI_RAMP)[0, 0] * 255).round()
    assert np.abs(px[24, 32, :3].astype(float) - want).max() <= 1   # NDVI 0.75 of the synthetic scene
    assert farm.get("/api/v2/eo/render.png", params={**q, "layer": "S1_VV", "mission": "S1GRD"}).status_code == 404
    big = farm.get("/api/v2/eo/render.png", params={**q, "layer": "NDVI", "west": 27.0, "east": 27.9})
    assert big.status_code == 400 and "Zoom in" in big.json()["detail"]


def test_availability_lists_every_source_and_survives_a_failing_catalogue(farm):
    rt = farm.app.state.runtime
    seen = []

    def http(method, url, headers, body, timeout=60):
        seen.append(url)
        if url == rt.settings.cdse_stac_url + "/search":
            col = json.loads(body)["collections"][0]
            if col == "sentinel-3-sl-2-lst-ntc":
                return 503, b"down"
            feats = [{"id": f"{col}-{i}", "properties": {"datetime": f"2026-11-{10 - i:02d}T08:41:09Z", "platform": "sentinel-x",
                                                        "eo:cloud_cover": 5.0 * i, "sat:relative_orbit": 64}} for i in range(3)]
            return 200, json.dumps({"features": feats, "links": []}).encode()
        if url == rt.settings.earthsearch_url + "/search":
            return 200, json.dumps({"features": [{"id": "LC09_x", "properties": {
                "datetime": "2026-11-04T08:31:00Z", "platform": "landsat-9", "eo:cloud_cover": 1.0}}]}).encode()
        if "/data/search-products/" in url:
            return 200, json.dumps({"totalResults": 144, "features": [{"properties": {
                "identifier": "P1", "date": "2026-11-12T23:00:07Z/2026-11-12T23:09:23Z"}}]}).encode()
        raise AssertionError(url)
    rt.satellite.http = http
    d = farm.get("/api/v2/eo/availability", params={"company": "Company_1", "days": 30}).json()
    m = {x["id"]: x for x in d["missions"]}
    assert m["S2L2A"]["count"] == 3 and m["S2L2A"]["items"][0]["date"] == "2026-11-10" and m["S2L2A"]["items"][1]["cloud"] == 5.0
    assert m["S1GRD"]["ok"] and m["S3OLCI"]["ok"] and m["LANDSAT"]["items"][0]["platform"] == "landsat-9"
    assert m["S3SLSTR"]["ok"] is False and "503" in m["S3SLSTR"]["error"]       # one catalogue down, the rest shown
    assert d["eumetsat"][0]["count"] == 144 and d["eumetsat"][0]["latest"].startswith("2026-11-12")
    assert "server" in d and "browser" in d and "S2_L2A_CDAS" in d["browser"]["S2L2A"]
    n = len(seen)
    assert farm.get("/api/v2/eo/availability", params={"company": "Company_1", "days": 30}).json()["cached"] is True
    assert len(seen) == n                                             # cached for 20 minutes


# ------------------------------------------------------------------ viewer hardening (pre-push review)
def test_viewer_protects_the_server_and_the_copernicus_allowance(farm, monkeypatch):
    import http.client

    from pydantic import SecretStr

    from wiot.api import eo as eo_api
    from wiot.services import eo_render
    rt = farm.app.state.runtime
    rt.settings.sentinel_client_id, rt.settings.sentinel_client_secret = "cid", SecretStr("sec")
    calls = []
    rt.satellite.http = _viewer_fake_sh(calls)
    viewer = rt.satellite.viewer
    q = {"mission": "S2L2A", "layer": "TRUE_COLOR", "west": 28.70, "south": 22.24, "east": 28.74, "north": 22.26,
         "width": 512, "height": 512, "cloud": 32.4}
    assert farm.get("/api/v2/eo/render.png", params=q).status_code == 200
    assert calls[-1]["input"]["data"][0]["dataFilter"]["maxCloudCoverage"] == 32     # the value of the cache key
    assert farm.get("/api/v2/eo/render.png", params={**q, "cloud": 31.6}).status_code == 200 and len(calls) == 1
    assert eo_render.processing_units(512, 512, calls[-1]["evalscript"]) == pytest.approx(1.0)   # 3 bands, 512 x 512
    assert viewer.usage_today()["*"] == pytest.approx(1.0)
    # daily allowance of the server (the supervisor has no company): cache misses are charged, cached images are free
    rt.settings.viewer_daily_pu = 1.5
    over = farm.get("/api/v2/eo/render.png", params={**q, "west": 28.701})
    assert over.status_code == 429 and "allowance of this server" in over.json()["detail"]
    assert farm.get("/api/v2/eo/render.png", params=q).status_code == 200
    rt.settings.viewer_daily_pu = 0                                              # 0 = no limit
    # every Sentinel Hub slot in use: 503 with Retry-After, nothing charged
    monkeypatch.setattr(eo_render, "SLOT_WAIT_S", 0)
    held = [viewer._sh_slots.acquire() for _ in range(eo_render.SH_SLOTS)]
    try:
        before = len(eo_api._renders["EgSA_Supervisor"])
        busy = farm.get("/api/v2/eo/render.png", params={**q, "west": 28.702})
        assert busy.status_code == 503 and busy.headers["retry-after"] == "2"
        assert len(eo_api._renders["EgSA_Supervisor"]) == before                  # a busy answer is not counted
    finally:
        for _ in held:
            viewer._sh_slots.release()
    assert viewer.usage_today()["*"] == pytest.approx(1.0)
    # one user's images still being drawn
    monkeypatch.setitem(eo_api._inflight, "EgSA_Supervisor", eo_api.INFLIGHT_PER_USER)
    mine = farm.get("/api/v2/eo/render.png", params={**q, "west": 28.703})
    assert mine.status_code == 503 and "still being drawn" in mine.json()["detail"]
    monkeypatch.delitem(eo_api._inflight, "EgSA_Supervisor")

    # remote failures are 502, never 500, and never show a server path
    def answer(result):
        def fake(method, url, headers, body, timeout=60):
            if isinstance(result, Exception):
                raise result
            return result
        return fake
    for n, (result, words) in enumerate([((200, b"<html>maintenance</html>"), "did not send a PNG"),
                                         (http.client.IncompleteRead(b"\x89PNG"), "could not be read"),
                                         (TimeoutError("timed out"), "could not be reached"),
                                         (FileNotFoundError(2, "No such file", "D:/srv/wiot/data/secret.png"), "Storage error")]):
        rt.satellite.http = answer(result)
        r = farm.get("/api/v2/eo/render.png", params={**q, "west": 28.71 + n / 1000})
        assert r.status_code == 502 and words in r.json()["detail"], (n, r.text)
        assert "secret" not in r.text and "D:/srv" not in r.text
    # own evalscript: the supervisor only (shared Copernicus account), dates strictly YYYY-MM-DD
    rt.satellite.http = _viewer_fake_sh(calls)
    script = {**q, "layer": "CUSTOM", "evalscript": "//VERSION=3\nfunction setup(){return {input:[\"B04\"],output:{bands:1}}}\n"
                                                    "function evaluatePixel(s){return [s.B04]}"}
    assert farm.get("/api/v2/eo/layers", params={"company": "Company_1"}).json()["own_evalscript"] is True
    assert farm.post("/api/v2/eo/render.png", json={**script, "date": "20261110"}).status_code == 422
    nan_body = json.dumps({**script, "west": float("nan")})                    # Python's JSON parser accepts NaN
    assert "NaN" in nan_body
    assert farm.post("/api/v2/eo/render.png", content=nan_body, headers={"Content-Type": "application/json"}).status_code in (400, 422)
    assert farm.post("/api/v2/eo/render.png", json={**script, "date": "2026-11-10"}).status_code == 200
    assert calls[-1]["input"]["data"][0]["dataFilter"]["timeRange"]["from"] == "2026-11-10T00:00:00Z"
    png, meta = viewer.render("S2L2A", "NDVI", (28.70, 22.24, 28.74, 22.26), 64, 64, day="20261109")
    assert meta["date"] == "2026-11-09" and calls[-1]["input"]["data"][0]["dataFilter"]["timeRange"]["from"].startswith("2026-11-09")
    farm.headers["X-CSRF-Token"] = login(farm, "admin", PASSWORDS["WIOT_ADMIN_PASSWORD"])     # an admin of Company_1
    assert farm.post("/api/v2/eo/render.png", json=script).status_code == 403
    assert farm.get("/api/v2/eo/layers").json()["own_evalscript"] is False
    used = viewer.usage_today().get("Company_1", 0.0)
    rt.settings.viewer_company_daily_pu = used + 1.5                            # room for one more 512 x 512 image
    assert farm.get("/api/v2/eo/render.png", params={**q, "west": 28.72}).status_code == 200
    over = farm.get("/api/v2/eo/render.png", params={**q, "west": 28.721})
    assert over.status_code == 429 and "allowance of this company" in over.json()["detail"]
    assert farm.get("/api/v2/eo/render.png", params={**q, "west": 28.72}).status_code == 200     # cached: free
    assert viewer.usage_today()["Company_1"] == pytest.approx(used + 1.0)


def test_render_cache_is_atomic_bounded_and_survives_races(farm, monkeypatch):
    import os
    import threading

    from wiot.services import eo_render
    rt = farm.app.state.runtime
    viewer = rt.satellite.viewer
    d = viewer.cache_dir()
    (d / "old.png").write_bytes(b"\x89PNG")                          # files of the earlier cache format
    (d / "old.json").write_text("{}")
    monkeypatch.setattr(eo_render, "CACHE_FILES", 5)
    png = b"\x89PNG\r\n\x1a\n" + bytes(1000)
    errors = []

    def worker(k):
        try:
            for i in range(25):
                path = d / f"w{k}-{i}.cache"
                viewer._cache_put(path, png, {"from": "2026-11-10", "k": k})
                hit = viewer._cache_get(path)
                assert hit is None or (hit[0] == png and hit[1]["k"] == k)
        except Exception as exc:                                      # noqa: BLE001 - collected for the assert
            errors.append(repr(exc))
    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    viewer._evict()
    names = sorted(p.name for p in d.iterdir())
    assert len(names) <= 5 and all(n.endswith(".cache") for n in names), names
    # a broken file is a cache miss, not an error
    (d / "broken.cache").write_bytes(b"not json\n\x00\x01")
    assert viewer._cache_get(d / "broken.cache") is None and viewer._cache_get(d / "missing.cache") is None
    # size limit: the newest files within WIOT_VIEWER_CACHE_MB
    for p in d.iterdir():
        p.unlink()
    monkeypatch.setattr(eo_render, "CACHE_FILES", 50)
    for i in range(3):
        viewer._cache_put(d / f"s{i}.cache", png, {})
        os.utime(d / f"s{i}.cache", (1_700_000_000 + i, 1_700_000_000 + i))
    size = (d / "s0.cache").stat().st_size
    rt.settings.viewer_cache_mb = 2.5 * size / (1024 * 1024)
    viewer._evict()
    assert sorted(p.name for p in d.iterdir()) == ["s1.cache", "s2.cache"]


def test_open_archive_cloud_filter_footprint_and_unreadable_data(farm):
    from wiot.services.eo_render import covers
    rt = farm.app.state.runtime
    rt.settings.satellite_provider = "open"
    http, files, searches = open_archive(rt.settings)
    q = {"mission": "S2L2A", "layer": "NDVI", "west": 28.718, "south": 22.248, "east": 28.722, "north": 22.252,
         "width": 64, "height": 48}

    def with_footprint(geometry):
        def fake(method, url, headers, body, timeout=60):
            status, raw = http(method, url, headers, body, timeout)
            if url == rt.settings.earthsearch_url + "/search":
                data = json.loads(raw)
                for f in data["features"]:
                    f["geometry"] = geometry
                raw = json.dumps(data).encode()
            return status, raw
        return fake
    inside = {"type": "Polygon", "coordinates": [[[28.6, 22.1], [28.9, 22.1], [28.9, 22.4], [28.6, 22.4], [28.6, 22.1]]]}
    strip = {"type": "Polygon", "coordinates": [[[28.6, 22.1], [28.65, 22.1], [28.65, 22.4], [28.6, 22.4], [28.6, 22.1]]]}
    rt.satellite.http = with_footprint(inside)
    assert farm.get("/api/v2/eo/render.png", params={**q, "cloud": 0}).status_code == 200
    assert searches[-1]["query"]["eo:cloud_cover"] == {"lte": 0}               # 0 % means "no cloud at all", inclusive
    assert farm.get("/api/v2/eo/render.png", params={**q, "date": "2026-11-12"}).status_code == 200
    assert "query" not in searches[-1]                                          # a chosen date: every pass of that day
    rt.satellite.http = with_footprint(strip)                                   # data only in a strip west of the view
    r = farm.get("/api/v2/eo/render.png", params={**q, "width": 65})
    assert r.status_code == 404 and "No Sentinel-2 pass" in r.json()["detail"]
    assert covers({"geometry": inside}, 28.72, 22.25) and not covers({"geometry": strip}, 28.72, 22.25)
    assert covers({"bbox": [28.6, 22.1, 28.9, 22.4]}, 28.72, 22.25) and covers({}, 0, 0)
    holed = {"type": "MultiPolygon", "coordinates": [[inside["coordinates"][0],
                                                      [[28.7, 22.2], [28.75, 22.2], [28.75, 22.3], [28.7, 22.3], [28.7, 22.2]]]]}
    assert not covers({"geometry": holed}, 28.72, 22.25) and covers({"geometry": holed}, 28.8, 22.35)
    rt.satellite.http = with_footprint(inside)
    from PIL import Image
    big = farm.get("/api/v2/eo/render.png", params={**q, "width": 1600, "height": 1200, "date": "2026-11-02"})
    assert big.status_code == 200 and Image.open(io.BytesIO(big.content)).size == (1024, 768)   # at most 1024 px
    for url in list(files.files):
        if url.endswith("/red.tif"):
            files.files[url] = files.files[url][:200]                          # a tile cut short by the remote side
    bad = farm.get("/api/v2/eo/render.png", params={**q, "width": 66, "date": "2026-11-07"})
    assert bad.status_code == 502 and "could not be read" in bad.json()["detail"], bad.text


def test_availability_pages_deadline_cache_and_limits(farm, monkeypatch):
    from wiot.api import eo as eo_api
    from wiot.services import eo_render
    rt = farm.app.state.runtime
    pages = []

    def http(method, url, headers, body, timeout=60):
        if url.startswith(rt.settings.cdse_stac_url):
            q = json.loads(body)
            col, start = q["collections"][0], q.get("token", 0)
            total = 250 if col == "sentinel-2-l2a" else 2
            pages.append((col, start))
            feats = [{"id": f"{col}-{i}", "properties": {"datetime": f"2026-11-{1 + i % 9:02d}T08:41:09Z"}}
                     for i in range(start, min(start + 100, total))]
            links = ([{"rel": "next", "href": rt.settings.cdse_stac_url + "/search", "method": "POST", "merge": True,
                       "body": {"token": start + 100}}] if start + 100 < total else [])
            return 200, json.dumps({"features": feats, "links": links, "numberMatched": total}).encode()
        if url.startswith(rt.settings.earthsearch_url):                          # a "next" link to another host is not followed
            return 200, json.dumps({"features": [{"id": "LC09_x", "properties": {"datetime": "2026-11-04T08:31:00Z"}}],
                                    "links": [{"rel": "next", "href": "https://elsewhere.example/x"}]}).encode()
        if "/data/search-products/" in url:
            time.sleep(3.0)                                                     # a catalogue that answers too late
            return 200, json.dumps({"totalResults": 1, "features": []}).encode()
        raise AssertionError(url)
    rt.satellite.http = http
    monkeypatch.setattr(eo_render, "AVAIL_DEADLINE_S", 0.4)
    t0 = time.monotonic()
    d = farm.get("/api/v2/eo/availability", params={"company": "Company_1", "days": 90}).json()
    assert time.monotonic() - t0 < 2.5                                          # the late catalogue does not hold it
    s2 = next(m for m in d["missions"] if m["id"] == "S2L2A")
    assert s2["count"] == 250 and len(s2["items"]) == 250 and s2["exact"] and not s2["partial"]
    assert [p[1] for p in pages if p[0] == "sentinel-2-l2a"] == [0, 100, 200]   # every page, body merged
    landsat = next(m for m in d["missions"] if m["id"] == "LANDSAT")
    assert landsat["ok"] and landsat["count"] == 1
    assert all(not e["ok"] and "no answer within" in e["error"] for e in d["eumetsat"])
    key = next(k for k in rt.satellite.viewer._avail if k[1] == 90)
    assert rt.satellite.viewer._avail[key][0] - time.time() <= eo_render.AVAIL_TTL_FAILED + 1   # failures: short reuse
    monkeypatch.setattr(eo_render, "STAC_MAX_ITEMS", 100)                       # a longer period than the cap holds
    rt.satellite.viewer._avail[("stale",)] = (time.time() - 5, {})
    d30 = farm.get("/api/v2/eo/availability", params={"company": "Company_1", "days": 30}).json()
    s2 = next(m for m in d30["missions"] if m["id"] == "S2L2A")
    assert s2["count"] == 250 and len(s2["items"]) == 100 and s2["exact"] and s2["partial"]
    assert ("stale",) not in rt.satellite.viewer._avail                        # expired answers are dropped
    assert farm.get("/api/v2/eo/availability", params={"company": "Company_1", "days": 45}).status_code == 400
    monkeypatch.setattr(eo_api, "AVAIL_LIMIT", 0)
    assert farm.get("/api/v2/eo/availability", params={"company": "Company_1", "days": 90}).status_code == 429


def test_viewer_follows_the_provider_setting(farm):
    from pydantic import SecretStr
    rt = farm.app.state.runtime
    viewer = rt.satellite.viewer
    rt.settings.sentinel_client_id, rt.settings.sentinel_client_secret = "cid", SecretStr("sec")
    expect = {"auto": ("sentinelhub", "sentinelhub"), "sentinelhub": ("sentinelhub", "sentinelhub"),
              "open": ("open", None), "off": (None, None)}
    for setting, (s2, s1) in expect.items():                  # with the Copernicus client
        rt.settings.satellite_provider = setting
        assert (viewer.provider("S2L2A"), viewer.provider("S1GRD")) == (s2, s1), setting
    rt.settings.sentinel_client_id = None                     # without it
    for setting, s2 in {"auto": "open", "open": "open", "sentinelhub": None, "off": None}.items():
        rt.settings.satellite_provider = setting
        assert viewer.provider("S2L2A") == s2 and viewer.provider("S1GRD") is None, setting
    rt.settings.satellite_provider = "open"
    lay = farm.get("/api/v2/eo/layers", params={"company": "Company_1"}).json()
    assert lay["sentinelhub"] is False and lay["open"] is True
    assert [m["id"] for m in lay["missions"] if m["renderers"]] == ["S2L2A"]
