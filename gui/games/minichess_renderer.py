"""MiniChess board renderer — chess pieces with Unicode glyphs."""

import pygame
import pygame.freetype

try:
    import gui.config as cfg
except ImportError:
    import config as cfg


class MiniChessRenderer:
    """Renders MiniChess board with pre-rendered Unicode chess piece glyphs."""

    _FONT_CANDIDATES = (
        "Segoe UI Symbol",
        "Apple Symbols",
        "DejaVu Sans",
        "Arial Unicode MS",
        "Menlo",
        None,
    )

    def __init__(self, surface):
        self.surface = surface

        self.piece_font = None
        for name in self._FONT_CANDIDATES:
            try:
                font = pygame.freetype.SysFont(name, cfg.FONT_SIZE_PIECE)
                if name is not None and "freesansbold" in getattr(font, "path", ""):
                    continue
                font.render(cfg.PIECE_UNICODE[0][cfg.KING], fgcolor=(255, 255, 255))
                self.piece_font = font
                break
            except Exception:
                continue
        if self.piece_font is None:
            self.piece_font = pygame.freetype.Font(None, cfg.FONT_SIZE_PIECE)

        self._glyphs = {0: {}, 1: {}}
        self._pre_render_glyphs()

    def _pre_render_glyphs(self):
        shadow_color = (0, 0, 0)
        piece_colors = {0: cfg.COLOR_WHITE_PIECE, 1: cfg.COLOR_BLACK_PIECE}
        for player in (0, 1):
            for piece_type in (
                cfg.PAWN,
                cfg.ROOK,
                cfg.KNIGHT,
                cfg.BISHOP,
                cfg.QUEEN,
                cfg.KING,
            ):
                char = cfg.PIECE_UNICODE[player][piece_type]
                fg = piece_colors[player]
                main_surf, main_rect = self.piece_font.render(char, fgcolor=fg)
                shadow_surf, _ = self.piece_font.render(char, fgcolor=shadow_color)
                self._glyphs[player][piece_type] = (main_surf, shadow_surf, main_rect)

    def draw_pieces(self, state):
        shadow_offsets = [(-1, -1), (1, -1), (-1, 1), (1, 1)]
        for player in (0, 1):
            for row in range(cfg.BOARD_H):
                for col in range(cfg.BOARD_W):
                    piece_type = self._get_piece(state, player, row, col)
                    if piece_type is None or piece_type == cfg.EMPTY:
                        continue
                    main_surf, shadow_surf, glyph_rect = self._glyphs[player][
                        piece_type
                    ]
                    sx, sy = cfg.sq_xy(row, col)
                    cx = sx + (cfg.SQUARE_SIZE - glyph_rect.width) // 2
                    cy = sy + (cfg.SQUARE_SIZE - glyph_rect.height) // 2
                    for dx, dy in shadow_offsets:
                        self.surface.blit(shadow_surf, (cx + dx, cy + dy))
                    self.surface.blit(main_surf, (cx, cy))

    def _get_piece(self, state, player, row, col):
        try:
            val = state.board[player][row][col]
            if isinstance(val, (int, float)):
                return int(val) if int(val) != cfg.EMPTY else None
        except (TypeError, IndexError, KeyError):
            pass
        for pt in (cfg.PAWN, cfg.ROOK, cfg.KNIGHT, cfg.BISHOP, cfg.QUEEN, cfg.KING):
            try:
                if state.board[player][pt][row][col]:
                    return pt
            except (TypeError, IndexError, KeyError):
                continue
        return None
