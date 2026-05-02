"""Tests for paths.project-relative layout."""
import paths


def test_config_path_under_config_dir():
    p = paths.config_path('6600WB_eq_constants.json')
    assert p.name == '6600WB_eq_constants.json'
    assert p.parent.name == paths.REL_CONFIG
    assert p.parent.parent == paths.PROJECT_ROOT


def test_recipes_root_under_project():
    r = paths.recipes_root()
    assert r.name == paths.REL_RECIPES
    assert r.parent == paths.PROJECT_ROOT


def test_project_root_contains_entrypoint():
    assert (paths.PROJECT_ROOT / 'main.py').is_file()
