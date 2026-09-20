import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class JSONHandler(BaseHTTPRequestHandler):
    routes = {}
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

    def _dispatch(self, method):
        path = self.path.split("?")[0]
        for (m, prefix), fn in self.routes.items():
            if m == method and (path == prefix or path.startswith(prefix.rstrip("/") + "/")):
                try:
                    status, obj = fn(self, path, self._body() if method in ("POST", "PUT") else {})
                except Exception as e:  # noqa: BLE001
                    status, obj = 500, {"error": str(e)}
                return self._send(status, obj)
        self._send(404, {"error": "not found"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")


def serve(handler_cls, host, port):
    srv = ThreadingHTTPServer((host, port), handler_cls)
    srv.daemon_threads = True
    return srv
