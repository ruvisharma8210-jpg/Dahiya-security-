"""Render free Web Service ke liye chhota HTTP server (PORT par 'OK' deta hai) + self-ping.

Render free service 15 minute tak koi bahar se request na aaye to SO jaata hai — tab polling bhi
ruk jaati hai aur bot jawab dena band kar deta hai. Isliye har 10 minute me bot apne hi public URL
(RENDER_EXTERNAL_URL, Render khud set karta hai) ko ping karta hai, taaki service jaagti rahe.
Flask ki zaroorat nahi.
"""
import logging
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger(__name__)
PING_EVERY = 10 * 60  # seconds — Render 15 min me sulata hai


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"OK - bot running")

    do_HEAD = do_GET

    def log_message(self, *a):
        pass


def _self_ping(url: str) -> None:
    url = url.rstrip("/") + "/"
    while True:
        time.sleep(PING_EVERY)
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                r.read(64)
        except Exception as e:
            log.warning("keepalive ping fail (%s): %s", url, e)


def start():
    port = os.getenv("PORT")
    if not port:
        return  # local / background worker: server ki zaroorat nahi
    srv = HTTPServer(("0.0.0.0", int(port)), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEPALIVE_URL") or "").strip()
    if url:
        threading.Thread(target=_self_ping, args=(url,), daemon=True).start()
        log.info("Keepalive: har %d min me %s ping hoga (Render sleep se bachne ke liye)", PING_EVERY // 60, url)
    else:
        log.warning("Keepalive URL nahi mila (RENDER_EXTERNAL_URL/KEEPALIVE_URL) — free service so sakti hai")
