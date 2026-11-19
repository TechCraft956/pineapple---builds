#!/usr/bin/env python3
"""
PINEAPPLE NETWORK OS - local web dashboard (local-first, actionable).

Read-only views + action buttons (run brief / intake / scan) that call the same
engines as the TUI and GUI. Binds to 127.0.0.1 ONLY. No public exposure at v1;
remote later via VPN/Tailscale/Cloudflare Tunnel.

    python dashboard.py                 # http://127.0.0.1:8800
    python dashboard.py --port 8801 --selftest   # render once + exit
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NET = Path(__file__).resolve().parent
ROOT = NET.parent
sys.path.insert(0, str(ROOT / "_lib"))
import pineapple_api as api  # noqa: E402


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(msg=""):
    users = api.network_users()
    b = api.brief()
    sc = api.scan_stats()
    plugins = api.plugins()
    st = api.learning_stats()
    evo = api.evolution()
    evr = evo.get("review", {})
    questions = evo.get("questions", [])
    backlog = sorted(evo.get("backlog", []), key=lambda x: x.get("priority", 0), reverse=True)
    caps = evo.get("registry", [])
    roadmap = evo.get("roadmap", {})
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    user_rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
        (esc(u["username"]), esc(u["role"]), esc(u.get("plan", "")), "YES" if u.get("is_owner") else "-")
        for u in users) or "<tr><td colspan=4>No users</td></tr>"
    action_rows = "".join("<tr><td>%d</td><td>%.1f</td><td>%s</td><td>%s</td></tr>" %
        (i, a.get("quant", 0), esc(a.get("category", "")), esc(a.get("title", "")[:48]))
        for i, a in enumerate(b.get("top_actions", [])[:10], 1)) or "<tr><td colspan=4>Run the brief</td></tr>"
    plug_html = "".join("<span class='chip %s'>%s</span>" %
        ("on" if p["status"] == "implemented" else "off", esc(p["id"])) for p in plugins)
    q_rows = "".join("<tr><td>%d</td><td>%s</td><td>%d</td><td>%s<br><span class=k>%s</span></td></tr>" %
        (i, esc(q.get("category", "")), q.get("priority", 0), esc(q.get("question", "")), esc(q.get("reason_for_asking", "")))
        for i, q in enumerate(questions[:6], 1)) or "<tr><td colspan=4>Run Evolution</td></tr>"
    cap_rows = "".join("<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>" %
        (esc(c.get("name", "")), esc(c.get("status", "")), c.get("health_score", 0), esc(c.get("next_action", "")[:72]))
        for c in caps[:8]) or "<tr><td colspan=4>No capabilities registered</td></tr>"
    backlog_rows = "".join("<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>" %
        (esc(i.get("name", "")), esc(i.get("status", "")), i.get("priority", 0), esc(i.get("next_action", "")[:72]))
        for i in backlog[:8]) or "<tr><td colspan=4>No backlog</td></tr>"
    banner = ("<div class=msg>%s</div>" % esc(msg)) if msg else ""

    return """<!doctype html><html><head><meta charset=utf-8><title>Pineapple Network OS</title><style>
*{box-sizing:border-box} body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#0f1430;color:#e8ecf8}
header{padding:20px 28px;background:#151b45;border-bottom:2px solid #d7a93c}
h1{margin:0;font-size:21px} .sub{color:#9aa6d4;font-size:13px;margin-top:3px}
.bar{padding:14px 28px;background:#141a40;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
button{background:#222a5e;color:#e8ecf8;border:0;border-radius:8px;padding:9px 14px;font-weight:bold;cursor:pointer}
button:hover{background:#d7a93c;color:#151b45}
.msg{color:#4fbf8b;font-size:13px;margin-left:8px}
.wrap{padding:22px 28px;display:grid;grid-template-columns:1fr 1fr;gap:18px;max-width:1100px}
.card{background:#1a2150;border:1px solid #2a3270;border-radius:12px;padding:16px}
.card h2{margin:0 0 10px;font-size:13px;color:#d7a93c;letter-spacing:1px;text-transform:uppercase}
table{width:100%%;border-collapse:collapse;font-size:13px} td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #2a3270}
.full{grid-column:1/3} .chip{display:inline-block;margin:3px;padding:3px 9px;border-radius:11px;font-size:12px}
.chip.on{background:#1d6b4a;color:#cdeede} .chip.off{background:#3a3050;color:#b9a9d0}
.k{color:#9aa6d4} footer{padding:14px 28px;color:#6b7299;font-size:12px}
</style></head><body>
<header><h1>&#127821; PINEAPPLE NETWORK OS</h1>
<div class=sub>Local-first &middot; 127.0.0.1 only &middot; %s</div></header>
<form class=bar method=post>
<button name=action value=brief>Run Decision Brief</button>
<button name=action value=intake>Run Context Intake</button>
<button name=action value=scan>Scan Screenshots</button>
<button name=action value=evolution>Run Evolution</button>
<button name=action value=recalibrate>Recalibrate Learning</button>
%s</form>
<div class=wrap>
<div class=card><h2>Users &amp; Roles</h2><table>
<tr><th>User</th><th>Role</th><th>Plan</th><th>Owner</th></tr>%s</table></div>
<div class=card><h2>System</h2><div style="font-size:13px;line-height:1.9">
<div><span class=k>Files indexed:</span> %d</div>
<div><span class=k>Brief items:</span> %d considered</div>
<div><span class=k>Learning log:</span> %d outcomes</div>
<div><span class=k>Brief generated:</span> %s</div></div></div>
<div class="card full"><h2>Today &mdash; Top Actions</h2><table>
<tr><th>#</th><th>Quant</th><th>Decision</th><th>Title</th></tr>%s</table></div>
<div class="card full"><h2>Evolution Layer</h2><div style="font-size:13px;line-height:1.8">
<div><span class=k>Roadmap stage:</span> %s</div>
<div><span class=k>End-state alignment:</span> %s/100</div>
<div><span class=k>Next highest leverage build:</span> %s</div>
</div></div>
<div class="card full"><h2>Adaptive Questions</h2><table>
<tr><th>#</th><th>Category</th><th>Priority</th><th>Question / reason</th></tr>%s</table></div>
<div class="card full"><h2>Capability Registry</h2><table>
<tr><th>Name</th><th>Status</th><th>Health</th><th>Next action</th></tr>%s</table></div>
<div class="card full"><h2>Capability Backlog</h2><table>
<tr><th>Name</th><th>Status</th><th>Priority</th><th>Next action</th></tr>%s</table></div>
<div class="card full"><h2>Intelligence Sources</h2>%s</div>
</div>
<footer>Read-only views + safe actions. Trading, sensors, per-user sign-in, remote (VPN) plug in here. No public exposure at v1. Shared feed (brief #2 Dash): <a href="http://127.0.0.1:8100/api/feed/opportunities">feed opportunities</a> — this dashboard is the historical OS page, not a second feed UI.</footer>
</body></html>""" % (gen, banner, user_rows, sc["indexed"], b.get("total_considered", 0),
                     st["total"], esc(b.get("generated", "not run")), action_rows,
                     esc(roadmap.get("current_stage", "unknown")), esc(evr.get("end_state_alignment_score", "?")),
                     esc(evr.get("next_highest_leverage_build", roadmap.get("highest_leverage_next_build", "Run Evolution"))),
                     q_rows, cap_rows, backlog_rows, plug_html)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200):
        body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self._send("not found", 404); return
        self._send(render_html())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8")
        action = ""
        for kv in data.split("&"):
            if kv.startswith("action="):
                action = kv.split("=", 1)[1]
        msg = "no action"
        if action == "brief":
            c, _ = api.run_decision(10); msg = "Decision brief regenerated (exit %d)" % c
        elif action == "intake":
            c, _ = api.run_intake(); msg = "Context intake run (exit %d)" % c
        elif action == "scan":
            c, _ = api.run_scan("Screenshots"); msg = "Screenshots scanned (exit %d)" % c
        elif action == "evolution":
            c, _ = api.run_evolution("dashboard"); msg = "Evolution run (exit %d)" % c
        elif action == "recalibrate":
            c, o = api.recalibrate(); msg = o.strip().splitlines()[-1] if o.strip() else "recalibrated"
        self._send(render_html(msg))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        html = render_html("selftest")
        (NET / "dashboard_preview.html").write_text(html, encoding="utf-8")
        print("Rendered %d bytes -> %s" % (len(html), NET / "dashboard_preview.html"))
    else:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        print("Pineapple dashboard -> http://127.0.0.1:%d  (Ctrl-C to stop)" % args.port)
        srv.serve_forever()
