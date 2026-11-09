"""Project-wide statistics: firmware footprint per build profile, power-guard verification, code size.

Firmware sizes are read from the ``IoT_Node_Encrypted.ino.elf`` produced in every build-profile
folder (``Documentation/FirmwareBuild*_YYYYMMDD/<profile>/``) using the same rule as the
STM32duino ``arduino-cli`` size recipe: flash = ``.text + .rodata + .data``, RAM =
``.data + .bss + .noinit``. This reproduces the logs exactly (e.g. node2-wor 20261030:
102,788 B flash / 34,500 B RAM). ``Sketch uses ...`` lines in standalone build logs are parsed
too, as extra trend points. The ``backups/`` directory is never visited.
"""
from __future__ import annotations

import json
import os
import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

FLASH_MAX_DEFAULT, RAM_MAX_DEFAULT = 262144, 65536   # STM32F401CC BlackPill ("Maximum is ..." in the logs)
EEPROM_SECTOR = 0x08020000                           # "below EEPROM sector 0x08020000" in build-matrix logs
FLASH_BASE = 0x08000000

_BUILD_DIR = re.compile(r"^FirmwareBuild(?P<label>[A-Za-z]*)_(?P<date>\d{8})$")
_SKETCH = re.compile(r"Sketch uses (\d+) bytes \((\d+)%\) of program storage space\. Maximum is (\d+) bytes")
_GLOBALS = re.compile(r"Global variables use (\d+) bytes \((\d+)%\) of dynamic memory.*Maximum is (\d+) bytes")
_BUILDING = re.compile(r"^Building (\S+)")
_PASS = re.compile(r"PASS (\S+); flash load ends at (0x[0-9A-Fa-f]+)")
_START = re.compile(r"Start time: (\d{8})")


# ---------------------------------------------------------------------------
# ELF parsing (32-bit little-endian ARM)
# ---------------------------------------------------------------------------
def elf_section_sizes(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError(f"not a 32-bit little-endian ELF: {path}")
    shoff = struct.unpack_from("<I", data, 0x20)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", data, 0x2E)
    headers = [struct.unpack_from("<IIIIIIIIII", data, shoff + i * shentsize) for i in range(shnum)]
    str_off = headers[shstrndx][4]
    sizes = {}
    for h in headers:
        start = str_off + h[0]
        name = data[start:data.index(b"\0", start)].decode("ascii", "replace")
        sizes[name] = h[5]
    return sizes


def elf_usage(path: Path) -> tuple[int, int]:
    s = elf_section_sizes(path)
    flash = s.get(".text", 0) + s.get(".rodata", 0) + s.get(".data", 0)
    ram = s.get(".data", 0) + s.get(".bss", 0) + s.get(".noinit", 0)
    return flash, ram


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
def parse_build_log(path: Path) -> list[dict[str, Any]]:
    """Profiles in a build log: sizes from 'Sketch uses' lines and flash end from 'PASS' lines."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: dict[str, dict[str, Any]] = {}
    current = None
    for line in lines:
        if m := _BUILDING.match(line.strip()):
            current = m.group(1)
            out.setdefault(current, {"profile": current})
        elif current and (m := _SKETCH.search(line)):
            out[current].update(flash_bytes=int(m.group(1)), flash_max=int(m.group(3)))
        elif current and (m := _GLOBALS.search(line)):
            out[current].update(ram_bytes=int(m.group(1)), ram_max=int(m.group(3)))
        if m := _PASS.search(line):
            out.setdefault(m.group(1), {"profile": m.group(1)})["flash_end"] = int(m.group(2), 16)
    return list(out.values())


def _log_date(path: Path) -> str:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        head = ""
    if m := _START.search(head):
        return m.group(1)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y%m%d")


def firmware_stats(repo_root: Path) -> dict[str, Any]:
    doc = repo_root / "Documentation"
    entries: list[dict[str, Any]] = []
    flash_end: dict[tuple[str, str], int] = {}
    if doc.is_dir():
        for build_dir in sorted(p for p in doc.iterdir() if p.is_dir() and _BUILD_DIR.match(p.name)):
            date = _BUILD_DIR.match(build_dir.name).group("date")
            for log in build_dir.glob("*.log"):
                for rec in parse_build_log(log):
                    if "flash_end" in rec:
                        flash_end[(build_dir.name, rec["profile"])] = rec["flash_end"]
            for prof in sorted(p for p in build_dir.iterdir() if p.is_dir()):
                elf = next(prof.glob("*.ino.elf"), None)
                if elf is None:
                    continue
                flash, ram = elf_usage(elf)
                entries.append({"build": build_dir.name, "date": date, "profile": prof.name, "flash_bytes": flash,
                                "ram_bytes": ram, "source": "elf", "built_at": int(elf.stat().st_mtime)})
    log_points = []
    if doc.is_dir():
        for log in sorted(doc.rglob("*.log")):
            if any(part.startswith("FirmwareBuild") for part in log.relative_to(doc).parts[:-1]):
                continue
            for rec in parse_build_log(log):
                if "flash_bytes" in rec:
                    log_points.append({"build": log.stem, "date": _log_date(log), "profile": rec["profile"],
                                       "flash_bytes": rec["flash_bytes"], "ram_bytes": rec.get("ram_bytes"),
                                       "source": f"log:{log.relative_to(doc).as_posix()}"})
    flash_max, ram_max = FLASH_MAX_DEFAULT, RAM_MAX_DEFAULT
    latest: dict[str, dict] = {}
    for e in entries:
        if e["profile"] not in latest or (e["date"], e["built_at"]) > (latest[e["profile"]]["date"], latest[e["profile"]]["built_at"]):
            latest[e["profile"]] = e
    profiles = []
    for name in sorted(latest):
        e = latest[name]
        end = flash_end.get((e["build"], name))
        profiles.append({"name": name, "build": e["build"], "date": e["date"],
                         "flash_bytes": e["flash_bytes"], "flash_pct": 100.0 * e["flash_bytes"] / flash_max,
                         "flash_max": flash_max, "ram_bytes": e["ram_bytes"],
                         "ram_pct": 100.0 * e["ram_bytes"] / ram_max, "ram_max": ram_max,
                         "flash_end": hex(end) if end else None,
                         "eeprom_headroom_bytes": EEPROM_SECTOR - end if end else None})
    trend = sorted(({k: e[k] for k in ("build", "date", "profile", "flash_bytes", "ram_bytes", "source")}
                    for e in entries + log_points), key=lambda r: (r["date"], r["profile"], r["build"]))
    return {"profiles": profiles, "trend": trend, "n_builds": len({e["build"] for e in entries}),
            "method": "flash = .text + .rodata + .data and RAM = .data + .bss + .noinit from each profile's ELF "
                      "(STM32duino size recipe); percentages of 256 KiB flash / 64 KiB RAM (STM32F401CC). "
                      "eeprom_headroom_bytes = bytes between the end of the flash image and the EEPROM-emulation "
                      "sector at 0x08020000 (the effective application limit is 128 KiB)."}


def power_guard_stats(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "Documentation" / "PowerModes" / "power_combination_verification.json"
    if not path.exists():
        return {"available": False}
    d = json.loads(path.read_text(encoding="utf-8"))
    cases = d.get("cases", [])

    def group(key: str) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for c in cases:
            g = out.setdefault(str(c.get(key)), {"total": 0, "accepted": 0, "rejected": 0, "passed": 0})
            g["total"] += 1
            g["accepted" if c.get("accepted") else "rejected"] += 1
            g["passed"] += int(bool(c.get("passed")))
        return out

    accepted = [{k: c.get(k) for k in ("role", "transport", "controller", "lora", "wifi", "sim", "wor_tx")}
                for c in cases if c.get("accepted")]
    return {"available": True, "firmware_revision": d.get("firmware_revision"), "scope": d.get("scope"),
            "total": int(d.get("total", len(cases))), "accepted": int(d.get("accepted", len(accepted))),
            "rejected": int(d.get("rejected", len(cases) - len(accepted))),
            "all_passed": bool(d.get("all_passed", all(c.get("passed") for c in cases))),
            "passed_cases": int(sum(bool(c.get("passed")) for c in cases)),
            "by_role": group("role"), "by_transport": group("transport"), "accepted_cases": accepted}


# ---------------------------------------------------------------------------
# Lines of code
# ---------------------------------------------------------------------------
SKIP_DIRS = {"backups", ".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", "cache", "temp",
             "tmp", "Debug", "Release", "Doxygen", "html", "latex", ".vscode", ".kilo", ".settings", ".idea",
             ".pytest_cache", "compiler-temporary", "site-packages"}
SOURCE_EXT = {".c", ".h", ".cpp", ".hpp", ".ino", ".s", ".py", ".js", ".css", ".html", ".md", ".ps1"}
LANGUAGE = {".c": "C", ".h": "C/C++ header", ".cpp": "C++", ".hpp": "C++ header", ".ino": "Arduino C++",
            ".s": "ARM assembly", ".py": "Python", ".js": "JavaScript", ".css": "CSS", ".html": "HTML",
            ".md": "Markdown", ".ps1": "PowerShell"}


def iter_source_files(root: Path, exclude: tuple[Path, ...] = ()) -> Iterator[Path]:
    excluded = {p.resolve() for p in exclude}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith("FirmwareBuild")
                       and not (rel == Path(".") and d == "backups")
                       and (Path(dirpath) / d).resolve() not in excluded]
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix.lower() in SOURCE_EXT:
                yield p


def is_generated(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (name.endswith((".pb.c", ".pb.h", "_pb2.py")) or "/generated/" in f"/{rel}"
            or name.startswith("generated_"))


def is_vendor(rel: str) -> bool:
    return rel.startswith(("WIOT_STM32CubeIDE/Drivers/", "WIOT_STM32CubeIDE/Middlewares/")) or "/third_party/" in rel


def is_test(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return any(p in ("tests", "test") for p in parts[:-1]) or name.startswith("test_") or \
        name.endswith(("_test.py", "_test.cpp"))


COMPONENTS: list[tuple[str, str, tuple[str, ...], str]] = [
    # (name, path prefix, extensions, language label)
    ("STM32 Arduino firmware", "Node/IoT_Node_Encrypted/", (".ino", ".cpp", ".h", ".c", ".hpp"), "C/C++ (Arduino)"),
    ("STM32CubeIDE firmware", "WIOT_STM32CubeIDE/", (".c", ".h", ".cpp", ".hpp", ".s"), "C (HAL)"),
    ("ESP32 firmware", "esp32/", (".ino", ".cpp", ".h", ".c"), "C/C++ (Arduino)"),
    ("Server Platform v2 (Python)", "Server/WIOT-Platform-v2/", (".py",), "Python"),
    ("Server v1.31 legacy (Python)", "Server/WIOT-Server-Web", (".py",), "Python"),
    ("Web dashboard (JS/CSS/HTML)", "Server/", (".js", ".css", ".html"), "JavaScript/CSS/HTML"),
    ("Sensor simulators & tools (SENSORS)", "SENSORS/", (".py",), "Python"),
    ("Bench test sketches", "Test_", (".ino", ".py", ".cpp", ".h"), "C++/Python"),
    ("Build & validation scripts", "", (".ps1",), "PowerShell"),
    ("Documentation tooling (Python)", "Documentation/", (".py",), "Python"),
    ("Repository tooling (Python)", "", (".py",), "Python"),
]


def _count_lines(path: Path) -> tuple[int, int]:
    try:
        text = path.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return 0, 0
    lines = text.splitlines()
    return len(lines), sum(1 for ln in lines if ln.strip())


def _classify(rel: str) -> str | None:
    ext = Path(rel).suffix.lower()
    if ext == ".md":
        return "Documentation (Markdown)"
    for name, prefix, exts, _ in COMPONENTS:
        if ext in exts and rel.startswith(prefix):
            if name == "Repository tooling (Python)" and "/" in rel:
                continue
            return name
    return None


_PY_TEST = re.compile(r"^\s*(?:async\s+)?def\s+test_\w*\s*\(", re.M)
_CPP_CASE = re.compile(r'name\s*==\s*"([^"]+)"')


def project_stats(repo_root: Path, exclude: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Code size per component. ``exclude`` lists folders to skip (e.g. the pipeline's own output)."""
    exclude = tuple(exclude) + (repo_root / "Server" / "WIOT-Platform-v2" / "data",)
    comp: dict[str, dict[str, Any]] = {}
    generated = {"files": 0, "lines": 0, "examples": []}
    vendor = {"files": 0, "lines": 0}
    tests = {"files": 0, "lines": 0, "functions": 0, "python_files": 0, "python_test_functions": 0,
             "cpp_files": 0, "cpp_test_cases": 0, "by_area": {}}
    for path in iter_source_files(repo_root, exclude):
        rel = path.relative_to(repo_root).as_posix()
        total, nonblank = _count_lines(path)
        if is_generated(rel):
            generated["files"] += 1; generated["lines"] += nonblank
            if len(generated["examples"]) < 10:
                generated["examples"].append(rel)
            continue
        if is_vendor(rel):
            vendor["files"] += 1; vendor["lines"] += nonblank
            continue
        if is_test(rel) and path.suffix.lower() in (".py", ".cpp", ".h", ".ps1", ".c"):
            tests["files"] += 1; tests["lines"] += nonblank
            area = rel.split("/")[0]
            tests["by_area"][area] = tests["by_area"].get(area, 0) + 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            if path.suffix == ".py" and (path.name.startswith("test_") or path.name.endswith("_test.py")):
                n = len(_PY_TEST.findall(text))
                tests["python_files"] += 1; tests["python_test_functions"] += n
            elif path.name.endswith("_test.cpp"):
                cases = set(_CPP_CASE.findall(text))
                tests["cpp_files"] += 1; tests["cpp_test_cases"] += max(1, len(cases))
            continue
        name = _classify(rel)
        if name is None:
            continue
        c = comp.setdefault(name, {"name": name, "files": 0, "lines": 0, "total_lines": 0, "path": "", "language": ""})
        c["files"] += 1; c["lines"] += nonblank; c["total_lines"] += total
    meta = {n: (p, lang) for n, p, _, lang in COMPONENTS}
    meta["Documentation (Markdown)"] = ("**/*.md", "Markdown")
    for name, c in comp.items():
        c["path"], c["language"] = meta.get(name, ("", ""))
        c["path"] = c["path"] or "(repository-wide)"
    tests["functions"] = tests["python_test_functions"] + tests["cpp_test_cases"]
    components = sorted(comp.values(), key=lambda c: -c["lines"])
    components.append({"name": "Tests (all areas)", "path": "**/tests/, test_*.py, *_test.cpp", "files": tests["files"],
                       "lines": tests["lines"], "total_lines": None, "language": "Python/C++/PowerShell"})
    totals = {"files": sum(c["files"] for c in components), "lines": sum(c["lines"] for c in components)}
    return {"components": components, "generated": generated, "vendor": vendor, "tests": tests, "totals": totals,
            "method": "non-blank lines; excludes backups/, runtime data folders (incl. this pipeline's output), "
                      ".git, node_modules, __pycache__, virtualenvs, build/dist/cache folders, Doxygen output and Documentation/FirmwareBuild* build trees. Generated code (*.pb.c, "
                      "*.pb.h, *_pb2.py, generated/ folders) and vendor code (STM32 HAL/CMSIS Drivers, third_party/) "
                      "are counted separately and not included in totals. C++ host-test cases are counted as distinct "
                      "scenario names (name == \"...\") per *_test.cpp file (minimum 1)."}
