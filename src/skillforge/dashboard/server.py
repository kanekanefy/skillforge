"""Stdlib-only HTTP dashboard.

Routes:
    /           overview (skills count, queue depth, recent activity)
    /skills     full skill list with metrics, sortable client-side
    /skill/<id> single skill view (body, lineage, history)
    /metrics    pure metrics table
    /queue      evolution queue (pending + recent)
    /records    task records browser
    /static/... CSS only (single embedded sheet, no JS frameworks)

We keep everything synchronous; the dashboard is local + single-user,
no need for ASGI/uvicorn.
"""

from __future__ import annotations

import html
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .. import config
from ..evolver import queue as evolver_queue
from ..store import db


# ── HTML helpers ────────────────────────────────────────────────────


_STYLE = """
* { box-sizing: border-box; }
body { font: 14px -apple-system, "SF Pro Text", system-ui, sans-serif;
       margin: 0; background: #f6f7f9; color: #1d2125; }
header { background: #1d2125; color: #f1f4f8; padding: 12px 24px;
         display: flex; gap: 24px; align-items: center; }
header a { color: #ccd0d6; text-decoration: none; font-weight: 500; }
header a.active, header a:hover { color: #fff; }
header h1 { font-size: 15px; margin: 0; font-weight: 600; }
main { padding: 24px; max-width: 1100px; margin: 0 auto; }
h2 { font-size: 18px; margin: 0 0 12px; }
table { width: 100%; background: #fff; border-collapse: collapse;
        border-radius: 6px; overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
th, td { text-align: left; padding: 8px 14px; border-bottom: 1px solid #ebeef2; }
th { background: #fafbfc; font-weight: 600; font-size: 12px;
     text-transform: uppercase; color: #6b7280; letter-spacing: 0.04em; }
tr:last-child td { border-bottom: none; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
        font-size: 11px; font-weight: 600; }
.pill-orig { background: #e6f0ff; color: #2557d6; }
.pill-fix  { background: #fff1e6; color: #b15a00; }
.pill-derived { background: #ecfdf4; color: #167b3a; }
.pill-captured { background: #f3e7ff; color: #6f1ec7; }
.empty { color: #6b7280; padding: 16px; }
.stat { display: inline-block; padding: 16px 24px; background: #fff;
        border-radius: 6px; margin-right: 12px; min-width: 140px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.stat .n { font-size: 28px; font-weight: 700; color: #1d2125; }
.stat .label { font-size: 11px; color: #6b7280;
               text-transform: uppercase; letter-spacing: 0.06em; }
.code { font-family: "SF Mono", Menlo, monospace; font-size: 12px;
        background: #f0f2f5; padding: 1px 5px; border-radius: 3px; }
pre { background: #fafbfc; padding: 14px 18px; border-radius: 6px;
      overflow-x: auto; font-size: 12px; }
"""


def _render(title: str, body: str, active: str = "") -> bytes:
    def link(name: str, href: str) -> str:
        cls = "active" if active == name else ""
        return f'<a class="{cls}" href="{href}">{name}</a>'
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} — skillforge</title>
<style>{_STYLE}</style>
</head>
<body>
<header>
  <h1>skillforge</h1>
  {link("overview", "/")}
  {link("skills", "/skills")}
  {link("metrics", "/metrics")}
  {link("queue", "/queue")}
  {link("records", "/records")}
</header>
<main>
{body}
</main>
</body>
</html>"""
    return page.encode("utf-8")


# ── page renderers ──────────────────────────────────────────────────


def _overview() -> bytes:
    with db.connect() as conn:
        n_skills = conn.execute("SELECT COUNT(*) AS n FROM skills WHERE is_active=1").fetchone()["n"]
        n_evolved = conn.execute("SELECT COUNT(*) AS n FROM skills WHERE origin != 'original'").fetchone()["n"]
    n_queue = evolver_queue.count_pending()
    n_records = len(list(config.records_dir().glob("*"))) if config.records_dir().exists() else 0

    body = f"""<h2>Overview</h2>
<div>
  <div class="stat"><div class="n">{n_skills}</div><div class="label">active skills</div></div>
  <div class="stat"><div class="n">{n_evolved}</div><div class="label">evolved</div></div>
  <div class="stat"><div class="n">{n_queue}</div><div class="label">queued</div></div>
  <div class="stat"><div class="n">{n_records}</div><div class="label">task records</div></div>
</div>
"""
    return _render("Overview", body, active="overview")


def _skills_page() -> bytes:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.*, m.total_selections, m.applied, m.effective, m.fallback "
            "FROM skills s LEFT JOIN skill_metrics m USING(skill_id) "
            "WHERE s.is_active = 1 ORDER BY s.name"
        ).fetchall()
    if not rows:
        body = "<h2>Skills</h2><p class='empty'>No skills installed. Try <span class='code'>sf seed</span>.</p>"
        return _render("Skills", body, active="skills")

    trs = []
    for r in rows:
        sel = r["total_selections"] or 0
        eff = r["effective"] or 0
        fr = (r["fallback"] or 0) / sel if sel else 0
        er = eff / (r["applied"] or 1) if r["applied"] else 0
        origin_pill = f'<span class="pill pill-{r["origin"]}">{r["origin"]}</span>'
        trs.append(f"""<tr>
  <td><a href="/skill/{html.escape(r["skill_id"])}">{html.escape(r["name"])}</a></td>
  <td>{html.escape(r["description"][:80])}</td>
  <td>{origin_pill}</td>
  <td>v{r["version"]}</td>
  <td>g{r["generation"]}</td>
  <td>{sel}</td>
  <td>{er:.0%}</td>
  <td>{fr:.0%}</td>
</tr>""")
    body = f"""<h2>Skills</h2>
<table><thead><tr>
  <th>Name</th><th>Description</th><th>Origin</th><th>Version</th>
  <th>Gen</th><th>Select</th><th>Effective</th><th>Fallback</th>
</tr></thead><tbody>{"".join(trs)}</tbody></table>"""
    return _render("Skills", body, active="skills")


def _skill_detail(skill_id: str) -> bytes:
    with db.connect() as conn:
        skill = conn.execute(
            "SELECT * FROM skills WHERE skill_id = ?", (skill_id,)
        ).fetchone()
        if not skill:
            return _render("Not found", "<h2>Skill not found</h2>")
        lineage = conn.execute(
            "SELECT * FROM skill_lineage WHERE child_id = ? OR parent_id = ?",
            (skill_id, skill_id)
        ).fetchall()
        metrics = conn.execute(
            "SELECT * FROM skill_metrics WHERE skill_id = ?", (skill_id,)
        ).fetchone()

    metrics_html = "<p class='empty'>No metrics yet</p>"
    if metrics:
        metrics_html = (
            "<table><tbody>"
            + f"<tr><th>Selections</th><td>{metrics['total_selections']}</td></tr>"
            + f"<tr><th>Applied</th><td>{metrics['applied']}</td></tr>"
            + f"<tr><th>Effective</th><td>{metrics['effective']}</td></tr>"
            + f"<tr><th>Fallback</th><td>{metrics['fallback']}</td></tr>"
            + f"<tr><th>Last used</th><td>{metrics['last_used_at'] or 'never'}</td></tr>"
            + "</tbody></table>"
        )

    lineage_html = "<p class='empty'>No lineage</p>"
    if lineage:
        lineage_rows = "".join(
            f"<tr><td>{html.escape(l['parent_id'])}</td><td>→</td>"
            f"<td>{html.escape(l['child_id'])}</td>"
            f"<td><span class='pill pill-{l['kind']}'>{l['kind']}</span></td>"
            f"<td>{l['created_at']}</td></tr>"
            for l in lineage
        )
        lineage_html = (
            "<table><thead><tr><th>Parent</th><th></th><th>Child</th>"
            "<th>Kind</th><th>When</th></tr></thead><tbody>"
            + lineage_rows + "</tbody></table>"
        )

    body = f"""<h2>{html.escape(skill['name'])}</h2>
<p><span class="pill pill-{skill['origin']}">{skill['origin']}</span>
   v{skill['version']} gen{skill['generation']}
   &middot; <span class="code">{html.escape(skill['skill_id'])}</span></p>
<p>{html.escape(skill['description'])}</p>

<h2>Body</h2>
<pre>{html.escape(skill['body'] or '(empty)')}</pre>

<h2>Metrics</h2>
{metrics_html}

<h2>Lineage</h2>
{lineage_html}
"""
    return _render(skill['name'], body, active="skills")


def _metrics_page() -> bytes:
    rows = db.all_metrics()
    if not rows:
        body = "<h2>Metrics</h2><p class='empty'>No usage recorded yet.</p>"
        return _render("Metrics", body, active="metrics")
    trs = []
    for r in rows:
        sel = r["total_selections"] or 0
        applied = r["applied"] or 0
        eff = r["effective"] or 0
        fb = r["fallback"] or 0
        ar = applied / sel if sel else 0
        er = eff / applied if applied else 0
        fr = fb / sel if sel else 0
        trs.append(f"""<tr>
  <td>{html.escape(r["name"])}</td>
  <td>{sel}</td><td>{applied}</td><td>{eff}</td><td>{fb}</td>
  <td>{ar:.0%}</td><td>{er:.0%}</td><td>{fr:.0%}</td>
  <td>{r["last_used_at"] or "never"}</td>
</tr>""")
    body = f"""<h2>Metrics</h2>
<table><thead><tr>
  <th>Skill</th><th>Sel</th><th>App</th><th>Eff</th><th>FB</th>
  <th>app/sel</th><th>eff/app</th><th>fb/sel</th><th>Last used</th>
</tr></thead><tbody>{"".join(trs)}</tbody></table>"""
    return _render("Metrics", body, active="metrics")


def _queue_page() -> bytes:
    pending = evolver_queue.list_pending()
    with db.connect() as conn:
        recent = conn.execute(
            "SELECT * FROM evolve_queue WHERE status != 'pending' "
            "ORDER BY finished_at DESC LIMIT 25"
        ).fetchall()

    def render_rows(items: list, status_label: str) -> str:
        if not items:
            return f"<p class='empty'>No {status_label} items.</p>"
        rows = []
        for it in items:
            if isinstance(it, dict):
                kind = it.get("kind", "")
                sid = it.get("skill_id") or "—"
                qid = it.get("queue_id")
                when = it.get("enqueued_at", "")
                extra = ""
            else:
                kind = it["kind"]
                sid = it["skill_id"] or "—"
                qid = it["queue_id"]
                when = it["finished_at"] or it["enqueued_at"]
                extra = f" <span class='code'>{html.escape(it['status'])}</span>"
            rows.append(
                f"<tr><td><span class='code'>{html.escape(qid)}</span></td>"
                f"<td><span class='pill pill-{kind}'>{kind}</span></td>"
                f"<td>{html.escape(sid)}</td>"
                f"<td>{html.escape(when)}{extra}</td></tr>"
            )
        return ("<table><thead><tr><th>queue_id</th><th>kind</th>"
                "<th>skill</th><th>when</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table>")

    body = (
        "<h2>Pending</h2>" + render_rows(pending, "pending")
        + "<h2 style='margin-top:32px'>Recent</h2>" + render_rows(list(recent), "recent")
    )
    return _render("Queue", body, active="queue")


def _records_page() -> bytes:
    rdir = config.records_dir()
    if not rdir.exists():
        return _render("Records", "<h2>Records</h2><p class='empty'>No records yet.</p>",
                       active="records")
    entries = sorted(rdir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
    if not entries:
        return _render("Records", "<h2>Records</h2><p class='empty'>No records yet.</p>",
                       active="records")
    trs = []
    for d in entries:
        summary = d / "summary.json"
        active_skills = "(none)"
        completed = "?"
        if summary.exists():
            try:
                data = json.loads(summary.read_text())
                active_skills = ", ".join(data.get("active_skills", [])) or "(none)"
                completed = "yes" if data.get("completed") else "no"
            except json.JSONDecodeError:
                pass
        trs.append(f"<tr><td><span class='code'>{html.escape(d.name)}</span></td>"
                   f"<td>{html.escape(active_skills)}</td>"
                   f"<td>{completed}</td></tr>")
    body = (
        "<h2>Task records</h2>"
        "<table><thead><tr><th>task_id</th><th>active skills</th>"
        "<th>completed</th></tr></thead><tbody>"
        + "".join(trs) + "</tbody></table>"
    )
    return _render("Records", body, active="records")


# ── HTTP handler ────────────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):
    server_version = "skillforge-dash/0.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Suppress noisy default log unless you want it.
        return

    def do_GET(self) -> None:  # noqa: N802 (stdlib API)
        path = urlparse(self.path).path
        try:
            payload, content_type = self._route(path)
        except Exception as exc:  # noqa: BLE001
            payload = f"<h1>500 internal error</h1><pre>{html.escape(str(exc))}</pre>".encode()
            content_type = "text/html; charset=utf-8"
            self.send_response(500)
        else:
            self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _route(self, path: str) -> tuple[bytes, str]:
        if path == "/" or path == "/index.html":
            return _overview(), "text/html; charset=utf-8"
        if path == "/skills":
            return _skills_page(), "text/html; charset=utf-8"
        if path.startswith("/skill/"):
            return _skill_detail(path[len("/skill/"):]), "text/html; charset=utf-8"
        if path == "/metrics":
            return _metrics_page(), "text/html; charset=utf-8"
        if path == "/queue":
            return _queue_page(), "text/html; charset=utf-8"
        if path == "/records":
            return _records_page(), "text/html; charset=utf-8"
        return b"<h1>404</h1>", "text/html; charset=utf-8"


def run(host: str = "127.0.0.1", port: int = 7777, open_browser: bool = True) -> None:
    """Start the dashboard. Blocks until Ctrl-C."""
    httpd = ThreadingHTTPServer((host, port), _Handler)
    actual_host, actual_port = httpd.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/"
    print(f"skillforge dashboard: {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def get_free_port(start: int = 7777) -> int:
    """Probe for the lowest free port at-or-above `start`. Used by tests."""
    for p in range(start, start + 50):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", p))
                return p
        except OSError:
            continue
    raise RuntimeError("no free port in scan range")
