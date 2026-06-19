"""Game registry for the MiniChess-only project."""

try:
    import gui.config as _cfg
except ImportError:
    import config as _cfg

try:
    from gui.games.minichess_engine import (
        MiniChessState,
        format_move as _minichess_format_move,
        PLAYER_LABELS as _minichess_labels,
        PLAYER_COLORS as _minichess_colors,
    )
    from gui.games.minichess_renderer import MiniChessRenderer
except ImportError:
    from games.minichess_engine import (
        MiniChessState,
        format_move as _minichess_format_move,
        PLAYER_LABELS as _minichess_labels,
        PLAYER_COLORS as _minichess_colors,
    )
    from games.minichess_renderer import MiniChessRenderer


def get_game_module(game_name: str) -> tuple:
    """Return MiniChess state, formatter, renderer, labels, and colors."""
    _cfg.DROP_PIECE_CHAR = {}
    _cfg.CHAR_TO_DROP_PIECE = {}
    _cfg.PROMOTE_MAP = {}
    return (
        MiniChessState,
        _minichess_format_move,
        MiniChessRenderer,
        _minichess_labels,
        _minichess_colors,
    )


def configure_board_size(game_name: str) -> None:
    """Set MiniChess board dimensions."""
    _cfg.HAND_ROW_H = 0
    _cfg.BOARD_H = 6
    _cfg.BOARD_W = 5
    _cfg.SQUARE_SIZE = 80
    _cfg.MAX_STEP = 100
    _cfg.SCORE_PLOT_MAX_CP = 500
    _cfg.SCORE_DISPLAY_DIV = 100

    _cfg.BOARD_PIXEL_W = _cfg.BOARD_W * _cfg.SQUARE_SIZE
    _cfg.BOARD_PIXEL_H = _cfg.BOARD_H * _cfg.SQUARE_SIZE
    _cfg.COL_LABELS = "".join(chr(65 + i) for i in range(_cfg.BOARD_W))
    _cfg.ROW_LABELS = [str(_cfg.BOARD_H - i) for i in range(_cfg.BOARD_H)]

    _cfg.HAND_TOP_Y = _cfg.BOARD_Y
    _cfg.HAND_BOTTOM_Y = _cfg.BOARD_Y + _cfg.BOARD_PIXEL_H + _cfg.LABEL_MARGIN
    total_h = _cfg.BOARD_PIXEL_H + _cfg.LABEL_MARGIN
    _cfg.PANEL_X = _cfg.BOARD_X + _cfg.BOARD_PIXEL_W + 16
    _cfg.PANEL_Y = _cfg.HAND_TOP_Y
    _cfg.PANEL_H = max(getattr(_cfg, "PANEL_H", total_h), total_h)
    _cfg.BOTTOM_Y = _cfg.HAND_TOP_Y + total_h + 4
    _cfg.WINDOW_W = _cfg.PANEL_X + _cfg.PANEL_WIDTH + 12
    _cfg.WINDOW_H = _cfg.BOTTOM_Y + _cfg.BOTTOM_H + 8
