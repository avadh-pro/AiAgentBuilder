"""Smoke tests — package imports and basic structural invariants."""

from __future__ import annotations


def test_package_imports():
    import carousel_agent

    assert carousel_agent.__version__ == "0.1.0"


def test_paths_module_resolves():
    from carousel_agent import paths

    assert paths.project_root().is_absolute()
    assert paths.db_path().name == "carousel.db"
    assert paths.packaged_default_config().exists()
