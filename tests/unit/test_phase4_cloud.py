"""Phase 4 tests — registry manifest, fetch, install, publish stub.

We use a `file://` URL pointing at a tmp_path directory as a mock
registry so tests are fully offline + deterministic.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "sf-home"
    monkeypatch.setenv("SKILLFORGE_HOME", str(h))
    import skillforge.config
    importlib.reload(skillforge.config)
    import skillforge.store.db
    importlib.reload(skillforge.store.db)
    return h


@pytest.fixture
def initialized(home: Path) -> Path:
    from skillforge.store import db
    db.init_schema()
    return home


@pytest.fixture
def mock_registry(tmp_path: Path) -> Path:
    """Build a tiny mock registry at tmp_path/registry/."""
    root = tmp_path / "registry"
    cat_dir = root / "skills" / "data" / "yaml-validate"
    cat_dir.mkdir(parents=True)
    skill_md = (
        "---\n"
        'name: "yaml-validate"\n'
        'description: "Validate YAML files for syntax + schema errors."\n'
        "tags: [yaml, validate]\n"
        "cssk:\n"
        "  skill_id: 01HMOCK000000000000001\n"
        "  version: 1\n"
        "---\n"
        "\n"
        "Run `yamllint` then `python -c 'import yaml; yaml.safe_load(...)'`.\n"
    )
    (cat_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return root


@pytest.fixture
def mock_registry_with_index(mock_registry: Path) -> Path:
    """mock_registry + an index.json built by skillforge's own builder."""
    from skillforge.cloud.manifest import build_index
    idx = build_index(mock_registry, registry_name="mock")
    (mock_registry / "index.json").write_text(
        json.dumps(idx, indent=2), encoding="utf-8")
    return mock_registry


# ── manifest ────────────────────────────────────────────────────────


def test_build_index_walks_skills_dir(mock_registry: Path) -> None:
    from skillforge.cloud.manifest import build_index

    idx = build_index(mock_registry, registry_name="test")
    assert idx["version"] == 1
    assert idx["registry_name"] == "test"
    assert len(idx["skills"]) == 1
    s = idx["skills"][0]
    assert s["name"] == "yaml-validate"
    assert s["category"] == "data"
    assert s["path"] == "skills/data/yaml-validate"
    assert s["checksum"].startswith("sha256:")
    assert "yaml" in s["tags"]


def test_load_index_round_trips(mock_registry_with_index: Path) -> None:
    from skillforge.cloud.manifest import load_index

    raw = (mock_registry_with_index / "index.json").read_text()
    entries = load_index(raw)
    assert len(entries) == 1
    assert entries[0].name == "yaml-validate"
    assert entries[0].tags == ["yaml", "validate"]


# ── fetch + install via file:// URL ─────────────────────────────────


def test_fetch_index_via_file_url(initialized: Path,
                                    mock_registry_with_index: Path) -> None:
    from skillforge import userconfig
    from skillforge.cloud import fetch_index

    userconfig.set_("registry.url", f"file://{mock_registry_with_index}")
    entries = fetch_index()
    assert len(entries) == 1
    assert entries[0].name == "yaml-validate"


def test_install_skill_writes_to_disk_and_sqlite(
    initialized: Path, mock_registry_with_index: Path
) -> None:
    from skillforge import config, userconfig
    from skillforge.cloud import fetch_index, install_skill
    from skillforge.store import db

    userconfig.set_("registry.url", f"file://{mock_registry_with_index}")
    entry = fetch_index()[0]
    path = install_skill(entry)

    assert path.exists()
    assert "yaml-validate" in path.read_text()

    # Sqlite mirrored
    rows = db.search("yaml", limit=5)
    assert any(r["name"] == "yaml-validate" for r in rows)


def test_install_skill_verifies_checksum(
    initialized: Path, mock_registry_with_index: Path
) -> None:
    from skillforge import userconfig
    from skillforge.cloud import fetch_index, install_skill

    userconfig.set_("registry.url", f"file://{mock_registry_with_index}")
    entry = fetch_index()[0]
    # Tamper the checksum
    entry.checksum = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="checksum mismatch"):
        install_skill(entry, verify_checksum=True)


def test_install_skill_skip_checksum_flag(
    initialized: Path, mock_registry_with_index: Path
) -> None:
    """--no-verify should let an intentionally bad checksum through."""
    from skillforge import userconfig
    from skillforge.cloud import fetch_index, install_skill

    userconfig.set_("registry.url", f"file://{mock_registry_with_index}")
    entry = fetch_index()[0]
    entry.checksum = "sha256:bad"
    path = install_skill(entry, verify_checksum=False)
    assert path.exists()


def test_fetch_index_falls_back_to_cache_on_failure(
    initialized: Path, mock_registry_with_index: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First fetch populates cache; switch to a dead URL; cached copy should
    still be served."""
    from skillforge import userconfig
    from skillforge.cloud import fetch_index

    userconfig.set_("registry.url", f"file://{mock_registry_with_index}")
    fetch_index()  # warms cache

    userconfig.set_("registry.url", f"file://{tmp_path}/does-not-exist")
    entries = fetch_index(use_cache_on_failure=True)
    assert len(entries) == 1
    assert entries[0].name == "yaml-validate"


# ── publish stub ────────────────────────────────────────────────────


def test_publish_instructions_mentions_gh_flow() -> None:
    from skillforge.cloud import github_sync
    out = github_sync.publish_instructions("my-skill")
    assert "gh auth status" in out
    assert "gh pr create" in out
    assert "my-skill" in out
