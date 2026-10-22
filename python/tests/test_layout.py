"""A study's on-screen tags on a particular phone: corners, cut-outs, room for the bar, ruler check."""
import pytest

from socialeyes.phone.layout import MIN_ROW_DP, layout_checks, ruler_check, tag_boxes

# about the Motorola Edge 40 Pro: 1080 x 2400 px, ~397 dpi
PROFILE = {"screen_width_px": 1080, "screen_height_px": 2400, "density": 2.75, "xdpi": 397.6, "ydpi": 395.8,
           "rounded_corners": {}, "cutouts": []}
TAGS = {"steps": ["feed"], "layout": "bars", "family": "tag16h5", "size_mm": 10, "side_inset_mm": 3, "edge_gap_mm": 2}


def test_boxes_follow_the_app_geometry():
    b = tag_boxes(PROFILE, TAGS)
    px = 397.6 / 25.4
    cell = 10 * px / 6
    assert b["top_left"][0] == pytest.approx(3 * px - cell)          # black border 3 mm in, quiet zone outside it
    assert b["top_right"][2] == pytest.approx(1080 - 3 * px + cell)
    assert b["bottom_left"][3] == pytest.approx(2400 - 2 * 395.8 / 25.4 + cell)
    sq = tag_boxes(PROFILE, TAGS, quiet_zone=False)["top_left"]
    assert sq[2] - sq[0] == pytest.approx(10 * px)


def test_a_plain_screen_is_fine():
    assert layout_checks(PROFILE, TAGS) == []
    assert layout_checks(PROFILE, None) == [] and layout_checks(None, TAGS) == []
    assert layout_checks(PROFILE, {**TAGS, "layout": "bands"}) == []


def test_rounded_corners_that_reach_the_black_square_are_flagged_with_an_inset_that_clears_them():
    small = {**PROFILE, "rounded_corners": {c: 90 for c in ("top_left", "top_right", "bottom_right", "bottom_left")}}
    assert layout_checks(small, TAGS) == []                           # only the quiet zone's corner: fine
    big = {**PROFILE, "rounded_corners": {"top_left": 200, "top_right": 200}}
    (level, text), = layout_checks(big, TAGS)
    assert level == "warn" and "top-left, top-right" in text and "side_inset_mm to" in text
    suggested = float(text.split("side_inset_mm to ")[1].split(" mm")[0])
    assert suggested > 3 and layout_checks(big, {**TAGS, "side_inset_mm": suggested}) == []


def test_a_cutout_over_a_tag_is_flagged():
    holed = {**PROFILE, "cutouts": [[20, 10, 90, 80]]}                # a punch hole in the top-left corner
    assert any("cut-out covers the top-left" in t for _, t in layout_checks(holed, TAGS))


def test_a_narrow_screen_leaves_no_room_for_the_bar():
    narrow = {**PROFILE, "screen_width_px": 720, "density": 2.75}
    (level, text), = layout_checks(narrow, {**TAGS, "size_mm": 14, "side_inset_mm": 6})
    assert "between the top tags" in text and f"about {MIN_ROW_DP}" in text


def test_ruler_check_only_matters_for_eye_tracking():
    assert ruler_check(PROFILE, eye_tracking=False) == []
    assert ruler_check(None, True)[0][0] == "info"
    assert ruler_check(PROFILE, True)[0][0] == "warn"
    done = {**PROFILE, "ruler_check": {"at": 1, "measured_x_mm": 49.5, "measured_y_mm": 100.5}}
    assert ruler_check(done, True) == [("ok", "Screen size checked with a ruler (49.5 mm for 50, 100.5 mm for 100).")]
