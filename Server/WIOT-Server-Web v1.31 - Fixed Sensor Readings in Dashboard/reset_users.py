import os
import sqlite3

from werkzeug.security import generate_password_hash


DB_FILE = os.environ.get("WIOT_DB_FILE", "iot_data.db")


def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set before resetting users")
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
        "Company1_Admin",
        required_secret("WIOT_COMPANY1_ADMIN_PASSWORD"),
        "admin",
        "Company_1",
    ),
    (
        "Company2_Admin",
        required_secret("WIOT_COMPANY2_ADMIN_PASSWORD"),
        "admin",
        "Company_2",
    ),
    (
        "Company1_User",
        required_secret("WIOT_COMPANY1_USER_PASSWORD"),
        "user",
        "Company_1",
    ),
    (
        "Company2_User",
        required_secret("WIOT_COMPANY2_USER_PASSWORD"),
        "user",
        "Company_2",
    ),
)


with sqlite3.connect(DB_FILE) as connection:
    cursor = connection.cursor()
    cursor.execute("DELETE FROM users")
    cursor.executemany(
        "INSERT INTO users (username, password, role, company) "
        "VALUES (?, ?, ?, ?)",
        [
            (username, generate_password_hash(password), role, company)
            for username, password, role, company in accounts
        ],
    )

    rows = cursor.execute(
        "SELECT username, role, company FROM users ORDER BY username"
    ).fetchall()

print("Users reset successfully:")
for row in rows:
    print(row)
