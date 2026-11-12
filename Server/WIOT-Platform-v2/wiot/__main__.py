"""Command-line entry point: ``python -m wiot <command>``."""
from __future__ import annotations

import argparse
import getpass
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def _settings():
    from .config import get_settings
    return get_settings()


def cmd_serve(args) -> None:
    import uvicorn
    from .app import create_app

    settings = _settings()
    tls = {}
    if settings.tls_certfile and settings.tls_keyfile:
        tls = {"ssl_certfile": str(settings.tls_certfile), "ssl_keyfile": str(settings.tls_keyfile)}
    uvicorn.run(create_app(settings), host=args.host or settings.host, port=args.port or settings.port,
                proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_level="warning",
                ws_ping_interval=20, ws_ping_timeout=20, **tls)


def _backup_password(settings) -> str | None:
    return settings.backup_password.get_secret_value() if settings.backup_password else None


def cmd_backup(args) -> None:
    from .storage.backup import create_backup
    s = _settings()
    dest = args.to or s.backup_dir or (s.data_dir / "backups")
    result = create_backup(s, dest, password=_backup_password(s), keep=args.keep or s.backup_keep)
    if not result["encrypted"]:
        result["warning"] = "Backup is NOT encrypted: set WIOT_BACKUP_PASSWORD to encrypt it"
    print(json.dumps(result, indent=2))
    if result["integrity_problems"]:
        sys.exit(2)


def cmd_verify_backup(args) -> None:
    from .storage.backup import verify_backup
    try:
        print(json.dumps(verify_backup(args.file, _backup_password(_settings())), indent=2))
    except ValueError as exc:
        sys.exit(f"Backup verification FAILED: {exc}")


def cmd_restore_backup(args) -> None:
    from .storage.backup import restore_backup
    try:
        print(json.dumps(restore_backup(args.file, args.to, _backup_password(_settings())), indent=2))
    except ValueError as exc:
        sys.exit(f"Restore refused: {exc}")


def cmd_init(_) -> None:
    from .services.runtime import Runtime
    runtime = Runtime(_settings())
    runtime.main.init_schema()
    s = runtime.settings
    created = runtime.main.bootstrap_users(
        s.admin_password.get_secret_value() if s.admin_password else None,
        s.supervisor_password.get_secret_value() if s.supervisor_password else None,
        s.monitor_password.get_secret_value() if s.monitor_password else None)
    for company in runtime.main.company_names():
        runtime.telemetry.ensure(company)
    print(json.dumps({"data_dir": str(s.data_dir), "created_users": created,
                      "companies": runtime.main.company_names()}, indent=2))


def cmd_create_user(args) -> None:
    from .storage.main_store import MainStore
    store = MainStore(_settings().main_db)
    store.init_schema()
    password = args.password or getpass.getpass("Password: ")
    user_id = store.create_user(args.username, password, args.role, args.company,
                                allow_supervisor=True)
    store.audit("cli", "user_created", company=args.company, target=args.username)
    print(f"Created user #{user_id} {args.username} ({args.role}, {args.company})")


def cmd_reset_password(args) -> None:
    from .storage.main_store import MainStore
    store = MainStore(_settings().main_db)
    store.init_schema()
    user = store.get_user(args.username)
    if user is None:
        sys.exit(f"No such user: {args.username}")
    password = args.password or getpass.getpass("New password: ")
    store.set_password(user["id"], password)
    store.audit("cli", "password_reset", company=user["company"] or None, target=args.username)
    print(f"Password reset for {args.username}; existing sessions revoked")


def _backup(src: Path, dst: Path) -> None:
    """Consistent copy of a live SQLite file using the online backup API."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)) as source, \
            closing(sqlite3.connect(dst)) as target:
        source.backup(target)


def cmd_import_v1(args) -> None:
    src = Path(args.source).resolve()
    dst = _settings().data_dir.resolve()
    if not (src / "iot_data.db").exists():
        sys.exit(f"{src} does not look like a v1.31 server directory (iot_data.db missing)")
    existing = [p for p in (dst / "iot_data.db", dst / "command_lifecycle.db") if p.exists()]
    if existing and not args.force:
        sys.exit(f"{dst} already holds data ({', '.join(p.name for p in existing)}); use --force")
    files = [Path("iot_data.db"), Path("command_lifecycle.db"), Path("flash_archive.db"),
             Path("pending_commands.db")]
    files += [p.relative_to(src) for p in (src / "messages_dbs").glob("*.db")]
    copied = []
    for rel in files:
        if (src / rel).exists():
            _backup(src / rel, dst / rel)
            copied.append(str(rel))
    print(json.dumps({"source": str(src), "target": str(dst), "copied": copied}, indent=2))


def cmd_check(_) -> None:
    from .services.runtime import Runtime
    runtime = Runtime(_settings())
    issues = runtime.telemetry.preflight()
    print(json.dumps({"safe_to_start": not issues, "issues": issues}, indent=2))
    sys.exit(1 if issues else 0)


def cmd_flash_timeline(args) -> None:
    from .tools.flash_timeline import format_text, timeline
    result = timeline(_settings(), args.company, args.region, args.node, args.since, args.until,
                      args.gateway_log, args.tz)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else format_text(result))


def cmd_analyze(args) -> None:
    from .analytics import pipeline
    s = _settings()
    repo_root = args.repo_root or s.repo_root or Path(__file__).resolve().parents[3]
    pipeline.main(["--data-dir", str(s.analytics_data_dir or s.data_dir), "--repo-root", str(repo_root),
                   "--out", str(args.out or s.analytics_path)])


def cmd_simulate(args) -> None:
    from .sim import fleet
    s = _settings()
    key = args.aes_key or (s.mqtt_aes_key_hex.get_secret_value() if s.mqtt_aes_key_hex else None)
    if not key:
        sys.exit("Provide --aes-key or set WIOT_MQTT_AES_KEY_HEX")
    fleet.main(["--host", args.host or s.mqtt_host, "--port", str(args.port or s.mqtt_port),
                "--aes-key", key, "--report-seconds", str(args.report_seconds),
                "--companies", args.companies])


def cmd_devbroker(args) -> None:
    from .sim import devbroker
    devbroker.main(args.host, args.port, bridge=args.bridge,
                   bridge_topics=args.bridge_topic or (["wiot/Company_1/#"] if args.bridge else None))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wiot", description="WIOT Platform v2")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the API + dashboard server")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)

    sub.add_parser("init", help="create databases and built-in accounts").set_defaults(func=cmd_init)

    p = sub.add_parser("create-user", help="add a user")
    p.add_argument("username")
    p.add_argument("--role", choices=("supervisor", "admin", "monitor", "user"), required=True)
    p.add_argument("--company", required=True)
    p.add_argument("--password")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("reset-password", help="set a user's password (revokes sessions)")
    p.add_argument("username")
    p.add_argument("--password")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("import-v1", help="copy databases from a v1.31 server directory")
    p.add_argument("source")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_import_v1)

    sub.add_parser("check", help="tenant storage preflight").set_defaults(func=cmd_check)

    p = sub.add_parser("backup", help="consistent (optionally encrypted) backup of every database")
    p.add_argument("--to", type=Path, help="destination folder (default WIOT_BACKUP_DIR or data/backups)")
    p.add_argument("--keep", type=int, help="backups to keep in the folder (default WIOT_BACKUP_KEEP)")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("verify-backup", help="decrypt and check every database in a backup")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_verify_backup)

    p = sub.add_parser("restore-backup", help="restore a backup into a new, empty data folder")
    p.add_argument("file", type=Path)
    p.add_argument("--to", type=Path, required=True, help="empty folder; then set WIOT_DATA_DIR to it")
    p.set_defaults(func=cmd_restore_backup)

    p = sub.add_parser("flash-timeline", help="diagnose a flash download: server records + gateway serial log")
    p.add_argument("--company", required=True)
    p.add_argument("--region", default="Region_1")
    p.add_argument("--node", type=int, required=True)
    p.add_argument("--since", required=True, help='local time, e.g. "2026-11-09 12:30"')
    p.add_argument("--until", required=True)
    p.add_argument("--gateway-log", type=Path, help="gateway serial log saved by the terminal program")
    p.add_argument("--tz", default="Africa/Cairo")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_flash_timeline)

    p = sub.add_parser("analyze", help="run the analytics + ML pipeline")
    p.add_argument("--repo-root", type=Path)
    p.add_argument("--out", type=Path)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("simulate", help="run an encrypted virtual fleet against a broker")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--aes-key")
    p.add_argument("--companies", default="Company_1,Company_2")
    p.add_argument("--report-seconds", type=float, default=10)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("devbroker", help="start a local development MQTT broker")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--bridge", metavar="HOST[:PORT]",
                   help="also bridge to an upstream broker where field gateways publish (e.g. broker.hivemq.com)")
    p.add_argument("--bridge-topic", action="append", metavar="FILTER",
                   help="topic filter to bridge both ways; repeatable (default: wiot/Company_1/#)")
    p.set_defaults(func=cmd_devbroker)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
