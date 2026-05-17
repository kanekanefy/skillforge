#!/usr/bin/env bash
# skillforge installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<you>/skillforge/main/install.sh | bash
#
# What it does:
#   1. Verifies Python ≥3.11 and pipx are available (installs pipx via pip if not)
#   2. `pipx install skillforge` (or `pipx install -e .` if run from a checkout)
#   3. Runs `sf install --scope user --bare-command` to register hooks
#   4. Initializes ~/.skillforge/ state + seeds 3 demo skills
#   5. Prints a one-liner showing how to verify
#
# This script is *idempotent* — re-running upgrades the install in place.

set -euo pipefail

SKILLFORGE_REPO="${SKILLFORGE_REPO:-kanekanefy/skillforge}"   # github org/repo
SKILLFORGE_BRANCH="${SKILLFORGE_BRANCH:-main}"

# ── coloring ────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_OK="\033[32m"; C_WARN="\033[33m"; C_ERR="\033[31m"
  C_DIM="\033[2m"; C_RESET="\033[0m"
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_RESET=""
fi
say()  { printf "${C_DIM}▸${C_RESET} %s\n" "$*"; }
ok()   { printf "${C_OK}✓${C_RESET} %s\n" "$*"; }
warn() { printf "${C_WARN}⚠${C_RESET} %s\n" "$*"; }
die()  { printf "${C_ERR}✗${C_RESET} %s\n" "$*" >&2; exit 1; }

# ── prerequisites ───────────────────────────────────────────────────
say "checking python"
PYTHON="$(command -v python3 || true)"
[[ -z "$PYTHON" ]] && die "python3 not found. Install Python 3.11+ first."

PY_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 11) )); then
  die "Python 3.11+ required (found $PY_MAJOR.$PY_MINOR)."
fi
ok "python $PY_MAJOR.$PY_MINOR"

say "checking pipx"
if ! command -v pipx >/dev/null 2>&1; then
  warn "pipx not installed; installing via pip --user"
  "$PYTHON" -m pip install --user --quiet --upgrade pipx
  "$PYTHON" -m pipx ensurepath
  # pipx puts binaries in ~/.local/bin (Linux) or ~/.local/bin on macOS
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "pipx $(pipx --version 2>/dev/null || echo '(version unknown)')"

# ── install skillforge ──────────────────────────────────────────────
say "installing skillforge"
if [[ -f "./pyproject.toml" && -d "./src/skillforge" ]]; then
  # Running from a checkout — install editable.
  pipx install --force --editable .
  ok "installed (editable) from $(pwd)"
else
  # Install from git so users don't need to clone manually.
  pipx install --force "git+https://github.com/${SKILLFORGE_REPO}@${SKILLFORGE_BRANCH}"
  ok "installed from github.com/${SKILLFORGE_REPO}@${SKILLFORGE_BRANCH}"
fi

# ── register hooks (user scope by default) ──────────────────────────
SCOPE="${SF_INSTALL_SCOPE:-user}"
say "registering Claude Code hooks (scope: $SCOPE)"
if [[ "$SCOPE" == "user" ]]; then
  sf install --scope user --bare-command
else
  sf install --scope project --bare-command
fi

# ── seed demo skills ────────────────────────────────────────────────
say "seeding demo skills"
sf db init
sf seed >/dev/null
ok "demo skills loaded (run 'sf list' to see them)"

# ── post-install summary ────────────────────────────────────────────
echo
ok "skillforge installation complete"
echo
echo "  ${C_DIM}# verify:${C_RESET}"
echo "  sf doctor"
echo "  sf evolver doctor    ${C_DIM}# shows which backend will be used${C_RESET}"
echo
echo "  ${C_DIM}# open the dashboard:${C_RESET}"
echo "  sf dash"
echo
echo "  ${C_DIM}# uninstall:${C_RESET}"
echo "  sf uninstall --scope $SCOPE && pipx uninstall skillforge"
echo
