import hashlib
import http.cookies
import json
import os
import secrets
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = os.getenv("ATLAS_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", os.getenv("ATLAS_PORT", "8100")))
DATABASE_PATH = Path(os.getenv("ATLAS_DATABASE_PATH", Path(__file__).resolve().parent / "atlas.db"))


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dashboard_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                metric_key TEXT NOT NULL,
                metric_value REAL NOT NULL,
                metric_label TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, metric_key)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS dashboard_preferences (
                user_id INTEGER PRIMARY KEY,
                accent_color TEXT NOT NULL DEFAULT '#ff674d',
                density TEXT NOT NULL DEFAULT 'comfortable',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    )
    return salt, digest.hex()


def verify_password(password, salt, expected_hash):
    _, actual_hash = hash_password(password, salt)
    return secrets.compare_digest(actual_hash, expected_hash)


def json_response(handler, payload, status=200, headers=None):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


class AtlasHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).resolve().parent), **kwargs)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 1_000_000:
            raise ValueError("Request body is too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def get_session_user(self):
        cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        session = cookies.get("atlas_session")
        if not session:
            return None
        with get_connection() as connection:
            return connection.execute(
                """
                SELECT users.id, users.email, users.created_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ?
                """,
                (session.value,),
            ).fetchone()

    def require_user(self):
        user = self.get_session_user()
        if not user:
            json_response(self, {"error": "Authentication required"}, 401)
            return None
        return user

    def do_GET(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return super().do_GET()

        if path == "/api/health":
            return json_response(self, {"ok": True, "service": "atlas-api"})
        if path == "/api/auth/me":
            user = self.get_session_user()
            return json_response(self, {"authenticated": bool(user), "user": dict(user) if user else None})
        if path == "/api/dashboard":
            user = self.require_user()
            if not user:
                return
            with get_connection() as connection:
                metrics = connection.execute(
                    "SELECT metric_key, metric_value, metric_label FROM dashboard_metrics WHERE user_id = ? ORDER BY id",
                    (user["id"],),
                ).fetchall()
                preferences = connection.execute(
                    "SELECT accent_color, density FROM dashboard_preferences WHERE user_id = ?",
                    (user["id"],),
                ).fetchone()
            return json_response(
                self,
                {
                    "user": dict(user),
                    "metrics": [dict(metric) for metric in metrics],
                    "preferences": dict(preferences) if preferences else {"accent_color": "#ff674d", "density": "comfortable"},
                },
            )

        return json_response(self, {"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return json_response(self, {"error": "Not found"}, 404)

        try:
            payload = self.read_json()
        except (ValueError, json.JSONDecodeError):
            return json_response(self, {"error": "Invalid JSON body"}, 400)

        if path == "/api/dashboard/update":
            return self.update_dashboard(payload)

        if path == "/api/auth/register":
            email = str(payload.get("email", "")).strip().lower()
            password = str(payload.get("password", ""))
            if "@" not in email or len(email) > 254:
                return json_response(self, {"error": "Enter a valid email address"}, 400)
            if len(password) < 8:
                return json_response(self, {"error": "Password must be at least 8 characters"}, 400)
            salt, password_hash = hash_password(password)
            try:
                with get_connection() as connection:
                    cursor = connection.execute(
                        "INSERT INTO users (email, password_hash, salt) VALUES (?, ?, ?)",
                        (email, password_hash, salt),
                    )
                    user_id = cursor.lastrowid
                    connection.executemany(
                        "INSERT INTO dashboard_metrics (user_id, metric_key, metric_value, metric_label) VALUES (?, ?, ?, ?)",
                        [
                            (user_id, "visits", 1284, "Monthly visits"),
                            (user_id, "projects", 24, "Active projects"),
                            (user_id, "conversion", 18.6, "Conversion rate"),
                            (user_id, "uptime", 99.9, "Service uptime"),
                        ],
                    )
                    connection.execute("INSERT INTO dashboard_preferences (user_id) VALUES (?)", (user_id,))
            except sqlite3.IntegrityError:
                return json_response(self, {"error": "An account with that email already exists"}, 409)
            return self.create_session(user_id, email)

        if path == "/api/auth/login":
            email = str(payload.get("email", "")).strip().lower()
            password = str(payload.get("password", ""))
            with get_connection() as connection:
                user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user or not verify_password(password, user["salt"], user["password_hash"]):
                return json_response(self, {"error": "Invalid email or password"}, 401)
            return self.create_session(user["id"], user["email"])

        if path == "/api/auth/logout":
            cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            session = cookies.get("atlas_session")
            if session:
                with get_connection() as connection:
                    connection.execute("DELETE FROM sessions WHERE token = ?", (session.value,))
            return json_response(
                self,
                {"ok": True},
                headers={"Set-Cookie": "atlas_session=; HttpOnly; SameSite=Lax; Max-Age=0; Path=/"},
            )

        return json_response(self, {"error": "Not found"}, 404)

    def do_PATCH(self):
        path = urlparse(self.path).path
        if path != "/api/dashboard":
            return json_response(self, {"error": "Not found"}, 404)

        user = self.require_user()
        if not user:
            return

        try:
            payload = self.read_json()
        except (ValueError, json.JSONDecodeError):
            return json_response(self, {"error": "Invalid JSON body"}, 400)

        return self.update_dashboard(payload, user)

    def update_dashboard(self, payload, user=None):
        user = user or self.require_user()
        if not user:
            return

        metrics = payload.get("metrics", {})
        preferences = payload.get("preferences", {})
        if not isinstance(metrics, dict) or not isinstance(preferences, dict):
            return json_response(self, {"error": "Metrics and preferences must be objects"}, 400)

        allowed_metrics = {"visits", "projects", "conversion", "uptime"}
        allowed_density = {"comfortable", "compact"}
        accent_color = preferences.get("accent_color")
        density = preferences.get("density")
        if accent_color is not None and (not isinstance(accent_color, str) or len(accent_color) != 7 or not accent_color.startswith("#")):
            return json_response(self, {"error": "Accent color must be a  six-digit hex color"}, 400)
        if density is not None and density not in allowed_density:
            return json_response(self, {"error": "Density must be comfortable or compact"}, 400)

        with get_connection() as connection:
            for metric_key, changes in metrics.items():
                if metric_key not in allowed_metrics or not isinstance(changes, dict):
                    return json_response(self, {"error": f"Unsupported metric: {metric_key}"}, 400)
                try:
                    metric_value = float(changes["value"])
                except (KeyError, TypeError, ValueError):
                    return json_response(self, {"error": f"Invalid value for {metric_key}"}, 400)
                metric_label = str(changes.get("label", "")).strip()
                if not metric_label or len(metric_label) > 60 or metric_value < 0:
                    return json_response(self, {"error": f"Invalid label or value for {metric_key}"}, 400)
                connection.execute(
                    "UPDATE dashboard_metrics SET metric_value = ?, metric_label = ? WHERE user_id = ? AND metric_key = ?",
                    (metric_value, metric_label, user["id"], metric_key),
                )

            connection.execute(
                "INSERT INTO dashboard_preferences (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING",
                (user["id"],),
            )
            if accent_color is not None or density is not None:
                current = connection.execute(
                    "SELECT accent_color, density FROM dashboard_preferences WHERE user_id = ?",
                    (user["id"],),
                ).fetchone()
                connection.execute(
                    "UPDATE dashboard_preferences SET accent_color = ?, density = ? WHERE user_id = ?",
                    (accent_color or current["accent_color"], density or current["density"], user["id"]),
                )

        return json_response(self, {"ok": True})

    def create_session(self, user_id, email):
        token = secrets.token_urlsafe(32)
        with get_connection() as connection:
            connection.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        headers = {"Set-Cookie": f"atlas_session={token}; HttpOnly; SameSite=Lax; Max-Age=604800; Path=/"}
        return json_response(self, {"user": {"id": user_id, "email": email}}, headers=headers)


def main():
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), AtlasHandler)

    print(f"Serving Atlas from {DATABASE_PATH.parent}")
    print(f"Open http://localhost:{PORT}/")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
