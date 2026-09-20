"""Small HTTP client with wall-clock deadlines.

Socket timeouts behaved inconsistently on the gateway box (see ticket T-0188), so every call here
is driven by a deadline on time.time() and a non-blocking socket.
"""
import json
import select
import socket
import time
import urllib.parse


class CallTimeout(Exception):
    pass


def http_call(url, method="GET", body=None, timeout_s=10.0, headers=None):
    u = urllib.parse.urlsplit(url)
    host, port = u.hostname, u.port or 80
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    hdrs = {"Host": f"{host}:{port}", "Connection": "close", "Content-Type": "application/json"}
    hdrs.update(headers or {})
    if data is not None:
        hdrs["Content-Length"] = str(len(data))
    req = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hdrs.items()) + "\r\n"
    payload = req.encode() + (data or b"")
    deadline = time.time() + timeout_s
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setblocking(False)
    try:
        try:
            s.connect((host, port))
        except BlockingIOError:
            pass
        while True:
            _, w, _ = select.select([], [s], [], 0.001)
            if w:
                err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err:
                    raise ConnectionError(f"connect failed: {err}")
                break
            if time.time() > deadline:
                raise CallTimeout("connect deadline")
        s.sendall(payload)
        buf = b""
        while True:
            r, _, _ = select.select([s], [], [], 0.001)
            if r:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"\r\n\r\n" in buf:
                    head, _, rest = buf.partition(b"\r\n\r\n")
                    m = [l for l in head.split(b"\r\n") if l.lower().startswith(b"content-length:")]
                    if m and len(rest) >= int(m[0].split(b":")[1].strip()):
                        break
            if time.time() > deadline:
                raise CallTimeout("response deadline")
    finally:
        s.close()
    head, _, rest = buf.partition(b"\r\n\r\n")
    parts = head.split(b" ")
    if len(parts) < 2 or not parts[1].isdigit():
        raise ConnectionError("empty or malformed response")
    status = int(parts[1])
    text = rest.decode(errors="replace")
    try:
        parsed = json.loads(text) if text else None
    except json.JSONDecodeError:
        parsed = text
    return status, parsed


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
