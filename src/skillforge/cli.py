"""skillforge CLI entry point.

Subcommands:
    sf install / uninstall  — hook registration in ~/.claude/settings.json
    sf doctor               — check setup health
    sf hook <event>         — invoked by Claude Code hooks (stdio JSON)
    sf seed                 — load demo skills (Phase 1 dev aid)
    sf db init              — create SQLite schema
    sf list                 — list installed skills

This is the surface that hooks and users both call. Keep it thin —
real logic lives in submodules.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click

from . import __version__, config


@click.group()
@click.version_option(__version__)
def main() -> None:
    """skillforge — self-evolving skill runtime for Claude Code."""


# ─────────────────────────────────────────────────────────────────────
# install / uninstall
# ─────────────────────────────────────────────────────────────────────


HOOK_MARKER = "__skillforge__"
"""Marker string we embed in hook command entries so we can dedup on reinstall
and find our own hooks on uninstall without false positives."""


def _settings_path(scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    if scope == "project":
        return Path.cwd() / ".claude" / "settings.json"
    raise click.BadParameter(f"unknown scope: {scope}")


def _load_settings(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text() or "{}")
    return {}


def _save_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


# Events we hook into. Names match Claude Code's hook event names exactly.
HOOK_EVENTS = [
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SessionStart",
]


def _sf_command() -> str:
    """Return the command string Claude Code should invoke for hooks.

    Preference order:
      1. Absolute path to the currently-running `sf` (handles editable installs
         in venvs that aren't on the user's shell PATH).
      2. Fallback to `sf` (works post-`pipx install skillforge` since pipx
         puts binaries on a stable PATH).

    We pick (1) when sys.argv[0] looks like a real path on disk — that's the
    case during `sf install`. This binds the hook to a specific binary, which
    is what we want during dev; production pipx installs will hit (2) via
    `sf install --bare-command`.
    """
    candidate = sys.argv[0]
    if candidate and Path(candidate).exists() and "/" in candidate:
        return str(Path(candidate).resolve())
    found = shutil.which("sf")
    return found or "sf"


def _hook_entry(event: str, sf_cmd: str) -> dict:
    """Build one Claude-Code-shaped hook entry pointing at our CLI.

    HOOK_MARKER lets us identify our own hooks on reinstall / uninstall.
    """
    return {
        "hooks": [
            {
                "type": "command",
                "command": f"{sf_cmd} hook {event.lower()} {HOOK_MARKER}",
            }
        ]
    }


def _add_hooks(settings: dict, sf_cmd: str) -> tuple[dict, list[str]]:
    """Insert skillforge hooks into a settings dict.

    Idempotent: if a hook already contains HOOK_MARKER for that event, skip.
    Returns (new_dict, list_of_events_added).
    """
    settings = json.loads(json.dumps(settings))  # deep copy
    hooks = settings.setdefault("hooks", {})
    added: list[str] = []
    for event in HOOK_EVENTS:
        existing = hooks.setdefault(event, [])
        already = any(
            HOOK_MARKER in (h.get("command", "") or "")
            for group in existing
            for h in group.get("hooks", [])
        )
        if not already:
            existing.append(_hook_entry(event, sf_cmd))
            added.append(event)
    return settings, added


def _remove_hooks(settings: dict) -> tuple[dict, list[str]]:
    """Strip out skillforge-owned hook entries by HOOK_MARKER."""
    settings = json.loads(json.dumps(settings))
    hooks = settings.get("hooks", {})
    removed: list[str] = []
    for event in HOOK_EVENTS:
        groups = hooks.get(event, [])
        new_groups = []
        for group in groups:
            kept = [h for h in group.get("hooks", []) if HOOK_MARKER not in (h.get("command", "") or "")]
            if kept:
                new_groups.append({**group, "hooks": kept})
        if len(new_groups) != len(groups):
            removed.append(event)
        if new_groups:
            hooks[event] = new_groups
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    return settings, removed


@main.command()
@click.option(
    "--scope",
    type=click.Choice(["user", "project"]),
    default="project",
    help="Where to register hooks. 'project' = ./.claude/settings.json, "
         "'user' = ~/.claude/settings.json (affects all sessions).",
)
@click.option(
    "--bare-command",
    is_flag=True,
    help="Write `sf` literally instead of the absolute path. Use this when "
         "you installed skillforge via pipx and want hooks to follow PATH "
         "rather than binding to today's binary location.",
)
def install(scope: str, bare_command: bool) -> None:
    """Register skillforge hooks into Claude Code's settings."""
    config.ensure_layout()

    path = _settings_path(scope)
    backup = path.with_suffix(path.suffix + ".sf-backup")

    sf_cmd = "sf" if bare_command else _sf_command()

    current = _load_settings(path)
    new, added = _add_hooks(current, sf_cmd)

    # Only back up if the on-disk file was pristine (no skillforge marker).
    # Otherwise the "backup" would just snapshot our previous install.
    raw = path.read_text() if path.exists() else ""
    if path.exists() and HOOK_MARKER not in raw and not backup.exists():
        backup.write_text(raw)
        click.echo(f"  backed up pristine settings: {backup}")

    _save_settings(path, new)

    if added:
        click.echo(f"✓ installed skillforge hooks at {path}")
        click.echo(f"  events:  {', '.join(added)}")
        click.echo(f"  command: {sf_cmd}")
    else:
        click.echo(f"= skillforge hooks already present at {path}")

    # First-install convenience: init the DB schema if missing.
    from .store import db as _db
    _db.init_schema()
    click.echo(f"✓ database ready at {config.db_path()}")


@main.command()
@click.option("--scope", type=click.Choice(["user", "project"]), default="project")
def uninstall(scope: str) -> None:
    """Remove skillforge hooks from Claude Code's settings."""
    path = _settings_path(scope)
    if not path.exists():
        click.echo(f"= no settings at {path}, nothing to do")
        return

    current = _load_settings(path)
    new, removed = _remove_hooks(current)
    _save_settings(path, new)

    if removed:
        click.echo(f"✓ removed skillforge hooks from {path}")
        click.echo(f"  events: {', '.join(removed)}")
    else:
        click.echo(f"= no skillforge hooks found in {path}")


# ─────────────────────────────────────────────────────────────────────
# doctor
# ─────────────────────────────────────────────────────────────────────


@main.command()
def doctor() -> None:
    """Comprehensive health check.

    Sections:
        1. Installation state (paths, version)
        2. Hook registration (user + project scope)
        3. Database integrity
        4. Evolver backend availability
        5. Registry connectivity (best-effort)
        6. Pending evolution work
    """
    import shutil as _shutil
    from .store import db as _db
    from .evolver.backends import available_backends, select_backend
    from .evolver import queue as _queue
    from . import userconfig

    click.echo(f"skillforge v{__version__}")
    click.echo()

    # ── 1. paths ─────────────────────────────────────────────────────
    click.echo("Paths")
    click.echo(f"  home:     {config.home()}")
    click.echo(f"  db:       {config.db_path()} {'(exists)' if config.db_path().exists() else '(MISSING — run `sf db init`)'}")
    click.echo(f"  skills:   {config.skills_dir()} ({len(list(config.skills_dir().glob('*'))) if config.skills_dir().exists() else 0} entries)")
    click.echo(f"  config:   {config.config_path()} {'(exists)' if config.config_path().exists() else '(using defaults)'}")
    click.echo()

    # ── 2. hooks ─────────────────────────────────────────────────────
    click.echo("Claude Code hooks")
    any_registered = False
    for scope in ("user", "project"):
        path = _settings_path(scope)
        if not path.exists():
            click.echo(f"  {scope:8}: {path} — no settings file")
            continue
        data = _load_settings(path)
        events = [e for e in HOOK_EVENTS
                  if any(HOOK_MARKER in (h.get("command", "") or "")
                         for group in data.get("hooks", {}).get(e, [])
                         for h in group.get("hooks", []))]
        if events:
            any_registered = True
            click.echo(f"  {scope:8}: ✓ {len(events)}/{len(HOOK_EVENTS)} hooks → {path}")
        else:
            click.echo(f"  {scope:8}: ✗ no skillforge hooks in {path}")
    if not any_registered:
        click.echo("  → run `sf install` to register hooks")
    click.echo()

    # ── 3. database ──────────────────────────────────────────────────
    click.echo("Database")
    if not config.db_path().exists():
        click.echo("  ✗ db missing")
    else:
        try:
            with _db.connect() as conn:
                n_skills = conn.execute("SELECT COUNT(*) AS n FROM skills WHERE is_active=1").fetchone()["n"]
                n_metrics = conn.execute("SELECT COUNT(*) AS n FROM skill_metrics").fetchone()["n"]
                n_lineage = conn.execute("SELECT COUNT(*) AS n FROM skill_lineage").fetchone()["n"]
            click.echo(f"  ✓ skills:  {n_skills} active")
            click.echo(f"  ✓ metrics: {n_metrics} rows")
            click.echo(f"  ✓ lineage: {n_lineage} edges")
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  ✗ db error: {exc}")
    click.echo()

    # ── 4. backends ──────────────────────────────────────────────────
    click.echo("Evolver backends")
    click.echo(f"  configured: {userconfig.get('evolver.backend', 'auto')}")
    for name, ok in available_backends():
        mark = "✓" if ok else "✗"
        path = _shutil.which(name) if name in ("codex", "claude-p") else None
        suffix = f"  ({path})" if path else ""
        click.echo(f"  {mark} {name}{suffix}")
    sel = select_backend()
    click.echo(f"  → active: {sel.name}")
    click.echo()

    # ── 5. registry ──────────────────────────────────────────────────
    click.echo("Registry")
    from .cloud import registry_url
    click.echo(f"  url:    {registry_url()}")
    cache = config.home() / "registry-cache" / "index.json"
    click.echo(f"  cache:  {'present' if cache.exists() else 'empty (no previous fetch)'}")
    click.echo()

    # ── 6. queue ─────────────────────────────────────────────────────
    click.echo("Evolution queue")
    try:
        n = _queue.count_pending()
        click.echo(f"  pending: {n}{' (run `sf evolve` to drain)' if n else ''}")
    except Exception as exc:  # noqa: BLE001
        click.echo(f"  ? queue inaccessible: {exc}")


# ─────────────────────────────────────────────────────────────────────
# hook dispatcher  (called by Claude Code)
# ─────────────────────────────────────────────────────────────────────


@main.command(name="hook")
@click.argument("event")
@click.argument("extra", nargs=-1)
def hook_cmd(event: str, extra: tuple[str, ...]) -> None:
    """Invoked by Claude Code hooks.

    Reads a JSON event from stdin; writes either nothing (silent allow)
    or a hookSpecificOutput JSON to stdout.
    """
    # Lazy import: hooks should start fast.
    payload_text = sys.stdin.read()
    try:
        payload = json.loads(payload_text) if payload_text.strip() else {}
    except json.JSONDecodeError:
        # Bad input — don't break Claude Code; just be silent.
        sys.exit(0)

    event_key = event.lower().replace("-", "_")

    if event_key == "userpromptsubmit":
        from .hooks.pre_prompt import handle
    elif event_key == "pretooluse":
        from .hooks.pre_tool import handle  # type: ignore[no-redef]
    elif event_key == "posttooluse":
        from .hooks.post_tool import handle  # type: ignore[no-redef]
    elif event_key == "stop":
        from .hooks.stop import handle  # type: ignore[no-redef]
    elif event_key == "sessionstart":
        from .hooks.session_start import handle  # type: ignore[no-redef]
    else:
        sys.exit(0)

    try:
        out = handle(payload)
    except Exception as exc:  # noqa: BLE001
        # Never let a hook crash break the user's session.
        # Log to stderr (goes to Claude Code's hook log) and exit clean.
        print(f"skillforge hook {event} error: {exc}", file=sys.stderr)
        sys.exit(0)

    if out:
        json.dump(out, sys.stdout, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────
# seed (dev aid)
# ─────────────────────────────────────────────────────────────────────


@main.command()
def seed() -> None:
    """Insert 3 dummy skills into the DB. For Phase 1 smoke testing only."""
    from .store import db as _db
    _db.init_schema()
    _db.seed_dummies()
    click.echo("✓ seeded 3 dummy skills")
    for row in _db.list_skills():
        click.echo(f"  - {row['skill_id']}: {row['name']} — {row['description']}")


@main.command(name="list")
def list_cmd() -> None:
    """List all installed skills."""
    from .store import db as _db
    rows = _db.list_skills()
    if not rows:
        click.echo("(no skills)")
        return
    for r in rows:
        click.echo(f"  {r['skill_id']}  {r['name']}  — {r['description']}")


# ─────────────────────────────────────────────────────────────────────
# metrics
# ─────────────────────────────────────────────────────────────────────


@main.group()
def metrics() -> None:
    """Skill quality metrics."""


@metrics.command(name="show")
def metrics_show() -> None:
    """Print per-skill counters and derived rates."""
    from .store import db as _db
    rows = _db.all_metrics()
    if not rows:
        click.echo("(no metrics recorded yet)")
        return
    # Compact tabular output
    headers = ["name", "select", "applied", "effective", "fallback",
               "comp/cont", "rates(a/e/f)"]
    click.echo("  ".join(f"{h:<13}" for h in headers))
    for r in rows:
        total = r["total_selections"]
        applied = r["applied"]
        eff = r["effective"]
        fb = r["fallback"]
        comp = r["completed_tasks"]
        cont = r["containing_tasks"]
        ar = applied / total if total else 0
        er = eff / applied if applied else 0
        fr = fb / total if total else 0
        cells = [
            r["name"][:13],
            str(total),
            str(applied),
            str(eff),
            str(fb),
            f"{comp}/{cont}",
            f"{ar:.2f}/{er:.2f}/{fr:.2f}",
        ]
        click.echo("  ".join(f"{c:<13}" for c in cells))


# ─────────────────────────────────────────────────────────────────────
# db (admin)
# ─────────────────────────────────────────────────────────────────────


@main.group()
def db() -> None:
    """Database admin."""


@db.command(name="init")
def db_init() -> None:
    """Create SQLite schema (idempotent)."""
    from .store import db as _db
    _db.init_schema()
    click.echo(f"✓ schema ready at {config.db_path()}")


# ─────────────────────────────────────────────────────────────────────
# config
# ─────────────────────────────────────────────────────────────────────


@main.group(name="config")
def config_cmd() -> None:
    """User configuration (~/.skillforge/config.toml)."""


@config_cmd.command(name="get")
@click.argument("key")
def config_get(key: str) -> None:
    from . import userconfig
    val = userconfig.get(key)
    click.echo(val if val is not None else "(unset)")


@config_cmd.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    from . import userconfig
    # Coerce simple booleans / ints so users don't have to quote everything.
    coerced: object = value
    if value.lower() in ("true", "false"):
        coerced = value.lower() == "true"
    else:
        try:
            coerced = int(value)
        except ValueError:
            pass
    userconfig.set_(key, coerced)
    click.echo(f"✓ {key} = {coerced!r}")


# ─────────────────────────────────────────────────────────────────────
# evolve
# ─────────────────────────────────────────────────────────────────────


@main.group(invoke_without_command=True)
@click.option("--list", "list_only", is_flag=True, help="Just list pending items (JSON to stdout).")
@click.option("--render", "render_id", help="Print the evolution prompt for one queue_id and exit.")
@click.option("--apply", "apply_id", help="Apply parsed result to a queue_id; --content gives the file.")
@click.option("--content", "content_path", help="Path to a file with the LLM output to parse.")
@click.option("--max", "max_items", type=int, help="Cap how many items to process this run.")
@click.pass_context
def evolve(ctx: click.Context, list_only: bool, render_id: str | None,
           apply_id: str | None, content_path: str | None,
           max_items: int | None) -> None:
    """Drain the evolution queue (or do single-item ops for sf-evolve skill)."""
    if ctx.invoked_subcommand is not None:
        return

    from .evolver import queue as q, worker, parser as _parser
    from .evolver.apply import apply_fix, apply_derived, apply_captured
    from .analyzer import render_evolution_prompt as _render
    import json as _json

    if list_only:
        click.echo(_json.dumps(q.list_pending(), default=str, indent=2))
        return

    if render_id:
        for item in q.list_pending():
            if item["queue_id"] == render_id:
                c = item["candidate"]
                click.echo(_render(
                    kind=item["kind"],
                    skill_id=c.get("skill_id"),
                    metrics=c.get("metrics", {}),
                    trigger_task_id=c.get("trigger_task_id"),
                ))
                return
        raise click.ClickException(f"queue_id {render_id} not found")

    if apply_id:
        if not content_path:
            raise click.ClickException("--apply requires --content <path>")
        text = Path(content_path).read_text(encoding="utf-8")
        decision = _parser.parse_evolution_output(text)

        target = None
        for item in q.list_pending():
            if item["queue_id"] == apply_id:
                target = item
                break
        if target is None:
            raise click.ClickException(f"queue_id {apply_id} not found in pending")

        if not decision.confirmed:
            q.mark_done(apply_id, error=f"rejected: {decision.reject_reason}")
            click.echo(f"= rejected: {decision.reject_reason}")
            return
        if not decision.ok:
            q.mark_done(apply_id, error=f"parse: {decision.failure_reason}")
            click.echo(f"✗ malformed output: {decision.failure_reason}")
            return

        kind = target["kind"]
        sid = target["candidate"].get("skill_id")
        try:
            if kind == "fix":
                new_id = apply_fix(target_skill_id=sid or "", decision=decision)
            elif kind == "derived":
                new_id = apply_derived(parent_skill_id=sid or "", decision=decision)
            else:
                new_id = apply_captured(decision=decision)
        except Exception as exc:  # noqa: BLE001
            q.mark_done(apply_id, error=f"apply: {exc}")
            raise click.ClickException(f"apply failed: {exc}") from exc
        q.mark_done(apply_id)
        click.echo(f"✓ applied {kind} → new_id={new_id}")
        return

    # No flag → drain the queue ourselves (uses configured backend).
    n = worker.drain(max_items=max_items)
    click.echo(f"✓ processed {n} item(s)")


# ─────────────────────────────────────────────────────────────────────
# evolver doctor
# ─────────────────────────────────────────────────────────────────────


@main.group()
def evolver() -> None:
    """Evolver backend admin."""


@evolver.command(name="doctor")
def evolver_doctor() -> None:
    from .evolver.backends import available_backends, select_backend
    from . import userconfig

    click.echo("skillforge evolver doctor")
    click.echo(f"  configured backend: {userconfig.get('evolver.backend', 'auto')}")
    click.echo(f"  async in Stop hook: {userconfig.get('evolver.async_in_stop_hook', True)}")
    click.echo("  backends:")
    for name, ok in available_backends():
        mark = "✓" if ok else "✗"
        click.echo(f"    {mark} {name}")
    selected = select_backend()
    click.echo(f"  → would select: {selected.name}")


# ─────────────────────────────────────────────────────────────────────
# search / install / publish / registry  (Phase 4)
# ─────────────────────────────────────────────────────────────────────


@main.command()
@click.argument("query")
@click.option("--remote", is_flag=True, help="Search the registry instead of local.")
@click.option("--limit", type=int, default=10)
def search(query: str, remote: bool, limit: int) -> None:
    """Search local skills (FTS5 BM25) or the active registry."""
    if remote:
        from .cloud import fetch_index, registry_url
        try:
            entries = fetch_index()
        except Exception as exc:
            raise click.ClickException(f"fetch failed: {exc}")
        click.echo(f"# registry: {registry_url()}")
        q = query.lower()
        hits = [e for e in entries
                if q in e.name.lower() or q in e.description.lower()
                or any(q in t.lower() for t in (e.tags or []))]
        for e in hits[:limit]:
            click.echo(f"  {e.skill_id}  {e.name}  [{e.category}]  — {e.description}")
        if not hits:
            click.echo("(no remote matches)")
    else:
        from .store import db as _db
        rows = _db.search(query, limit=limit)
        if not rows:
            click.echo("(no local matches)")
        for r in rows:
            click.echo(f"  {r['skill_id']}  {r['name']}  — {r['description']}")


@main.command(name="install-skill")
@click.argument("skill_id")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.option("--no-verify", is_flag=True, help="Skip checksum verification.")
def install_skill_cmd(skill_id: str, yes: bool, no_verify: bool) -> None:
    """Install a skill from the active registry by skill_id (or name)."""
    from .cloud import fetch_index, install_skill

    try:
        entries = fetch_index()
    except Exception as exc:
        raise click.ClickException(f"fetch failed: {exc}")

    match = next((e for e in entries
                  if e.skill_id == skill_id or e.name == skill_id), None)
    if not match:
        raise click.ClickException(f"not found in registry: {skill_id}")

    click.echo(f"Skill:       {match.name} ({match.skill_id})")
    click.echo(f"Category:    {match.category}")
    click.echo(f"Description: {match.description}")
    click.echo(f"Maintainer:  {match.maintainer or '(unspecified)'}")
    click.echo(f"License:     {match.license or '(unspecified)'}")
    click.echo(f"Checksum:    {match.checksum}")
    if not yes and not click.confirm("Install?", default=True):
        click.echo("aborted")
        return

    path = install_skill(match, verify_checksum=not no_verify)
    click.echo(f"✓ installed → {path}")


@main.command()
@click.argument("skill_id")
def publish(skill_id: str) -> None:
    """Print step-by-step instructions for PRing a skill to the registry."""
    from .cloud.github_sync import publish_instructions
    click.echo(publish_instructions(skill_id))


@main.group()
def registry() -> None:
    """Manage which registry sf search/install pulls from."""


@registry.command(name="get")
def registry_get() -> None:
    from .cloud import registry_url
    click.echo(registry_url())


@registry.command(name="set")
@click.argument("url")
def registry_set(url: str) -> None:
    from . import userconfig
    userconfig.set_("registry.url", url)
    click.echo(f"✓ registry.url = {url}")


@registry.command(name="build-index")
@click.argument("registry_root", type=click.Path(exists=True, file_okay=False))
@click.option("--name", default="local", help="Registry display name in index.")
def registry_build_index(registry_root: str, name: str) -> None:
    """For maintainers of a registry fork: regenerate index.json."""
    import json as _json
    from .cloud.manifest import build_index
    idx = build_index(Path(registry_root), registry_name=name)
    out_path = Path(registry_root) / "index.json"
    out_path.write_text(_json.dumps(idx, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    click.echo(f"✓ wrote {out_path} ({len(idx['skills'])} skills)")


# ─────────────────────────────────────────────────────────────────────
# dashboard / bridge   (Phase 5)
# ─────────────────────────────────────────────────────────────────────


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", type=int, default=7777)
@click.option("--no-open", is_flag=True, help="Don't auto-open browser.")
def dash(host: str, port: int, no_open: bool) -> None:
    """Open the local dashboard (skills, metrics, queue, records)."""
    from .dashboard import run_dashboard
    run_dashboard(host=host, port=port, open_browser=not no_open)


@main.group()
def bridge() -> None:
    """Cross-host MCP bridge (Codex / OpenClaw / nanobot consumers)."""


@bridge.command(name="serve")
def bridge_serve() -> None:
    """Run an MCP server on stdio. Configure your host agent's MCP file
    to point at `sf bridge serve` to expose skillforge's search +
    metrics + queue tools."""
    from .bridge.mcp_server import serve_stdio
    serve_stdio()


# ─────────────────────────────────────────────────────────────────────
# _worker — invoked by Stop hook's detached spawn
# ─────────────────────────────────────────────────────────────────────


@main.command(name="_worker", hidden=True)
@click.option("--task-id", help="Task that triggered this drain (informational only).")
def worker_entry(task_id: str | None) -> None:
    """Drain the queue. Intended for detached background execution."""
    from .evolver import worker as _worker
    n = _worker.drain()
    click.echo(f"processed {n} item(s)" + (f" triggered by task {task_id}" if task_id else ""))
