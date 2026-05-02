"""
Project data locations: anchored at SECS_Simulator root (this file's directory),
joined with logical segments REL_CONFIG / REL_RECIPES — independent of process CWD.

專案內路徑：以本檔所在目錄為根，用相對區段（config/、recipes/）組合，不依賴啟動時工作目錄。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

REL_CONFIG = 'config'
REL_RECIPES = 'recipes'


def config_path(*parts: str) -> Path:
    """PROJECT_ROOT / 'config' / *parts"""
    return PROJECT_ROOT.joinpath(REL_CONFIG, *parts)


def recipes_root() -> Path:
    """PROJECT_ROOT / 'recipes'"""
    return PROJECT_ROOT / REL_RECIPES
