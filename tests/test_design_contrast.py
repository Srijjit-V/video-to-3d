"""The colour pairs the viewer actually uses must meet WCAG contrast (4.5:1 text, 3:1 UI parts)."""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[1] / "viewer" / "css" / "styles.css").read_text()
_DARK, _LIGHT = CSS.split(':root[data-theme="light"]', 1)
_THEMES = {
    "dark": dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", _DARK)),
}
_THEMES["light"] = {**_THEMES["dark"], **dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", _LIGHT.split("}", 1)[0]))}
TOKENS = _THEMES["dark"]  # DESIGN.md documents the dark tokens first


def luminance(hex_):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b, theme="dark"):
    t = _THEMES[theme]
    la, lb = sorted((luminance(t[a]), luminance(t[b])), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_PAIRS = [(fg, bg) for fg in ("text", "text-2", "text-3", "mint", "hot", "amber") for bg in ("bg", "card", "input")]
TEXT_PAIRS += [("mint-ink", "mint")]  # primary button label


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_colour_pairs_reach_4_5_to_1(fg, bg, theme):
    assert contrast(fg, bg, theme) >= 4.5, f"{theme}: {fg} on {bg} is {contrast(fg, bg, theme):.2f}:1"


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("fg,bg", [("mint", "bg"), ("mint", "card")])
def test_focus_ring_reaches_3_to_1(fg, bg, theme):
    assert contrast(fg, bg, theme) >= 3.0


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("name", ["green", "red"])
def test_confidence_and_step_colours_reach_3_to_1_on_cards(name, theme):
    assert contrast(name, "card", theme) >= 3.0, f"{theme}: {name} on card"


def test_no_raw_colours_outside_the_token_blocks():
    """Every colour in a rule must come from a token, so a theme can change all of them (the 3D label pill is the one fixed exception)."""
    body = _DARK.split("--scene-bg: #0c0e12;", 1)[1]
    raw = re.findall(r"rgb\([0-9 /.]+\)|#[0-9a-fA-F]{3,8}\b", body)
    assert sorted(raw) == ["#fff", "rgb(12 14 18 / 0.85)"], raw


def test_the_tokens_documented_in_design_md_are_the_ones_in_the_css():
    design = (Path(__file__).resolve().parents[1] / "DESIGN.md").read_text().lower()
    for name in ("bg", "card", "border", "text", "mint", "hot", "amber"):
        assert TOKENS[name].lower() in design, f"--{name} {TOKENS[name]} is missing from DESIGN.md"
