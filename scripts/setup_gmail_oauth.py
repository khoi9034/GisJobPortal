from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from getpass import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import parse, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.email_alerts import DEFAULT_ALERT_QUERY, GMAIL_READONLY_SCOPE, gmail_get  # noqa: E402
from backend.app.paths import load_backend_env  # noqa: E402

TOKEN_PATH = ROOT / "runtime" / "secrets" / "gmail_token.local.json"
ENV_PATH = ROOT / "backend" / ".env"
REDIRECT_URI = "http://127.0.0.1:8765/"
# Scope: https://www.googleapis.com/auth/gmail.readonly


def env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    return "" if not value or value.lower().startswith("replace_") else value


def set_env_line(lines: list[str], name: str, value: str) -> list[str]:
    prefix = f"{name}="
    row = f"{name}={value}"
    return [row if line.startswith(prefix) else line for line in lines] if any(line.startswith(prefix) for line in lines) else [*lines, row]


def save_missing_local_env(client_id: str, client_secret: str) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else [
        "DATABASE_URL=sqlite:///./data/jobs.sqlite3",
        "API_ENV=local",
        "CORS_ORIGINS=http://localhost:3000,https://gis-job-portal.vercel.app",
    ]
    for name, value in {
        "GMAIL_INGESTION_ENABLED": "true",
        "GMAIL_CLIENT_ID": client_id,
        "GMAIL_CLIENT_SECRET": client_secret,
        "GMAIL_TOKEN_PATH": "runtime/secrets/gmail_token.local.json",
        "GMAIL_ALERT_QUERY": DEFAULT_ALERT_QUERY,
    }.items():
        lines = set_env_line(lines, name, value)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


class OAuthHandler(BaseHTTPRequestHandler):
    code = ""
    error = ""

    def log_message(self, *_args):  # keep tokens/codes out of terminal logs
        return

    def do_GET(self):
        params = parse.parse_qs(parse.urlsplit(self.path).query)
        OAuthHandler.code = (params.get("code") or [""])[0]
        OAuthHandler.error = (params.get("error") or [""])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Gmail authorization received. You can close this window.")


def exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    payload = parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = request.Request("https://oauth2.googleapis.com/token", data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with request.urlopen(req, timeout=30) as response:
        token = json.loads(response.read().decode("utf-8"))
    if token.get("expires_in"):
        token["expires_at"] = int(time.time()) + int(token["expires_in"])
    return token


def main() -> int:
    load_backend_env()
    client_id = env_value("GMAIL_CLIENT_ID")
    client_secret = env_value("GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Gmail OAuth credentials are missing from backend/.env.")
        client_id = getpass("Paste Gmail OAuth client ID: ").strip()
        client_secret = getpass("Paste Gmail OAuth client secret: ").strip()
        if not client_id or not client_secret:
            print("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are required.")
            return 1
        save_missing_local_env(client_id, client_secret)
        print("Saved Gmail OAuth credentials to ignored backend/.env.")

    params = parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": GMAIL_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    server = HTTPServer(("127.0.0.1", 8765), OAuthHandler)
    print("Opening browser for Gmail read-only OAuth consent...")
    webbrowser.open(url)
    server.handle_request()
    server.server_close()
    if OAuthHandler.error or not OAuthHandler.code:
        print("Gmail OAuth did not complete.")
        return 1

    token = exchange_code(OAuthHandler.code, client_id, client_secret)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token, indent=2), encoding="utf-8")
    profile = gmail_get("/profile", config={"client_id": client_id, "client_secret": client_secret}, token=token)
    print("Gmail OAuth configured successfully.")
    print(f"Token saved locally under: {TOKEN_PATH.relative_to(ROOT)}")
    print(f"Authenticated Gmail profile: {profile.get('emailAddress', 'verified')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
