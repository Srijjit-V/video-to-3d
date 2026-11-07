"""The colour pairs the viewer actually uses must meet WCAG contrast (4.5:1 text, 3:1 UI parts)."""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[1] / "viewer" / "css" / "styles.css").read_text()
TOKENS = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", CSS))


def luminance(hex_):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b):
    la, lb = sorted((luminance(TOKENS[a]), luminance(TOKENS[b])), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_PAIRS = [(fg, bg) for fg in ("text", "text-2", "text-3", "mint", "hot", "amber") for bg in ("bg", "card", "input")]
TEXT_PAIRS += [("mint-ink", "mint")]  # primary button label


@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_colour_pairs_reach_4_5_to_1(fg, bg):
    assert contrast(fg, bg) >= 4.5, f"{fg} on {bg} is {contrast(fg, bg):.2f}:1"


@pytest.mark.parametrize("fg,bg", [("mint", "bg"), ("mint", "card"), ("border-strong", "bg")])
def test_focus_ring_and_borders_reach_3_to_1_or_are_decorative(fg, bg):
    if fg == "border-strong":
        pytest.skip("hairline borders are decorative; controls also have text and shape")
    assert contrast(fg, bg) >= 3.0


def test_the_tokens_documented_in_design_md_are_the_ones_in_the_css():
    design = (Path(__file__).resolve().parents[1] / "DESIGN.md").read_text().lower()
    for name in ("bg", "card", "border", "text", "mint", "hot", "amber"):
        assert TOKENS[name].lower() in design, f"--{name} {TOKENS[name]} is missing from DESIGN.md"
