"""Release 2.7: Earth observation - open Sentinel-2 NDVI, Copernicus catalogue, EUMETSAT Data Store."""
from __future__ import annotations

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
            assert q["collections"] == ["sentinel-2-l2a"] and q["query"]["eo:cloud_cover"]["lt"] == 60
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
