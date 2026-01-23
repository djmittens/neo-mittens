"""Unit tests for ralph.utils module."""

import re

from ralph.utils import Colors, gen_id


class TestColors:
    """Tests for the Colors class."""

    def test_colors_are_strings(self):
        """All color constants should be strings."""
        color_attrs = [
            "RED",
            "GREEN",
            "YELLOW",
            "BLUE",
            "MAGENTA",
            "CYAN",
            "WHITE",
            "RESET",
            "NC",
            "BOLD",
            "DIM",
            "BRIGHT_YELLOW",
            "BRIGHT_RED",
            "BRIGHT_WHITE",
            "BRIGHT_BLUE",
            "BRIGHT_MAGENTA",
            "BRIGHT_CYAN",
            "BRIGHT_GREEN",
            "BRIGHT_BLACK",
            "GRAY",
            "PINK",
            "SKIN",
            "HAIR",
            "SHIRT_BLUE",
            "SHIRT_DARK",
            "BG_RED",
            "BG_GREEN",
            "BG_YELLOW",
            "BG_BLUE",
            "BG_MAGENTA",
            "BG_CYAN",
            "BG_WHITE",
            "BG_BLACK",
        ]
        for attr in color_attrs:
            value = getattr(Colors, attr)
            assert isinstance(value, str), f"Colors.{attr} should be a string"

    def test_colors_contain_ansi_escape(self):
        """Color constants should contain ANSI escape sequences."""
        assert Colors.RED.startswith("\033[")
        assert Colors.GREEN.startswith("\033[")
        assert Colors.RESET.startswith("\033[")

    def test_reset_ends_formatting(self):
        """RESET and NC should be the same escape code."""
        assert Colors.RESET == Colors.NC
        assert Colors.RESET == "\033[0m"


class TestGenId:
    """Tests for the gen_id function."""

    def test_gen_id_default_prefix(self):
        """gen_id() should return ID with 't' prefix by default."""
        id_str = gen_id()
        assert id_str.startswith("t-")

    def test_gen_id_custom_prefix(self):
        """gen_id() should accept custom prefix."""
        id_str = gen_id("i")
        assert id_str.startswith("i-")

        id_str = gen_id("x")
        assert id_str.startswith("x-")

    def test_gen_id_format(self):
        """gen_id() should return base36 format: {prefix}-{6 alphanumeric chars}."""
        id_str = gen_id()
        # Format: t-xxxxxx where x is [a-z0-9]
        pattern = r"^[a-z]-[a-z0-9]{6}$"
        assert re.match(pattern, id_str), f"ID '{id_str}' doesn't match expected format"

    def test_gen_id_uniqueness(self):
        """gen_id() should generate unique IDs."""
        ids = [gen_id() for _ in range(100)]
        unique_ids = set(ids)
        assert len(unique_ids) == 100, "Generated IDs should be unique"

    def test_gen_id_uniqueness_same_prefix(self):
        """gen_id() with same prefix should still generate unique IDs."""
        ids = [gen_id("t") for _ in range(50)]
        unique_ids = set(ids)
        assert len(unique_ids) == 50, "Generated IDs with same prefix should be unique"

    def test_gen_id_length(self):
        """gen_id() should return ID of consistent length."""
        for prefix in ["t", "i", "x"]:
            id_str = gen_id(prefix)
            # prefix (1) + dash (1) + 6 chars = 8 total
            assert len(id_str) == 8, f"ID length should be 8, got {len(id_str)}"
