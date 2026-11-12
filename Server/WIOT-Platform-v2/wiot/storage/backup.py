"""Consistent, optionally encrypted backups of every database, with verification and restore (R2.1, point 6).

``create_backup`` copies each SQLite database with the online-backup API (safe while the server runs),
checks each copy with ``PRAGMA integrity_check``, writes a manifest with SHA-256 digests and zips the set.
With a password the zip is encrypted with AES-256-GCM in 4 MiB chunks (key from scrypt), so a stolen
backup reveals nothing and a corrupted or truncated one fails verification instead of restoring silently.

File format of ``*.wbk`` (encrypted): ``b"WIOTBK1\\n"`` | salt (16) | nonce prefix (8) | chunks, each
``length (4, big-endian)`` | ciphertext+tag; the chunk number is the nonce suffix and the last chunk is
authenticated with the associated data ``b"last"``. Unencrypted backups are plain ``*.zip`` files.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import struct
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

MAGIC = b"WIOTBK1\n"
CHUNK = 4 * 1024 * 1024
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


def database_files(settings) -> list[Path]:
    """Every database the platform owns (analytics artifacts and logs are regenerable and skipped)."""
    files = [settings.main_db, settings.command_db, settings.flash_db, settings.legacy_command_db]
    files += sorted(Path(settings.messages_dir).glob("*.db"))
    return [Path(f) for f in files if Path(f).exists()]


def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, **SCRYPT).derive(password.encode("utf-8"))


def _encrypt(src: Path, dst: Path, password: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, prefix = os.urandom(16), os.urandom(8)
    aead = AESGCM(_key(password, salt))
    size, done, index = src.stat().st_size, 0, 0
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(MAGIC + salt + prefix)
        while True:
            block = fin.read(CHUNK)
            done += len(block)
            last = done >= size
            ct = aead.encrypt(prefix + struct.pack(">I", index), block, b"last" if last else b"")
            fout.write(struct.pack(">I", len(ct)) + ct)
            index += 1
            if last:
                break


def _decrypt(src: Path, dst: Path, password: str) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        if fin.read(len(MAGIC)) != MAGIC:
            raise ValueError("Not a WIOT encrypted backup")
        salt, prefix = fin.read(16), fin.read(8)
        aead = AESGCM(_key(password, salt))
        index, finished = 0, False
        while True:
            head = fin.read(4)
            if not head:
                break
            ct = fin.read(struct.unpack(">I", head)[0])
            if finished:
                raise ValueError("Data after the final chunk: backup tampered with")
            nonce = prefix + struct.pack(">I", index)
            try:
                fout.write(aead.decrypt(nonce, ct, b"last"))
                finished = True
            except InvalidTag:
                try:
                    fout.write(aead.decrypt(nonce, ct, b""))
                except InvalidTag as exc:
                    raise ValueError("Wrong password, or the backup is damaged") from exc
            index += 1
        if not finished:
            raise ValueError("Backup is truncated (final chunk missing)")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def create_backup(settings, dest: Path, *, password: str | None = None, keep: int = 14) -> dict:
    """Write one backup into ``dest``; prune to the newest ``keep`` backups there. Returns a summary."""
    from .. import __version__
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    data_dir = Path(settings.data_dir)
    manifest = {"format": 1, "created_at": int(time.time()), "platform_version": __version__, "files": []}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for src in database_files(settings):
            rel = src.relative_to(data_dir) if src.is_relative_to(data_dir) else Path(src.name)
            target = tmp / "data" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)) as source, \
                    closing(sqlite3.connect(target)) as copy:
                source.backup(copy)
                integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
            manifest["files"].append({"path": rel.as_posix(), "bytes": target.stat().st_size,
                                      "sha256": _sha256(target), "integrity": integrity})
        zpath = tmp / f"wiot-backup-{stamp}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            for f in manifest["files"]:
                z.write(tmp / "data" / f["path"], "data/" + f["path"])
        if password:
            out = dest / f"wiot-backup-{stamp}.wbk"
            _encrypt(zpath, out, password)
        else:
            out = dest / zpath.name
            shutil.copyfile(zpath, out)
    backups = sorted([p for p in dest.glob("wiot-backup-*") if p.suffix in (".zip", ".wbk")], key=lambda p: p.name)
    removed = [p.name for p in backups[:-keep]] if keep > 0 else []
    for name in removed:
        (dest / name).unlink(missing_ok=True)
    bad = [f["path"] for f in manifest["files"] if f["integrity"] != "ok"]
    return {"file": str(out), "bytes": out.stat().st_size, "encrypted": bool(password),
            "databases": len(manifest["files"]), "integrity_problems": bad, "pruned": removed}


def _open_zip(path: Path, password: str | None, workdir: Path) -> Path:
    path = Path(path)
    if path.suffix == ".wbk":
        if not password:
            raise ValueError("This backup is encrypted: set the backup password")
        plain = workdir / "backup.zip"
        _decrypt(path, plain, password)
        return plain
    return path


def verify_backup(path: Path, password: str | None = None) -> dict:
    """Decrypt, unzip and check every database in a backup (digest and integrity). Raises on failure."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath = _open_zip(path, password, tmp)
        with zipfile.ZipFile(zpath) as z:
            manifest = json.loads(z.read("manifest.json"))
            z.extractall(tmp / "x")
        problems, tables = [], 0
        for f in manifest["files"]:
            p = tmp / "x" / "data" / f["path"]
            if not p.exists() or _sha256(p) != f["sha256"]:
                problems.append(f"{f['path']}: digest mismatch")
                continue
            with closing(sqlite3.connect(p)) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append(f"{f['path']}: integrity check failed")
                tables += db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        if problems:
            raise ValueError("; ".join(problems))
        return {"file": str(path), "created_at": manifest["created_at"], "databases": len(manifest["files"]),
                "tables": tables, "platform_version": manifest.get("platform_version"), "ok": True}


def restore_backup(path: Path, target_dir: Path, password: str | None = None) -> dict:
    """Restore into an empty directory (never over live data); point WIOT_DATA_DIR there to use it."""
    target_dir = Path(target_dir)
    if target_dir.exists() and any(target_dir.iterdir()):
        raise ValueError(f"{target_dir} is not empty; restore into a new, empty directory")
    summary = verify_backup(path, password)
    with tempfile.TemporaryDirectory() as tmp:
        zpath = _open_zip(path, password, Path(tmp))
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if name.startswith("data/") and not name.endswith("/"):
                    out = target_dir / name[len("data/"):]
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(name) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    return {**summary, "restored_to": str(target_dir)}
