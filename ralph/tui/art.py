"""Ralph Wiggum ASCII Art Options.

Art style can be set via config file or RALPH_ART_STYLE environment variable:
  - "braille" (default): Braille dot art with colored regions (11 lines)
  - "braille_full": Full-body braille art (15 lines, includes legs)
  - "blocks": Block art using special characters (11 lines)
  - "minimal": Simple/minimal text art (5 lines)
  - "none": No art displayed
"""

import os
from typing import Dict, List, Tuple

from ralph.utils import Colors

__all__ = ["RALPH_ART", "RALPH_WIDTH", "get_ralph_art"]

_COLOR_CODES: Dict[str, str] = {
    "HAIR": Colors.HAIR,
    "SKIN": Colors.SKIN,
    "SHIRT_BLUE": Colors.SHIRT_BLUE,
    "NC": Colors.NC,
}

_BRAILLE_RAW = [
    "\u2800\u2800\u2800\u2800\u2800\u2800\u28c0\u28e4\u28f6\u2876\u28db\u281f\u287f\u28bb\u28fb\u28ff\u28f6\u28e6\u28c4\u2840\u2800\u2800\u2800\u2800\u2800\u2800",
    "\u2800\u2800\u2800\u28c0\u28e0\u2877\u2867\u28ab\u280c\u2810\u28a1\u280a\u28b0\u2801\u286e\u2818\u2864\u28a2\u281b\u285b\u2877\u28e4\u2840\u2800\u2800\u2800",
    "\u2800\u2800\u28e0\u28ea\u28ab\u287e\u28a0\u2803\u286c\u2800\u280e\u2800\u2809\u2800\u2803\u2800\u2803\u2800\u2803\u2819\u2818\u280a\u28bb\u28e6\u2800\u2800",
    "\u2800\u2800\u28c7\u2847\u286c\u2800\u281c\u2800\u2801\u2800\u28c0\u2814\u2809\u2809\u2891\u2804\u2800\u2800\u2870\u280a\u2809\u2891\u2864\u2847\u2800\u2800",
    "\u2800\u2800\u2878\u28a7\u2804\u2800\u2800\u2800\u2800\u2800\u2818\u2840\u28be\u2800\u2800\u28f8\u2800\u2800\u28e7\u2800\u281b\u2800\u280c\u2847\u2800\u2800",
    "\u2800\u2818\u2847\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2819\u28d2\u28d2\u285a\u2801\u2808\u2809\u28b2\u284d\u28d2\u2808\u2800\u2847\u2800\u2800",
    "\u2800\u2800\u2808\u28b2\u28c6\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u28e0\u2896\u2809\u2879\u28a4\u28b6\u2801\u2800\u2800\u2800\u2808\u28e6\u2800",
    "\u2800\u2800\u2800\u2800\u2808\u28e6\u2840\u2800\u2800\u2800\u2800\u28a7\u28f4\u2801\u2800\u2818\u28d3\u28f2\u28c4\u28c0\u28c0\u28c0\u2874\u2894\u2803\u2800",
    "\u2800\u2800\u2800\u2800\u28dc\u2800\u2808\u28d3\u28e6\u28c4\u28c0\u28c0\u28f8\u2800\u2800\u2800\u2800\u2801\u28c8\u28c7\u28fc\u2841\u2800\u2800\u2800\u2800",
    "\u2800\u2800\u28e0\u28d2\u281b\u28b2\u28c4\u2800\u2800\u2800\u28e0\u280f\u2800\u2809\u28b2\u28e4\u2800\u28f8\u280b\u28bb\u28e4\u285b\u28c4\u2800\u2800\u2800",
    "\u2800\u2800\u28a1\u2800\u2800\u2800\u2800\u2809\u28f2\u28be\u2801\u2800\u2800\u2800\u2800\u2808\u28b3\u287e\u28e4\u281f\u2801\u2879\u28bf\u28c6\u2800\u2800",
]
_BRAILLE_COLORS: List[List[Tuple[int, int, str]]] = [
    [(0, 26, "HAIR")],
    [(0, 26, "HAIR")],
    [(0, 26, "HAIR")],
    [(0, 5, "HAIR"), (5, 22, "SKIN"), (22, 26, "HAIR")],
    [(0, 5, "HAIR"), (5, 22, "SKIN"), (22, 26, "HAIR")],
    [(0, 3, "HAIR"), (3, 22, "SKIN"), (22, 26, "HAIR")],
    [(0, 26, "SKIN")],
    [(0, 26, "SKIN")],
    [(0, 10, "SKIN"), (10, 17, "SHIRT_BLUE"), (17, 26, "SKIN")],
    [(0, 2, "SKIN"), (2, 26, "SHIRT_BLUE")],
    [(0, 26, "SHIRT_BLUE")],
]
_BRAILLE_WIDTH = 26

_BRAILLE_FULL_RAW = [
    "\u2800\u2800\u2800\u2800\u2800\u2800\u28c0\u28e4\u28f6\u2876\u28db\u281f\u287f\u28bb\u28fb\u28ff\u28f6\u28e6\u28c4\u2840\u2800\u2800\u2800\u2800\u2800\u2800",
    "\u2800\u2800\u2800\u28c0\u28e0\u2877\u2867\u28ab\u280c\u2810\u28a1\u280a\u28b0\u2801\u286e\u2818\u2864\u28a2\u281b\u285b\u2877\u28e4\u2840\u2800\u2800\u2800",
    "\u2800\u2800\u28e0\u28ea\u28ab\u287e\u28a0\u2803\u286c\u2800\u280e\u2800\u2809\u2800\u2803\u2800\u2803\u2800\u2803\u2819\u2818\u280a\u28bb\u28e6\u2800\u2800",
    "\u2800\u2800\u28c7\u2847\u286c\u2800\u281c\u2800\u2801\u2800\u28c0\u2814\u2809\u2809\u2891\u2804\u2800\u2800\u2870\u280a\u2809\u2891\u2864\u2847\u2800\u2800",
    "\u2800\u2800\u2878\u28a7\u2804\u2800\u2800\u2800\u2800\u2800\u2818\u2840\u28be\u2800\u2800\u28f8\u2800\u2800\u28e7\u2800\u281b\u2800\u280c\u2847\u2800\u2800",
    "\u2800\u2818\u2847\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2819\u28d2\u28d2\u285a\u2801\u2808\u2809\u28b2\u284d\u28d2\u2808\u2800\u2847\u2800\u2800",
    "\u2800\u2800\u2808\u28b2\u28c6\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u28e0\u2896\u2809\u2879\u28a4\u28b6\u2801\u2800\u2800\u2800\u2808\u28e6\u2800",
    "\u2800\u2800\u2800\u2800\u2808\u28e6\u2840\u2800\u2800\u2800\u2800\u28a7\u28f4\u2801\u2800\u2818\u28d3\u28f2\u28c4\u28c0\u28c0\u28c0\u2874\u2894\u2803\u2800",
    "\u2800\u2800\u2800\u2800\u28dc\u2800\u2808\u28d3\u28e6\u28c4\u28c0\u28c0\u28f8\u2800\u2800\u2800\u2800\u2801\u28c8\u28c7\u28fc\u2841\u2800\u2800\u2800\u2800",
    "\u2800\u2800\u28e0\u28d2\u281b\u28b2\u28c4\u2800\u2800\u2800\u28e0\u280f\u2800\u2809\u28b2\u28e4\u2800\u28f8\u280b\u28bb\u28e4\u285b\u28c4\u2800\u2800\u2800",
    "\u2800\u2800\u28a1\u2800\u2800\u2800\u2800\u2809\u28f2\u28be\u2801\u2800\u2800\u2800\u2800\u2808\u28b3\u287e\u28e4\u281f\u2801\u2879\u28bf\u28c6\u2800\u2800",
    "\u2800\u28c0\u28bc\u28c6\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u28fc\u2803\u2800\u2800\u2800\u2800\u2800\u2808\u28e7\u2800",
    "\u2800\u280f\u2800\u2818\u28e6\u2840\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u28e0\u281e\u2801\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u28f8\u28e7",
    "\u28b0\u28c4\u2800\u2800\u2800\u2809\u28b3\u28e6\u28e4\u28e4\u2874\u28b6\u2897\u280b\u2801\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u28ef",
    "\u28f8\u28c9\u2809\u28d3\u28f2\u28e6\u28e4\u28c4\u28c0\u28c0\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u2800\u28c0\u28c0\u28c0\u28e0\u28fc",
]
_BRAILLE_FULL_COLORS: List[List[Tuple[int, int, str]]] = [
    [(0, 26, "HAIR")],
    [(0, 26, "HAIR")],
    [(0, 26, "HAIR")],
    [(0, 5, "HAIR"), (5, 22, "SKIN"), (22, 26, "HAIR")],
    [(0, 5, "HAIR"), (5, 22, "SKIN"), (22, 26, "HAIR")],
    [(0, 3, "HAIR"), (3, 22, "SKIN"), (22, 26, "HAIR")],
    [(0, 26, "SKIN")],
    [(0, 26, "SKIN")],
    [(0, 10, "SKIN"), (10, 17, "SHIRT_BLUE"), (17, 26, "SKIN")],
    [(0, 2, "SKIN"), (2, 26, "SHIRT_BLUE")],
    [(0, 26, "SHIRT_BLUE")],
    [(0, 26, "SHIRT_BLUE")],
    [(0, 26, "SHIRT_BLUE")],
    [(0, 26, "SHIRT_BLUE")],
    [(0, 26, "SHIRT_BLUE")],
]
_BRAILLE_FULL_WIDTH = 30

_BLOCKS_RAW = [
    "   \u2593\u2591  \u2593  \u2591\u2593   ",
    "  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593  ",
    " \u2593\u2593\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2593\u2593 ",
    " \u2593\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2593 ",
    " \u2593\u2592 \u25cf\u2592\u2592\u2592\u2592\u2592\u25cf \u2592\u2593 ",
    " \u2593\u2592\u2592\u2592\u2592 o \u2592\u2592\u2592\u2592\u2593 ",
    " \u2593\u2592\u2592 ~~~~~ \u2592\u2592\u2593 ",
    " \u2593\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2593 ",
    "  \u2593\u2593\u2592\u2592\u2592\u2592\u2592\u2592\u2592\u2593\u2593  ",
    "   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588 ",
    "   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588   ",
]
_BLOCKS_COLORS: List[List[Tuple[int, int, str]]] = [
    [(0, 15, "HAIR")],
    [(0, 15, "HAIR")],
    [(0, 3, "HAIR"), (3, 12, "SKIN"), (12, 15, "HAIR")],
    [(0, 2, "HAIR"), (2, 13, "SKIN"), (13, 15, "HAIR")],
    [(0, 2, "HAIR"), (2, 13, "SKIN"), (13, 15, "HAIR")],
    [(0, 2, "HAIR"), (2, 13, "SKIN"), (13, 15, "HAIR")],
    [(0, 2, "HAIR"), (2, 13, "SKIN"), (13, 15, "HAIR")],
    [(0, 2, "HAIR"), (2, 13, "SKIN"), (13, 15, "HAIR")],
    [(0, 3, "HAIR"), (3, 12, "SKIN"), (12, 15, "HAIR")],
    [(0, 15, "SHIRT_BLUE")],
    [(0, 15, "SHIRT_BLUE")],
]
_BLOCKS_WIDTH = 18

_MINIMAL_RAW = [
    f"{Colors.HAIR}  .-~~~-.  {Colors.NC}",
    f"{Colors.HAIR} /  {Colors.SKIN}o o{Colors.HAIR}  \\ {Colors.NC}",
    f"{Colors.SKIN}|    <    |{Colors.NC}",
    f"{Colors.SKIN} \\  ===  / {Colors.NC}",
    f"{Colors.SHIRT_BLUE}  '-----'  {Colors.NC}",
]
_MINIMAL_COLORS: List[List[Tuple[int, int, str]]] = []
_MINIMAL_WIDTH = 14


def _colorize_art(
    raw_lines: List[str],
    color_map_list: List[List[Tuple[int, int, str]]],
    color_codes: Dict[str, str],
) -> List[str]:
    """Build colored art lines from raw art and color map."""
    result = []
    for line_idx, line in enumerate(raw_lines):
        if line_idx >= len(color_map_list):
            result.append(line + Colors.NC)
            continue
        colored_line = ""
        colors = color_map_list[line_idx]
        for start, end, color_name in colors:
            segment = line[start:end]
            colored_line += f"{color_codes.get(color_name, '')}{segment}"
        colored_line += Colors.NC
        result.append(colored_line)
    return result


def get_ralph_art() -> Tuple[List[str], int]:
    """Get Ralph art based on RALPH_ART_STYLE environment variable.

    Returns:
        A tuple of (art_lines, width) where art_lines is a list of
        colored strings and width is the character width of the art.
    """
    style = os.environ.get("RALPH_ART_STYLE", "braille").lower()

    if style == "none":
        return [], 0
    elif style == "braille_full":
        return (
            _colorize_art(_BRAILLE_FULL_RAW, _BRAILLE_FULL_COLORS, _COLOR_CODES),
            _BRAILLE_FULL_WIDTH,
        )
    elif style == "blocks":
        return _colorize_art(_BLOCKS_RAW, _BLOCKS_COLORS, _COLOR_CODES), _BLOCKS_WIDTH
    elif style == "minimal":
        return _MINIMAL_RAW, _MINIMAL_WIDTH
    else:
        return (
            _colorize_art(_BRAILLE_RAW, _BRAILLE_COLORS, _COLOR_CODES),
            _BRAILLE_WIDTH,
        )


RALPH_ART, RALPH_WIDTH = get_ralph_art()
