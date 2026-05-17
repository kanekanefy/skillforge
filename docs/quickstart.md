# Quickstart

## 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/skillforge/skillforge/main/install.sh | bash
```

Or, from a clone:

```bash
git clone https://github.com/skillforge/skillforge
cd skillforge
./install.sh
```

The installer:

1. Installs the `skillforge` Python package via `pipx`
2. Registers Claude Code hooks in `~/.claude/settings.json` (use `--scope project` to scope to one repo)
3. Initializes `~/.skillforge/` state + seeds 3 demo skills

## 2. Sanity-check

```bash
sf doctor
sf evolver doctor
sf list
```

## 3. Use it

Open Claude Code in any directory. Ask something a demo skill matches:

> "format this SELECT * FROM users SQL query"

You should see a system reminder inserted before the main agent's reply:

```
skillforge: candidate skills matched against your prompt (BM25):
  • [sql-format] Format SQL queries with consistent indentation and capitalize keywords.
If any of these fit, follow the skill's pattern. Otherwise ignore — they're advisory only.
```

## 4. Watch it evolve

Use Claude Code for a few sessions. After a skill accumulates enough signal (≥3 selections + threshold-tripping metrics), skillforge auto-fires the evolver:

```bash
tail -f ~/.skillforge/logs/evolve.log
```

Or browse:

```bash
sf dash      # localhost:7777 — overview, skills, metrics, queue, records
sf metrics show
```

## 5. Configure (optional)

```bash
sf config set evolver.backend codex          # codex | claude-p | task | auto
sf config set evolver.async_in_stop_hook true
sf registry set https://raw.githubusercontent.com/your-fork/registry/main
```

See [evolver-backends.md](evolver-backends.md) for which backend to choose.

## 6. Install skills from the community

```bash
sf search "json"               # local
sf search --remote "json"      # registry
sf install-skill <skill-id>    # adds to ~/.skillforge/skills/
```

## 7. Publish your own

```bash
sf publish <skill-id>          # prints gh CLI steps
```

## Uninstall

```bash
sf uninstall --scope user      # remove hooks
pipx uninstall skillforge      # remove the binary
rm -rf ~/.skillforge           # remove state (DESTRUCTIVE — loses all evolution)
```

Your `~/.claude/settings.json` is restored from `~/.claude/settings.json.sf-backup` (created on first install).
