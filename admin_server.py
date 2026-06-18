#!/usr/bin/env python3
import json
import sqlite3
import urllib.request
import urllib.error
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

# Define the port for the admin server
PORT = 8080
# Bind to loopback ONLY. The served page contains live CDP/Groq keys; '' (all
# interfaces) would expose them to anyone on the local network.
HOST = "127.0.0.1"


class AdminHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # Serve the HTML file directly on the root path
        if self.path == '/' or self.path == '/admin_command_hub.html':
            self.path = 'admin_command_hub.html'
            return super().do_GET()

        # API endpoint to fetch data for the dashboard
        elif self.path == '/api/dashboard_data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            data = {
                "users": self.get_users(),
                "metering": self.get_metering(),
                "telemetry": self.get_telemetry(),
                "groq_status": self.check_groq()
            }
            self.wfile.write(json.dumps(data).encode('utf-8'))
        else:
            self.send_error(404)

    def get_users(self):
        """Reads user data from the local SQLite database."""
        db_path = "railcall_consumers.db"
        if not os.path.exists(db_path):
            return []  # Return empty if db doesn't exist yet

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # Real schema: table 'consumers', column 'free_runs_remaining'
            cursor.execute("SELECT email, free_runs_remaining, runs_used FROM consumers LIMIT 10")
            rows = cursor.fetchall()
            conn.close()
            return [{"email": row[0], "runs": row[1], "used": row[2]} for row in rows]
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return []

    def get_metering(self):
        """Computes real metering from the consumers DB (no fabricated numbers)."""
        db_path = "railcall_consumers.db"
        out = {"total_runs_used": 0, "est_revenue": 0.0, "consumers": 0, "by_status": {}}
        if not os.path.exists(db_path):
            return out
        try:
            conn = sqlite3.connect(db_path)
            rows = list(conn.execute("SELECT runs_used, status FROM consumers"))
            conn.close()
            total = sum((r[0] or 0) for r in rows)
            by_status = {}
            for r in rows:
                by_status[r[1]] = by_status.get(r[1], 0) + 1
            return {
                "total_runs_used": total,
                "est_revenue": round(total * 0.005, 2),
                "consumers": len(rows),
                "by_status": by_status,
            }
        except sqlite3.Error as e:
            print(f"Metering error: {e}")
            return out

    def get_telemetry(self):
        """Reads recent real runs from companion_usage_ledger.jsonl."""
        path = "companion_usage_ledger.jsonl"
        if not os.path.exists(path):
            return []
        entries = []
        try:
            with open(path) as f:
                lines = [l for l in f if l.strip()]
            for line in lines[-12:]:
                try:
                    j = json.loads(line)
                except json.JSONDecodeError:
                    continue
                na = j.get("network_audit") or {}
                ext = None
                if isinstance(na, dict):
                    for k in ("during_call_external_sockets", "external_sockets_open", "after_call_external_sockets"):
                        if k in na:
                            ext = na[k]
                            break
                res = j.get("result")
                if isinstance(res, str) and len(res) > 60:
                    res = res[:60] + "…"
                entries.append({
                    "ran_at": j.get("ran_at"),
                    "run_type": j.get("run_type"),
                    "latency_ms": j.get("latency_ms"),
                    "ext_sockets": ext,
                    "result": res,
                })
        except OSError as e:
            print(f"Telemetry error: {e}")
        return list(reversed(entries))  # newest first

    def check_groq(self):
        """Simple ping to check if Groq API is reachable."""
        try:
            req = urllib.request.Request("https://api.groq.com", method="HEAD")
            urllib.request.urlopen(req, timeout=2)
            return "ONLINE"
        except urllib.error.HTTPError:
            # Got an HTTP response (e.g. 404 on root) = host is reachable.
            return "ONLINE"
        except urllib.error.URLError:
            return "OFFLINE"


def run():
    print(f"Starting Admin Server on {HOST}:{PORT}...")
    print(f"Open http://localhost:{PORT} in your browser.")
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, AdminHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()


if __name__ == '__main__':
    run()
