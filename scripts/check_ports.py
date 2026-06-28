from __future__ import annotations

import json
import socket
from urllib import error, request

PORTS = (8000, 8001, 3000)


def is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_get(port: int, path: str = "/") -> tuple[bool, str]:
    try:
        with request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            return True, f"HTTP {response.status}"
    except error.HTTPError as exc:
        return True, f"HTTP {exc.code}"
    except (OSError, error.URLError, TimeoutError) as exc:
        return False, str(exc)


def health(port: int) -> tuple[bool, str]:
    try:
        with request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("status") == "ok", f"/health {data.get('status')} ({data.get('database', 'unknown')})"
    except error.HTTPError as exc:
        return False, f"/health HTTP {exc.code}"
    except (OSError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return False, f"/health failed: {exc}"


def main() -> int:
    print("preferred backend port: 8001")
    for port in PORTS:
        opened = is_open(port)
        print(f"port {port}: {'open' if opened else 'closed'}")
        if not opened:
            continue
        responded, detail = http_get(port)
        print(f"  http: {'responded' if responded else 'no response'} - {detail}")
        if port in {8000, 8001}:
            ok, status = health(port)
            print(f"  backend: {status}")
            if port == 8000 and not ok:
                print("  warning: port 8000 is occupied but is not this app backend.")
            if port == 8001 and ok:
                print("  ok: 8001 is ready for local real data mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
