import time
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import nowplaying
from nowplaying import (
    Debouncer,
    hex_to_str,
    needs_update,
    to_inky_palette,
    truncate,
    wrap_text,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def draw():
    """Mock ImageDraw where textlength returns 10px per character."""
    mock = MagicMock()
    mock.textlength.side_effect = lambda text, font=None: len(text) * 10
    return mock


class FakeInky:
    WHITE = 0
    BLACK = 1
    width = 400
    height = 300


# ---------------------------------------------------------------------------
# hex_to_str
# ---------------------------------------------------------------------------

class TestHexToStr:
    def test_basic_ascii(self):
        assert hex_to_str("48656c6c6f") == "Hello"

    def test_empty_string(self):
        assert hex_to_str("") == ""

    def test_null_sentinel(self):
        assert hex_to_str("00") == ""

    def test_none(self):
        assert hex_to_str(None) == ""

    def test_utf8_multibyte(self):
        text = "Björk"
        assert hex_to_str(text.encode("utf-8").hex()) == text

    def test_invalid_hex_returns_original(self):
        # Odd-length / non-hex falls back to the raw string
        assert hex_to_str("not-hex") == "not-hex"

    def test_real_api_title(self):
        # "Next Lifetime" as returned by the LinkPlay API
        assert hex_to_str("4e657874204c69666574696d65") == "Next Lifetime"


# ---------------------------------------------------------------------------
# needs_update
# ---------------------------------------------------------------------------

BASE = {"status": "play", "Title": "abc", "Artist": "xyz",
        "Album": "alb", "mode": "31", "vol": "50"}


class TestNeedsUpdate:
    def test_both_none(self):
        assert not needs_update(None, None)

    def test_prev_none_curr_dict(self):
        assert needs_update(None, BASE)

    def test_curr_none_prev_dict(self):
        assert needs_update(BASE, None)

    def test_identical(self):
        assert not needs_update(BASE, BASE.copy())

    @pytest.mark.parametrize("field", ["status", "Title", "Artist", "Album", "mode", "vol"])
    def test_tracked_field_changed(self, field):
        curr = {**BASE, field: "CHANGED"}
        assert needs_update(BASE, curr)

    def test_curpos_ignored(self):
        prev = {**BASE, "curpos": 1000}
        curr = {**BASE, "curpos": 9000}
        assert not needs_update(prev, curr)

    def test_totlen_ignored(self):
        prev = {**BASE, "totlen": 0}
        curr = {**BASE, "totlen": 240000}
        assert not needs_update(prev, curr)


# ---------------------------------------------------------------------------
# truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_fits_unchanged(self, draw):
        assert truncate(draw, "Hello", None, 200) == "Hello"

    def test_empty_string(self, draw):
        assert truncate(draw, "", None, 100) == ""

    def test_long_string_truncated(self, draw):
        # 10px/char; max 50px → at most 5 chars including ellipsis
        result = truncate(draw, "Hello World", None, 50)
        assert result.endswith("…")
        assert draw.textlength(result) <= 50

    def test_exact_fit_unchanged(self, draw):
        # "Hello" = 5 chars = 50px, max_px = 50 → fits exactly
        assert truncate(draw, "Hello", None, 50) == "Hello"


# ---------------------------------------------------------------------------
# wrap_text
# ---------------------------------------------------------------------------

class TestWrapText:
    def test_single_line(self, draw):
        # "Hi" = 20px, max 200px
        lines = wrap_text(draw, "Hi there", None, 200)
        assert lines == ["Hi there"]

    def test_wraps_to_two_lines(self, draw):
        # 10px/char; "Hello World" = 110px > 60px → wraps
        lines = wrap_text(draw, "Hello World", None, 60)
        assert len(lines) == 2
        assert lines[0] == "Hello"
        assert lines[1] == "World"

    def test_respects_max_lines(self, draw):
        lines = wrap_text(draw, "one two three four five", None, 50, max_lines=2)
        assert len(lines) <= 2

    def test_long_single_word_truncated(self, draw):
        # A word longer than max_width goes through truncate
        lines = wrap_text(draw, "Superlongword", None, 50)
        assert len(lines) == 1
        assert lines[0].endswith("…")


# ---------------------------------------------------------------------------
# Debouncer
# ---------------------------------------------------------------------------

class TestDebouncer:
    def test_initial_state(self):
        d = Debouncer(5.0)
        assert not d.pending
        assert d.latest is None

    def test_see_marks_pending(self):
        d = Debouncer(5.0)
        d.see("x", time.monotonic())
        assert d.pending
        assert d.latest == "x"

    def test_flush_before_settled_returns_none(self):
        d = Debouncer(5.0)
        now = 100.0
        d.see("x", now)
        assert d.flush(now + 3.0) is None  # only 3s elapsed, need 5s

    def test_flush_after_settled_returns_value(self):
        d = Debouncer(5.0)
        now = 100.0
        d.see("x", now)
        assert d.flush(now + 5.0) == "x"

    def test_flush_clears_pending(self):
        d = Debouncer(5.0)
        now = 100.0
        d.see("x", now)
        d.flush(now + 5.0)
        assert not d.pending

    def test_rapid_changes_do_not_reset_timer(self):
        d = Debouncer(5.0)
        now = 100.0
        d.see("first",  now + 0.0)
        d.see("second", now + 1.0)
        d.see("third",  now + 2.0)
        # timer anchored to first change (now+0), so settled at now+5
        assert d.flush(now + 4.9) is None
        assert d.flush(now + 5.0) == "third"

    def test_rapid_changes_coalesce_to_last(self):
        d = Debouncer(5.0)
        now = 100.0
        for i, val in enumerate(["a", "b", "c", "d"]):
            d.see(val, now + i * 0.5)
        result = d.flush(now + 20.0)
        assert result == "d"

    def test_take_bypasses_settle(self):
        d = Debouncer(5.0)
        now = 100.0
        d.see("x", now)
        assert d.take() == "x"
        assert not d.pending

    def test_flush_empty_returns_none(self):
        d = Debouncer(5.0)
        assert d.flush(time.monotonic()) is None


# ---------------------------------------------------------------------------
# to_inky_palette
# ---------------------------------------------------------------------------

class TestToInkyPalette:
    def test_output_mode(self):
        img = Image.new("L", (40, 30), 255)
        result = to_inky_palette(img, FakeInky())
        assert result.mode == "P"

    def test_output_size(self):
        img = Image.new("L", (40, 30), 255)
        result = to_inky_palette(img, FakeInky())
        assert result.size == (40, 30)

    def test_pixel_values_are_palette_indices(self):
        img = Image.new("L", (40, 30), 255)
        result = to_inky_palette(img, FakeInky())
        assert set(result.tobytes()).issubset({FakeInky.WHITE, FakeInky.BLACK})

    def test_white_image_maps_to_white_index(self):
        img = Image.new("L", (10, 10), 255)  # all white
        result = to_inky_palette(img, FakeInky())
        assert all(p == FakeInky.WHITE for p in result.tobytes())

    def test_black_image_maps_to_black_index(self):
        img = Image.new("L", (10, 10), 0)   # all black
        result = to_inky_palette(img, FakeInky())
        assert all(p == FakeInky.BLACK for p in result.tobytes())


# ---------------------------------------------------------------------------
# get_player_status
# ---------------------------------------------------------------------------

class TestGetPlayerStatus:
    def test_success(self, monkeypatch):
        payload = {"status": "play", "Title": "abc"}
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        monkeypatch.setattr("nowplaying.requests.get", lambda *a, **k: mock_resp)
        assert nowplaying.get_player_status() == payload

    def test_connection_error_returns_none(self, monkeypatch):
        import requests as req
        monkeypatch.setattr(
            "nowplaying.requests.get",
            MagicMock(side_effect=req.RequestException("timeout")),
        )
        assert nowplaying.get_player_status() is None

    def test_bad_json_returns_none(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("no json")
        monkeypatch.setattr("nowplaying.requests.get", lambda *a, **k: mock_resp)
        assert nowplaying.get_player_status() is None
