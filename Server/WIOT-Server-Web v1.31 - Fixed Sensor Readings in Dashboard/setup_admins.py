import os
import sqlite3

from werkzeug.security import generate_password_hash


DB_FILE = os.environ.get("WIOT_DB_FILE", "iot_data.db")


def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set before provisioning users")
    return value


accounts = (
    (
        "EgSA_Supervisor",
        required_secret("WIOT_SUPERVISOR_PASSWORD"),
        "admin",
        "",
    ),
    (
        "Super_User",
        required_secret("WIOT_MONITOR_PASSWORD"),
        "monitor",
        "Company_1",
    ),
    (
        "admin_1",
        required_secret("WIOT_COMPANY1_ADMIN_PASSWORD"),
        "admin",
        "Company_1",
    ),
    (
        "admin_2",
        required_secret("WIOT_COMPANY2_ADMIN_PASSWORD"),
        "admin",
        "Company_2",
    ),
)


with sqlite3.connect(DB_FILE) as connection:
    cursor = connection.cursor()
    for username, password, role, company in accounts:
        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        cursor.execute(
            "INSERT INTO users (username, password, role, company) "
            "VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), role, company),
        )

    rows = cursor.execute(
        "SELECT username, role, company FROM users ORDER BY username"
    ).fetchall()

print("Configured users:")
for row in rows:
    print(row)
