"""ASCII art for Ralph's TUI."""

import os
from typing import List, Tuple

from ..utils import Colors


def _colorize_art(
    raw_lines: List[str],
    color_map_list: List[List[Tuple[int, int, str]]],
    color_codes: dict,
) -> List[str]:
    """Build colored art lines from raw art and color map.

    Args:
        raw_lines (List[str]): Original ASCII art lines
        color_map_list (List[List[Tuple[int, int, str]]]): Color mapping for each line
        color_codes (dict): Mapping of color names to color codes

    Returns:
        List[str]: Colorized art lines
    """
    result = []
    for line_idx, line in enumerate(raw_lines):
        if line_idx >= len(color_map_list):
            result.append(line + Colors.RESET)
            continue
        colored_line = ""
        colors = color_map_list[line_idx]
        for start, end, color_name in colors:
            segment = line[start:end]
            colored_line += f"{getattr(Colors, color_name, '')}{segment}"
        colored_line += Colors.RESET
        result.append(colored_line)
    return result


_COLOR_CODES = {
    "HAIR": Colors.HAIR,
    "SKIN": Colors.SKIN,
    "SHIRT_BLUE": Colors.SHIRT_BLUE,
    "RESET": Colors.RESET,
}


# Braille art
_BRAILLE_RAW = [
    "⠀⠀⠀⠀⠀⠀⣀⣤⣶⡶⢛⠟⡿⠻⢻⢿⢶⢦⣄⡀⠀⠀⠀⠀⠀⠀",
    "⠀⠀⠀⢀⣠⡾⡫⢊⠌⡐⢡⠊⢰⠁⡎⠘⡄⢢⠙⡛⡷⢤⡀⠀⠀⠀",
    "⠀⠀⢠⢪⢋⡞⢠⠃⡜⠀⠎⠀⠉⠀⠃⠀⠃⠀⠃⠙⠘⠊⢻⠦⠀⠀",
    "⠀⠀⢇⡇⡜⠀⠜⠀⠁⠀⢀⠔⠉⠉⠑⠄⠀⠀⡰⠊⠉⠑⡄⡇⠀⠀",
    "⠀⠀⡸⠧⠄⠀⠀⠀⠀⠀⠘⡀⠾⠀⠀⣸⠀⠀⢧⠀⠛⠀⠌⡇⠀⠀",
    "⠀⠘⡇⠀⠀⠀⠀⠀⠀⠀⠀⠙⠒⠒⠚⠁⠈⠉⠲⡍⠒⠈⠀⡇⠀⠀",
    "⠀⠀⠈⠲⣆⠀⠀⠀⠀⠀⠀⠀⠀⣠⠖⠉⡹⠤⠶⠁⠀⠀⠀⠈⢦⠀",
    "⠀⠀⠀⠀⠈⣦⡀⠀⠀⠀⠀⠧⣴⠁⠀⠘⠓⢲⣄⣀⣀⣀⡤⠔⠃⠀",
    "⠀⠀⠀⠀⣜⠀⠈⠓⠦⢄⣀⣀⣸⠀⠀⠀⠀⠁⢈⢇⣼⡁⠀⠀⠀⠀",
    "⠀⠀⢠⠒⠛⠲⣄⠀⠀⠀⣠⠏⠀⠉⠲⣤⠀⢸⠋⢻⣤⡛⣄⠀⠀⠀",
    "⠀⠀⢡⠀⠀⠀⠀⠉⢲⠾⠁⠀⠀⠀⠀⠈⢳⡾⣤⠟⠁⠹⣿⢆⠀⠀",
]

_BRAILLE_COLORS = [
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

_BRAILLE_FULL_RAW = [
    "⠀⠀⠀⠀⠀⠀⣀⣤⣶⡶⢛⠟⡿⠻⢻⢿⢶⢦⣄⡀⠀⠀⠀⠀⠀⠀",
    "⠀⠀⠀⢀⣠⡾⡫⢊⠌⡐⢡⠊⢰⠁⡎⠘⡄⢢⠙⡛⡷⢤⡀⠀⠀⠀",
    "⠀⠀⢠⢪⢋⡞⢠⠃⡜⠀⠎⠀⠉⠀⠃⠀⠃⠀⠃⠙⠘⠊⢻⠦⠀⠀",
    "⠀⠀⢇⡇⡜⠀⠜⠀⠁⠀⢀⠔⠉⠉⠑⠄⠀⠀⡰⠊⠉⠑⡄⡇⠀⠀",
    "⠀⠀⡸⠧⠄⠀⠀⠀⠀⠀⠘⡀⠾⠀⠀⣸⠀⠀⢧⠀⠛⠀⠌⡇⠀⠀",
    "⠀⠘⡇⠀⠀⠀⠀⠀⠀⠀⠀⠙⠒⠒⠚⠁⠈⠉⠲⡍⠒⠈⠀⡇⠀⠀",
    "⠀⠀⠈⠲⣆⠀⠀⠀⠀⠀⠀⠀⠀⣠⠖⠉⡹⠤⠶⠁⠀⠀⠀⠈⢦⠀",
    "⠀⠀⠀⠀⠈⣦⡀⠀⠀⠀⠀⠧⣴⠁⠀⠘⠓⢲⣄⣀⣀⣀⡤⠔⠃⠀",
    "⠀⠀⠀⠀⣜⠀⠈⠓⠦⢄⣀⣀⣸⠀⠀⠀⠀⠁⢈⢇⣼⡁⠀⠀⠀⠀",
    "⠀⠀⢠⠒⠛⠲⣄⠀⠀⠀⣠⠏⠀⠉⠲⣤⠀⢸⠋⢻⣤⡛⣄⠀⠀⠀",
    "⠀⠀⢡⠀⠀⠀⠀⠉⢲⠾⠁⠀⠀⠀⠀⠈⢳⡾⣤⠟⠁⠹⣿⢆⠀⠀",
    "⠀⢀⠼⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⠃⠀⠀⠀⠀⠀⠈⣧⠀",
    "⠀⡏⠀⠘⢦⡀⠀⠀⠀⠀⠀⠀⠀⠀⣠⠞⠁⠀⠀⠀⠀⠀⠀⠀⢸⣧",
    "⢰⣄⠀⠀⠀⠉⠳⠦⣤⣤⡤⠴⠖⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢯",
    "⢸⣉⠉⠓⠲⢦⣤⣄⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⣀⣠⣼",
]

_BRAILLE_FULL_COLORS = [
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

_BLOCKS_RAW = [
    "   ▓░  ▓  ░▓   ",
    "  ▓▓▓▓▓▓▓▓▓▓▓  ",
    " ▓▓▒▒▒▒▒▒▒▒▒▓▓ ",
    " ▓▒▒▒▒▒▒▒▒▒▒▒▓ ",
    " ▓▒ ●▒▒▒▒▒● ▒▓ ",
    " ▓▒▒▒▒ o ▒▒▒▒▓ ",
    " ▓▒▒ ~~~~~ ▒▒▓ ",
    " ▓▒▒▒▒▒▒▒▒▒▒▒▓ ",
    "  ▓▓▒▒▒▒▒▒▒▓▓  ",
    "   ███████████ ",
    "   █████████   ",
]

_BLOCKS_COLORS = [
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

_MINIMAL_RAW = [
    f"{Colors.HAIR}  .-~~~-.  {Colors.RESET}",
    f"{Colors.HAIR} /  {Colors.SKIN}o o{Colors.HAIR}  \\ {Colors.RESET}",
    f"{Colors.SKIN}|    <    |{Colors.RESET}",
    f"{Colors.SKIN} \\  ===  / {Colors.RESET}",
    f"{Colors.SHIRT_BLUE}  '-----'  {Colors.RESET}",
]


def get_ralph_art(style: str = "braille") -> List[str]:
    """Get Ralph art based on the specified style.

    Args:
        style (str, optional): Art style. Defaults to "braille".
            Possible values: 'none', 'braille', 'braille_full', 'blocks', 'minimal'

    Returns:
        List[str]: Colorized ASCII art lines
    """
    style = style.lower()

    if style == "none":
        return []
    elif style == "braille_full":
        art = _colorize_art(_BRAILLE_FULL_RAW, _BRAILLE_FULL_COLORS, _COLOR_CODES)
    elif style == "blocks":
        art = _colorize_art(_BLOCKS_RAW, _BLOCKS_COLORS, _COLOR_CODES)
    elif style == "minimal":
        art = _MINIMAL_RAW  # Already colored
    else:  # default: braille
        art = _colorize_art(_BRAILLE_RAW, _BRAILLE_COLORS, _COLOR_CODES)

    return art


# Default art constant
RALPH_ART: List[str] = get_ralph_art()
