"""Generate the reference part of the server documentation from the code itself.

Writes docs/reference/{API,CONFIG,CLI,DATABASE,MODULES,TESTS,EVENTS}.md. Run after any change:

    .venv\\Scripts\\python docs\\tools\\gen_reference.py

Safe to run: the app is built against a temporary data directory with no .env (no secrets are read,
no broker connection is made); live databases are opened read-only and only their schema is read.
"""
from __future__ import annotations

import ast
import inspect
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "reference"
sys.path.insert(0, str(ROOT))
STAMP = f"_Generated from the code by `docs/tools/gen_reference.py` on {date.today().isoformat()}. Do not edit by hand._\n\n"


def md_cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def write(name: str, title: str, body: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(f"# {title}\n\n{STAMP}{body}", encoding="utf-8")
    print("wrote", (OUT / name).relative_to(ROOT))


# ------------------------------------------------------------------ API
def dep_names(dependant, seen=None) -> list[str]:
    seen = seen if seen is not None else []
    for d in dependant.dependencies:
        name = getattr(d.call, "__name__", type(d.call).__name__)
        if name not in seen:
            seen.append(name)
        dep_names(d, seen)
    return seen


def gen_api() -> None:
    from fastapi.routing import APIRoute, APIWebSocketRoute
    from wiot.api import admin, alerts, auth, commands, farm, operations, org, stream, telemetry
    from wiot.app import API_PREFIX, create_app
    from wiot.config import Settings

    # Same router list and prefixes as wiot/app.py create_app (FastAPI >= 0.16x wraps included routers,
    # so the routes are read from the routers themselves).
    mounted = [(m.router, API_PREFIX) for m in (auth, admin, telemetry, commands, farm, operations, org, alerts)]
    mounted += [(farm.public_router, ""), (stream.router, API_PREFIX), (operations.health_router, "")]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # the app's log file stays open
        settings = Settings(_env_file=None, data_dir=Path(tmp), secret_key="x" * 48)
        app = create_app(settings)
        rows, ws = [], []
        routes = [r for r in app.routes if isinstance(r, (APIRoute, APIWebSocketRoute))]
        for router, prefix in mounted:
            for r in router.routes:
                r.path = prefix + r.path
                routes.append(r)
        for r in routes:
            if isinstance(r, APIRoute):
                deps = [d for d in dep_names(r.dependant) if d not in ("get_runtime", "runtime")]
                doc = (inspect.getdoc(r.endpoint) or r.summary or "").split("\n")[0]
                module = r.endpoint.__module__.replace("wiot.api.", "")
                for m in sorted(r.methods - {"HEAD"}):
                    rows.append((r.path, m, module, r.endpoint.__name__, ", ".join(deps), doc))
            elif isinstance(r, APIWebSocketRoute):
                ws.append((r.path, r.endpoint.__module__, r.endpoint.__name__))
        spec = app.openapi()
    rows.sort()
    paths = len({r[0] for r in rows})
    body = (f"{paths} HTTP paths, {len(rows)} operations (HEAD excluded), {len(ws)} WebSocket route(s); "
            f"OpenAPI documents {len(spec['paths'])} paths. Interactive docs: `/api/docs` on a running server.\n\n"
            "**Dependencies** are the FastAPI dependency functions on each route; they carry authentication "
            "(`current_principal`), role checks (`require_*`, `can_*`) and CSRF checks. Read them in "
            "`wiot/api/deps.py`.\n\n"
            "| Path | Method | Module | Handler | Dependencies | Description |\n|---|---|---|---|---|---|\n")
    body += "".join(f"| `{p}` | {m} | {mod} | `{h}` | {md_cell(d)} | {md_cell(doc)} |\n" for p, m, mod, h, d, doc in rows)
    body += "\n## WebSocket\n\n| Path | Module | Handler |\n|---|---|---|\n"
    body += "".join(f"| `{p}` | {m} | `{h}` |\n" for p, m, h in ws)
    write("API.md", "HTTP and WebSocket API", body)


# --------------------------------------------------------------- config
def gen_config() -> None:
    from wiot.config import Settings
    src = (ROOT / "wiot" / "config.py").read_text(encoding="utf-8")
    comments = {}
    for line in src.splitlines():
        m = re.match(r"\s{4}(\w+):.*?#\s*(.+)$", line)
        if m:
            comments[m.group(1)] = m.group(2)
    rows = []
    for name, f in Settings.model_fields.items():
        default = f.default
        if "secret" in str(f.annotation).lower() or "password" in name or name.endswith("_key") or "key_hex" in name:
            shown = "— (secret; set in `.env`)" if default in (None, "") or True else ""
        elif f.default_factory is not None:
            shown = "computed at start"
        else:
            shown = f"`{default}`" if default not in (None, "") else "—"
        ann = str(f.annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")
        desc = f.description or comments.get(name, "")
        rows.append(f"| `WIOT_{name.upper()}` | {md_cell(ann)} | {md_cell(shown)} | {md_cell(desc)} |")
    body = ("All settings are environment variables with the `WIOT_` prefix, read by pydantic-settings from "
            "the process environment and `.env` (see `.env.example`). Secret values are never shown here.\n\n"
            "| Variable | Type | Default | Notes |\n|---|---|---|---|\n" + "\n".join(rows) + "\n")
    write("CONFIG.md", "Configuration (environment variables)", body)


# ------------------------------------------------------------------ CLI
def gen_cli() -> None:
    py = sys.executable
    top = subprocess.run([py, "-m", "wiot", "--help"], cwd=ROOT, capture_output=True, text=True).stdout
    cmds = re.findall(r"^\s{4}(\w[\w-]*)\s", top, re.M)
    body = "```\n" + top.strip() + "\n```\n"
    for c in dict.fromkeys(cmds):
        h = subprocess.run([py, "-m", "wiot", c, "--help"], cwd=ROOT, capture_output=True, text=True).stdout
        if h.strip():
            body += f"\n## `python -m wiot {c}`\n\n```\n{h.strip()}\n```\n"
    write("CLI.md", "Command-line interface", body)


# ------------------------------------------------------------- database
def gen_database() -> None:
    data = ROOT / "data"
    dbs = [data / n for n in ("iot_data.db", "command_lifecycle.db", "flash_archive.db", "pending_commands.db")]
    tenant = sorted((data / "messages_dbs").glob("*.db"))[:1]
    body = ("Schemas read (read-only) from the live databases in `data/`. One `messages_dbs/<Company>.db` per "
            "tenant has the same schema; one is shown. No data values are included.\n")
    for db in dbs + tenant:
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        label = "messages_dbs/<Company>.db" if db.parent.name == "messages_dbs" else db.name
        body += f"\n## `{label}`\n"
        for name, sql in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table' "
                                     "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            cols = con.execute(f"PRAGMA table_info('{name}')").fetchall()
            body += f"\n### `{name}`\n\n| Column | Type | Not null | Default | PK |\n|---|---|---|---|---|\n"
            body += "".join(f"| `{c[1]}` | {c[2]} | {'yes' if c[3] else ''} | {md_cell(c[4] or '')} | "
                            f"{c[5] or ''} |\n" for c in cols)
            idx = con.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
                              "AND sql IS NOT NULL", (name,)).fetchall()
            if idx:
                body += "\nIndexes: " + "; ".join(f"`{md_cell(s)}`" for _, s in idx) + "\n"
        con.close()
    write("DATABASE.md", "Databases", body)


# -------------------------------------------------------------- modules
def gen_modules() -> None:
    rows = []
    for py in sorted((ROOT / "wiot").rglob("*.py")):
        if py.name == "messages_pb2.py":
            rows.append((py, 0, "Generated protobuf module (from proto/messages.proto); do not edit.", ""))
            continue
        src = py.read_text(encoding="utf-8")
        tree = ast.parse(src)
        doc = (ast.get_docstring(tree) or "").split("\n\n")[0].replace("\n", " ")
        names = [n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                 and not n.name.startswith("_")]
        rows.append((py, len([l for l in src.splitlines() if l.strip()]), doc, ", ".join(names[:14])
                     + (" …" if len(names) > 14 else "")))
    web = sorted((ROOT / "wiot" / "web").rglob("*"))
    body = ("| Module | Lines | Purpose (module docstring) | Public classes and functions |\n|---|---|---|---|\n")
    body += "".join(f"| `{p.relative_to(ROOT).as_posix()}` | {n} | {md_cell(d)} | {md_cell(names)} |\n"
                    for p, n, d, names in rows)
    body += "\n## Web assets (`wiot/web`)\n\n| File | Lines |\n|---|---|\n"
    for f in web:
        if f.is_file() and "vendor" not in f.parts and f.suffix in (".js", ".css", ".html", ".svg"):
            body += f"| `{f.relative_to(ROOT).as_posix()}` | {len(f.read_text(encoding='utf-8', errors='replace').splitlines())} |\n"
    vend = sorted({p.relative_to(ROOT / 'wiot' / 'web' / 'assets' / 'vendor').parts[0]
                   for p in (ROOT / "wiot" / "web" / "assets" / "vendor").rglob("*") if p.is_file()})
    body += f"\nVendored libraries in `wiot/web/assets/vendor/` (served locally, no CDN): {', '.join(vend)}.\n"
    write("MODULES.md", "Code map", body)


# ---------------------------------------------------------------- tests
def gen_tests() -> None:
    r = subprocess.run([sys.executable, "-m", "pytest", "-o", "addopts=", "--collect-only", "-q"], cwd=ROOT,
                       capture_output=True, text=True)
    items = [l for l in r.stdout.splitlines() if "::" in l]
    by_file: dict[str, list[str]] = {}
    for it in items:
        f, _, name = it.partition("::")
        by_file.setdefault(f, []).append(name)
    body = (f"{len(items)} tests collected in {len(by_file)} files. Run: `.venv\\Scripts\\python -m pytest`. "
            "CI: `.github/workflows/server-v2-tests.yml` in the EgSA_IOT repository (Ubuntu / Python 3.12 and "
            "Windows / Python 3.14). Tests that need the live databases in `data/` skip themselves in CI.\n\n"
            "| File | Tests | Names |\n|---|---|---|\n")
    for f, names in by_file.items():
        doc = ""
        try:
            doc = (ast.get_docstring(ast.parse((ROOT / f).read_text(encoding="utf-8"))) or "").split("\n")[0]
        except Exception:
            pass
        body += f"| `{f}` | {len(names)} | {md_cell(doc)}<br>{md_cell(', '.join(n.split('[')[0] for n in dict.fromkeys(names)))} |\n"
    write("TESTS.md", "Automated tests", body)


# --------------------------------------------------------------- events
def gen_events() -> None:
    rows = []
    for py in sorted((ROOT / "wiot").rglob("*.py")):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"\.publish\(\s*\"(\w+)\"", line)
            if m:
                rows.append((m.group(1), f"{py.relative_to(ROOT).as_posix()}:{i}"))
    metrics = []
    for py in sorted((ROOT / "wiot").rglob("*.py")):
        metrics += re.findall(r"(?:Counter|Gauge|Histogram|Summary)\(\s*\"(wiot_\w+)\"\s*,\s*\"([^\"]*)\"",
                              py.read_text(encoding="utf-8"))
    body = ("## Realtime hub events\n\nPublished on the internal hub, delivered to WebSocket clients of the same "
            "tenant (`/api/v2/ws`) and to the webhook service.\n\n| Event | Published at |\n|---|---|\n")
    body += "".join(f"| `{e}` | `{w}` |\n" for e, w in rows)
    body += "\n## Prometheus metrics (`/metrics`)\n\n| Metric | Help |\n|---|---|\n"
    body += "".join(f"| `{n}` | {md_cell(h)} |\n" for n, h in metrics)
    write("EVENTS.md", "Realtime events and metrics", body)


if __name__ == "__main__":
    for fn in (gen_api, gen_config, gen_cli, gen_database, gen_modules, gen_tests, gen_events):
        try:
            fn()
        except Exception as exc:  # keep going so one failure does not hide the others
            print(f"FAILED {fn.__name__}: {exc!r}")
