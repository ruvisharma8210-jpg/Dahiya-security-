"""Render free Web Service ke liye chhota HTTP server (PORT par 'OK' deta hai). Flask ki zaroorat nahi."""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - bot running")

    do_HEAD = do_GET

    def log_message(self, *a):
        pass


def start():
    port = os.getenv("PORT")
    if not port:
        return  # local / background worker: server ki zaroorat nahi
    srv = HTTPServer(("0.0.0.0", int(port)), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
