"""GUI configuration constants."""

import os

# Board dimensions (must match C++ config.hpp)
BOARD_H = 6
BOARD_W = 5
MAX_STEP = 100

# Piece codes (must match C++ state)
EMPTY, PAWN, ROOK, KNIGHT, BISHOP, QUEEN, KING = range(7)

# Unicode chess piece symbols: [player][piece_type]
PIECE_UNICODE = {
    0: {
        PAWN: "\u2659",
        ROOK: "\u2656",
        KNIGHT: "\u2658",
        BISHOP: "\u2657",
        QUEEN: "\u2655",
        KING: "\u2654",
    },
    1: {
        PAWN: "\u265f",
        ROOK: "\u265c",
        KNIGHT: "\u265e",
        BISHOP: "\u265d",
        QUEEN: "\u265b",
        KING: "\u265a",
    },
}

# Layout
SQUARE_SIZE = 80
LABEL_MARGIN = 24
BOARD_PIXEL_W = BOARD_W * SQUARE_SIZE
BOARD_PIXEL_H = BOARD_H * SQUARE_SIZE
BOARD_X = LABEL_MARGIN
BOARD_Y = LABEL_MARGIN
# Right panel (status / controls) — next to board
PANEL_WIDTH = 280
PANEL_X = BOARD_X + BOARD_PIXEL_W + 16
PANEL_Y = BOARD_Y
PANEL_H = BOARD_PIXEL_H

# Bottom panel (eval bar | score plot | move table) — below board
BOTTOM_H = 150
BOTTOM_Y = BOARD_Y + BOARD_PIXEL_H + LABEL_MARGIN + 4
BOTTOM_X = BOARD_X
BOTTOM_EVAL_W = 24  # thin vertical eval bar
BOTTOM_GAP = 8

WINDOW_W = PANEL_X + PANEL_WIDTH + 12
WINDOW_H = BOTTOM_Y + BOTTOM_H + 8

# Colors (RGB)
COLOR_BG = (32, 32, 36)
COLOR_LIGHT_SQ = (240, 217, 181)
COLOR_DARK_SQ = (181, 136, 99)
COLOR_HIGHLIGHT = (255, 255, 100, 140)  # selected piece
COLOR_LEGAL = (100, 200, 100, 160)  # legal move dot
COLOR_LAST_MOVE = (170, 210, 255, 100)  # last move highlight
COLOR_TEXT = (220, 220, 220)
COLOR_TEXT_DIM = (140, 140, 140)
COLOR_PANEL_BG = (42, 42, 48)
COLOR_BTN = (60, 60, 68)
COLOR_BTN_HOVER = (80, 80, 90)
COLOR_BTN_TEXT = (220, 220, 220)
COLOR_WHITE_PIECE = (255, 255, 255)
COLOR_BLACK_PIECE = (30, 30, 30)

# Fonts
FONT_SIZE_PIECE = 56
FONT_SIZE_LABEL = 16
FONT_SIZE_PANEL = 16
FONT_SIZE_BTN = 18
FONT_SIZE_STATUS = 20

# Axis labels (matching C++ game runner)
COL_LABELS = "ABCDE"
ROW_LABELS = ["6", "5", "4", "3", "2", "1"]

# Board flip (view from Black's perspective)
FLIPPED = False


def sq_xy(row, col):
    """Top-left pixel (x, y) of square (row, col), accounting for board flip."""
    if FLIPPED:
        row = BOARD_H - 1 - row
        col = BOARD_W - 1 - col
    return (BOARD_X + col * SQUARE_SIZE, BOARD_Y + row * SQUARE_SIZE)


# Paths
BUILD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build"
)

# Default AI timeout (seconds)
DEFAULT_TIMEOUT = 2

# AI vs AI delay between moves (seconds)
AI_VS_AI_DELAY = 0.5

# FPS
FPS = 30

# Algorithm selection
DEFAULT_ALGORITHM = "minimax"

# Piece symbols per game (extensible)
GAME_PIECES = {
    "MiniChess": {
        0: {
            1: "\u2659",
            2: "\u2656",
            3: "\u2658",
            4: "\u2657",
            5: "\u2655",
            6: "\u2654",
        },
        1: {
            1: "\u265f",
            2: "\u265c",
            3: "\u265e",
            4: "\u265d",
            5: "\u265b",
            6: "\u265a",
        },
    },
    "Connect6": {
        0: {1: "\u25cf"},  # black stone
        1: {1: "\u25cb"},  # white stone
    },
    "MiniShogi": {
        0: {
            1: "\u6b69",
            2: "\u9280",
            3: "\u91d1",
            4: "\u89d2",
            5: "\u98db",
            6: "\u738b",
            7: "\u3068",
            8: "\u5168",
            9: "\u99ac",
            10: "\u9f8d",
        },
        1: {
            1: "\u6b69",
            2: "\u9280",
            3: "\u91d1",
            4: "\u89d2",
            5: "\u98db",
            6: "\u7389",
            7: "\u3068",
            8: "\u5168",
            9: "\u99ac",
            10: "\u9f8d",
        },
    },
    "KohakuShogi": {
        0: {
            1: "\u6b69",  # 歩 Pawn
            2: "\u9280",  # 銀 Silver
            3: "\u91d1",  # 金 Gold
            4: "\u9999",  # 香 Lance
            5: "\u6842",  # 桂 Knight
            6: "\u89d2",  # 角 Bishop
            7: "\u98db",  # 飛 Rook
            8: "\u738b",  # 王 King
            9: "\u3068",  # と P_Pawn
            10: "\u5168",  # 全 P_Silver
            11: "\u674f",  # 杏 P_Lance
            12: "\u572d",  # 圭 P_Knight
            13: "\u99ac",  # 馬 P_Bishop
            14: "\u9f8d",  # 龍 P_Rook
        },
        1: {
            1: "\u6b69",
            2: "\u9280",
            3: "\u91d1",
            4: "\u9999",
            5: "\u6842",
            6: "\u89d2",
            7: "\u98db",
            8: "\u7389",  # 玉 King (gote)
            9: "\u3068",
            10: "\u5168",
            11: "\u674f",
            12: "\u572d",
            13: "\u99ac",
            14: "\u9f8d",
        },
    },
    "KohakuChess": {
        0: {
            1: "\u2659",
            2: "\u2656",
            3: "\u2658",
            4: "\u2657",
            5: "\u2655",
            6: "\u2654",
        },
        1: {
            1: "\u265f",
            2: "\u265c",
            3: "\u265e",
            4: "\u265d",
            5: "\u265b",
            6: "\u265a",
        },
    },
}
