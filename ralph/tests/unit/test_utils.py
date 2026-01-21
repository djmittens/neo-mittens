"""Unit tests for ralph.utils module - ID generation, ANSI formatting."""

import re
import time
from unittest.mock import patch

import pytest

from ralph.utils import (
    COLORS,
    Colors,
    colored,
    id_generate,
    strip_ansi,
)


class TestColors:
    """Tests for the Colors class."""

    def test_red_is_ansi_code(self) -> None:
        """Test RED is a valid ANSI escape code."""
        assert Colors.RED.startswith("\033[")
        assert Colors.RED.endswith("m")

    def test_green_is_ansi_code(self) -> None:
        """Test GREEN is a valid ANSI escape code."""
        assert Colors.GREEN.startswith("\033[")

    def test_nc_resets_color(self) -> None:
        """Test NC (No Color) is the reset code."""
        assert Colors.NC == "\033[0m"

    def test_all_colors_are_strings(self) -> None:
        """Test all color attributes are strings."""
        color_attrs = [
            Colors.RED,
            Colors.GREEN,
            Colors.YELLOW,
            Colors.BLUE,
            Colors.MAGENTA,
            Colors.CYAN,
            Colors.WHITE,
            Colors.NC,
            Colors.BRIGHT_YELLOW,
            Colors.BRIGHT_RED,
            Colors.BRIGHT_WHITE,
            Colors.BRIGHT_BLUE,
            Colors.BRIGHT_MAGENTA,
            Colors.DIM,
            Colors.PINK,
            Colors.SKIN,
            Colors.HAIR,
            Colors.SHIRT_BLUE,
            Colors.SHIRT_DARK,
        ]
        for color in color_attrs:
            assert isinstance(color, str)

    def test_colors_are_ansi_sequences(self) -> None:
        """Test all colors are valid ANSI escape sequences."""
        ansi_pattern = re.compile(r"\033\[[0-9;]+m")
        color_attrs = [
            Colors.RED,
            Colors.GREEN,
            Colors.YELLOW,
            Colors.BLUE,
            Colors.MAGENTA,
            Colors.CYAN,
            Colors.WHITE,
            Colors.NC,
        ]
        for color in color_attrs:
            assert ansi_pattern.match(color), f"{color!r} is not valid ANSI"


class TestColorsDict:
    """Tests for the COLORS dictionary."""

    def test_contains_basic_colors(self) -> None:
        """Test COLORS dict contains basic colors."""
        assert "red" in COLORS
        assert "green" in COLORS
        assert "yellow" in COLORS
        assert "blue" in COLORS
        assert "magenta" in COLORS
        assert "cyan" in COLORS
        assert "white" in COLORS
        assert "nc" in COLORS

    def test_keys_are_lowercase(self) -> None:
        """Test all keys are lowercase."""
        for key in COLORS:
            assert key == key.lower()

    def test_values_match_colors_class(self) -> None:
        """Test values match Colors class attributes."""
        assert COLORS["red"] == Colors.RED
        assert COLORS["green"] == Colors.GREEN
        assert COLORS["yellow"] == Colors.YELLOW
        assert COLORS["blue"] == Colors.BLUE
        assert COLORS["nc"] == Colors.NC

    def test_contains_extended_colors(self) -> None:
        """Test COLORS dict contains extended colors."""
        assert "bright_yellow" in COLORS
        assert "bright_red" in COLORS
        assert "dim" in COLORS
        assert "pink" in COLORS
        assert "skin" in COLORS


class TestColored:
    """Tests for the colored function."""

    def test_applies_color_and_reset(self) -> None:
        """Test applies color code and reset."""
        result = colored("test", "red")
        assert result.startswith(Colors.RED)
        assert result.endswith(Colors.NC)
        assert "test" in result

    def test_handles_green(self) -> None:
        """Test handles green color."""
        result = colored("success", "green")
        assert result.startswith(Colors.GREEN)
        assert "success" in result

    def test_case_insensitive(self) -> None:
        """Test color name is case-insensitive."""
        lower = colored("test", "red")
        upper = colored("test", "RED")
        mixed = colored("test", "Red")
        assert lower == upper == mixed

    def test_unknown_color_uses_raw_value(self) -> None:
        """Test unknown color name uses the value as-is."""
        result = colored("test", "\033[95m")
        assert result.startswith("\033[95m")
        assert "test" in result
        assert result.endswith(Colors.NC)

    def test_empty_text(self) -> None:
        """Test with empty text."""
        result = colored("", "red")
        assert result == f"{Colors.RED}{Colors.NC}"

    def test_multiline_text(self) -> None:
        """Test with multiline text."""
        result = colored("line1\nline2", "blue")
        assert "line1\nline2" in result
        assert result.startswith(Colors.BLUE)


class TestIdGenerate:
    """Tests for the id_generate function."""

    def test_returns_string(self) -> None:
        """Test returns a string."""
        result = id_generate()
        assert isinstance(result, str)

    def test_default_prefix_is_t(self) -> None:
        """Test default prefix is 't-'."""
        result = id_generate()
        assert result.startswith("t-")

    def test_custom_prefix(self) -> None:
        """Test custom prefix works."""
        result = id_generate("i")
        assert result.startswith("i-")

    def test_correct_format(self) -> None:
        """Test ID has correct format: {prefix}-{6 chars}."""
        result = id_generate("t")
        assert len(result) == 8
        assert result[1] == "-"
        assert result[0] == "t"

    def test_only_alphanumeric_after_prefix(self) -> None:
        """Test ID only contains lowercase alphanumeric after prefix."""
        result = id_generate()
        suffix = result[2:]
        assert suffix.isalnum()
        assert suffix == suffix.lower()

    def test_unique_ids(self) -> None:
        """Test generated IDs are unique."""
        ids = [id_generate() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_timestamp_component_varies(self) -> None:
        """Test timestamp component changes over time."""
        id1 = id_generate()
        time.sleep(0.01)
        id2 = id_generate()
        id3 = id_generate()
        ids = {id1, id2, id3}
        assert len(ids) == 3

    def test_different_prefixes_create_different_ids(self) -> None:
        """Test different prefixes create different IDs."""
        task_id = id_generate("t")
        issue_id = id_generate("i")
        assert task_id[0] == "t"
        assert issue_id[0] == "i"

    @patch("ralph.utils.time.time")
    @patch("ralph.utils.random.choice")
    def test_deterministic_with_mocks(self, mock_choice, mock_time) -> None:
        """Test ID generation is deterministic when mocked."""
        mock_time.return_value = 0
        mock_choice.return_value = "a"
        result = id_generate("t")
        assert result == "t-aaaaaa"

    def test_handles_long_prefix(self) -> None:
        """Test handles longer prefix."""
        result = id_generate("task")
        assert result.startswith("task-")

    def test_single_char_prefix(self) -> None:
        """Test single character prefix."""
        result = id_generate("x")
        assert result.startswith("x-")


class TestStripAnsi:
    """Tests for the strip_ansi function."""

    def test_strips_basic_colors(self) -> None:
        """Test strips basic color codes."""
        colored_text = f"{Colors.RED}error{Colors.NC}"
        result = strip_ansi(colored_text)
        assert result == "error"

    def test_strips_all_colors(self) -> None:
        """Test strips all color codes."""
        text = f"{Colors.GREEN}success{Colors.NC} and {Colors.RED}error{Colors.NC}"
        result = strip_ansi(text)
        assert result == "success and error"

    def test_plain_text_unchanged(self) -> None:
        """Test plain text is unchanged."""
        text = "plain text with no colors"
        result = strip_ansi(text)
        assert result == text

    def test_empty_string(self) -> None:
        """Test empty string returns empty."""
        assert strip_ansi("") == ""

    def test_only_ansi_codes(self) -> None:
        """Test string with only ANSI codes returns empty."""
        text = f"{Colors.RED}{Colors.GREEN}{Colors.NC}"
        result = strip_ansi(text)
        assert result == ""

    def test_strips_extended_colors(self) -> None:
        """Test strips extended 256-color codes."""
        text = f"{Colors.PINK}pink{Colors.NC}"
        result = strip_ansi(text)
        assert result == "pink"

    def test_strips_multiple_attributes(self) -> None:
        """Test strips codes with multiple attributes."""
        text = "\033[1;31;40mtest\033[0m"
        result = strip_ansi(text)
        assert result == "test"

    def test_preserves_newlines(self) -> None:
        """Test preserves newlines in text."""
        text = f"{Colors.RED}line1{Colors.NC}\n{Colors.GREEN}line2{Colors.NC}"
        result = strip_ansi(text)
        assert result == "line1\nline2"

    def test_preserves_tabs_and_spaces(self) -> None:
        """Test preserves tabs and spaces."""
        text = f"{Colors.BLUE}\t  spaced  \t{Colors.NC}"
        result = strip_ansi(text)
        assert result == "\t  spaced  \t"

    def test_strips_dim_attribute(self) -> None:
        """Test strips dim attribute."""
        text = f"{Colors.DIM}dimmed{Colors.NC}"
        result = strip_ansi(text)
        assert result == "dimmed"

    def test_handles_nested_codes(self) -> None:
        """Test handles nested/overlapping codes."""
        text = f"{Colors.RED}{Colors.BLUE}nested{Colors.NC}{Colors.NC}"
        result = strip_ansi(text)
        assert result == "nested"

    def test_strips_codes_in_middle(self) -> None:
        """Test strips codes in the middle of text."""
        text = f"before{Colors.RED}middle{Colors.NC}after"
        result = strip_ansi(text)
        assert result == "beforemiddleafter"


class TestIntegration:
    """Integration tests combining multiple utilities."""

    def test_colored_then_stripped(self) -> None:
        """Test that colored text can be stripped."""
        original = "test message"
        colored_text = colored(original, "red")
        stripped = strip_ansi(colored_text)
        assert stripped == original

    def test_multiple_colors_stripped(self) -> None:
        """Test stripping multiple colors."""
        text = colored("red", "red") + " " + colored("green", "green")
        result = strip_ansi(text)
        assert result == "red green"

    def test_id_contains_no_ansi(self) -> None:
        """Test generated IDs contain no ANSI codes."""
        for _ in range(10):
            id_val = id_generate()
            stripped = strip_ansi(id_val)
            assert id_val == stripped
