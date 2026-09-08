"""Example client for the Atlas account and dashboard API.

Run this from the project folder while server.py is running:
    python example_api.py
"""

import json
import urllib.error
import urllib.request

BASE_URL = "http://localhost:8100"
EMAIL = "example-user@example.com"
PASSWORD = "AtlasExample123"


class ApiClient:
    def __init__(self):
        self.cookies = {}

    def request(self, path, method="GET", payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{BASE_URL}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        if self.cookies:
            request.add_header(
                "Cookie", "; ".join(f"{key}={value}" for key, value in self.cookies.items())
            )

        try:
            with urllib.request.urlopen(request) as response:
                set_cookie = response.headers.get("Set-Cookie", "")
                if set_cookie:
                    self.cookies[set_cookie.split("=", 1)[0]] = set_cookie.split("=", 1)[1].split(";", 1)[0]
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8")
            raise RuntimeError(f"API request failed ({error.code}): {details}") from error


def main():
    client = ApiClient()

    try:
        account = client.request(
            "/api/auth/register",
            method="POST",
            payload={"email": EMAIL, "password": PASSWORD},
        )
    except RuntimeError as error:
        if "already exists" not in str(error):
            raise
        account = client.request(
            "/api/auth/login",
            method="POST",
            payload={"email": EMAIL, "password": PASSWORD},
        )

    print(f"Signed in as {account['user']['email']}")
    before = client.request("/api/dashboard")
    print("Before:", before["metrics"])

    client.request(
        "/api/dashboard",
        method="PATCH",
        payload={
            "metrics": {
                "visits": {"label": "Example visits", "value": 2400},
                "projects": {"label": "Example projects", "value": 31},
                "conversion": {"label": "Example conversion", "value": 21.5},
                "uptime": {"label": "Example uptime", "value": 99.95},
            },
            "preferences": {"accent_color": "#3f62ff", "density": "compact"},
        },
    )

    after = client.request("/api/dashboard")
    print("After:", after["metrics"])
    print("Preferences:", after["preferences"])


if __name__ == "__main__":
    main()
