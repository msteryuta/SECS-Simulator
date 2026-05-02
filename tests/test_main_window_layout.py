"""Layout constants aligned with primary UI / Xvfb resolution."""
from gui import main_window as mw


def test_target_framebuffer_resolution():
    assert mw.UI_WIDTH == 1024
    assert mw.UI_HEIGHT == 768


def test_side_panels_fit_within_width():
    assert mw._LEFT_W + mw._RIGHT_W < mw.UI_WIDTH
