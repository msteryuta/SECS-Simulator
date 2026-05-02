"""Tests for GUI recipe folder listing (S7F17 dropdown data source)."""
from pathlib import Path

from gui.host_panel import recipe_ppids_in_dir


def test_missing_recipes_dir_returns_empty(tmp_path: Path):
    assert recipe_ppids_in_dir(tmp_path / 'recipes') == []


def test_returns_sorted_directory_names_only(tmp_path: Path):
    recipes = tmp_path / 'recipes'
    (recipes / 'Zebra').mkdir(parents=True)
    (recipes / 'Apple').mkdir(parents=True)
    (recipes / 'not_a_dir.txt').write_text('x', encoding='utf-8')
    assert recipe_ppids_in_dir(recipes) == ['Apple', 'Zebra']
