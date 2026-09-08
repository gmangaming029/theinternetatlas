"""Example client for the Atlas account and dashboard API.

Run this from the project folder while server.py is running:
    python example_api.py
    python example_api.py --email you@example.com
    python example_api.py --email you@example.com --password your-password
    python example_api.py --email you@example.com --register
"""

import argparse
import getpass
import json
import urllib.error
import urllib.request

BASE_URL = "http://localhost:8100"


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


def parse_arguments():
    parser = argparse.ArgumentParser(description="Example client for the Atlas API")
    parser.add_argument("--email", help="Account email; prompted when omitted")
    parser.add_argument("--password", help="Account password; prompted securely when omitted")
    parser.add_argument("--register", action="store_true", help="Create the account before updating the dashboard")
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    email = arguments.email or input("Email: ").strip()
    password = arguments.password or getpass.getpass("Password: ")
    client = ApiClient()

    if arguments.register:
        account = client.request(
            "/api/auth/register",
            method="POST",
            payload={"email": email, "password": password},
        )
    else:
        account = client.request(
            "/api/auth/login",
            method="POST",
            payload={"email": email, "password": password},
        )

    print(f"Signed in as {account['user']['email']}")
    before = client.request("/api/dashboard")
    print("Before:", before["metrics"])

    client.request(
        "/api/dashboard/update",
        method="POST",
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
