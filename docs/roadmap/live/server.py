#!/usr/bin/env python3
"""Localhost-only read-only bridge for the live roadmap."""
from __future__ import annotations
import argparse, json, os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))
from collector import collect

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/status":
            try:
                payload = json.dumps(collect(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                payload = json.dumps({"error":type(exc).__name__,"message":"collector unavailable"}).encode()
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            return
        return super().do_GET()

    def do_POST(self):
        self.send_error(405, "Read-only dashboard")
    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def log_message(self, fmt, *args):
        print(f"[roadmap] {self.address_string()} {fmt % args}", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Refusing non-localhost bind")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CompanyQualityResearch live roadmap listening on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()
