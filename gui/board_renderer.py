"""Board renderer for UBGI games."""

import math

import pygame
import pygame.freetype

try:
    import gui.config as cfg
except ImportError:
    import config as cfg


class BoardRenderer:
    """Renders game boards on a Pygame surface."""

    # Font candidates in preference order
    _FONT_CANDIDATES = (
        "Segoe UI Symbol",
        "Apple Symbols",
        "DejaVu Sans",
        "Arial Unicode MS",
        "Helvetica",
        None,
    )

    def __init__(self, surface, game_renderer=None):
        self.surface = surface
        self.game_renderer = game_renderer

        self.label_font = None
        for name in self._FONT_CANDIDATES:
            try:
                font = pygame.freetype.SysFont(name, cfg.FONT_SIZE_LABEL)
                if name is not None and "freesansbold" in getattr(font, "path", ""):
                    continue
                self.label_font = font
                break
            except Exception:
                continue
        if self.label_font is None:
            self.label_font = pygame.freetype.Font(None, cfg.FONT_SIZE_LABEL)

        self._num_font = pygame.font.SysFont("Arial", 14, bold=True)

        # Flip icon (small button in upper-left corner of the board area)
        self._flip_icon_font = None
        for name in self._FONT_CANDIDATES:
            try:
                font = pygame.freetype.SysFont(name, 16)
                if name is not None and "freesansbold" in getattr(font, "path", ""):
                    continue
                self._flip_icon_font = font
                break
            except Exception:
                continue
        if self._flip_icon_font is None:
            self._flip_icon_font = pygame.freetype.Font(None, 16)
        self._flip_icon_rect = None  # set during draw

    # -----------------------------------------------------------------
    # Piece lookup (handles both chess and placement game board layouts)
    # -----------------------------------------------------------------

    def _get_piece(self, state, player, row, col):
        """Return the piece value for *player* at (row, col), or None."""
        try:
            piece = state.board[player][row][col]
            return piece if piece else None
        except (TypeError, IndexError):
            return None

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def draw(
        self,
        state,
        selected=None,
        legal_moves=None,
        last_move=None,
        pv_arrows=None,
        pv_multi=None,
    ):
        self._draw_squares()
        self._draw_last_move(last_move)
        self._draw_selected(selected)
        self._draw_legal_moves(state, selected, legal_moves)
        if self.game_renderer:
            self.game_renderer.draw_pieces(state)
        if pv_multi:
            # Delegate to game-specific renderer if it has draw_pv_multi
            if self.game_renderer and hasattr(self.game_renderer, "draw_pv_multi"):
                self.game_renderer.draw_pv_multi(state, pv_multi)
            else:
                current_player = getattr(state, "player", 0) if state else 0
                self._draw_pv_multi(pv_multi, current_player)
        elif pv_arrows:
            # Delegate to game-specific renderer if it has draw_pv
            if self.game_renderer and hasattr(self.game_renderer, "draw_pv"):
                self.game_renderer.draw_pv(state, pv_arrows)
            else:
                self._draw_pv_arrows(pv_arrows)
        self._draw_labels()
        self._draw_flip_icon()

    def hit_flip_icon(self, x, y):
        """Return True if (x, y) clicks the flip icon."""
        return self._flip_icon_rect is not None and self._flip_icon_rect.collidepoint(
            x, y
        )

    def screen_to_board(self, x, y):
        """Convert screen (x, y) to board (row, col).

        Returns (row, col) or None if the click is outside the board area.
        """
        if (
            x < cfg.BOARD_X
            or x >= cfg.BOARD_X + cfg.BOARD_PIXEL_W
            or y < cfg.BOARD_Y
            or y >= cfg.BOARD_Y + cfg.BOARD_PIXEL_H
        ):
            return None

        col = (x - cfg.BOARD_X) // cfg.SQUARE_SIZE
        row = (y - cfg.BOARD_Y) // cfg.SQUARE_SIZE

        # Clamp to valid range (defensive)
        col = max(0, min(col, cfg.BOARD_W - 1))
        row = max(0, min(row, cfg.BOARD_H - 1))

        if cfg.FLIPPED:
            row = cfg.BOARD_H - 1 - row
            col = cfg.BOARD_W - 1 - col

        return (row, col)

    def board_to_screen(self, row, col):
        """Convert board (row, col) to the top-left pixel (x, y) of that square."""
        return cfg.sq_xy(row, col)

    # -----------------------------------------------------------------
    # Internal drawing helpers
    # -----------------------------------------------------------------

    def _draw_squares(self):
        """Draw the alternating light/dark board squares."""
        for row in range(cfg.BOARD_H):
            for col in range(cfg.BOARD_W):
                x, y = self.board_to_screen(row, col)
                color = (
                    cfg.COLOR_LIGHT_SQ if (row + col) % 2 == 0 else cfg.COLOR_DARK_SQ
                )
                pygame.draw.rect(
                    self.surface, color, (x, y, cfg.SQUARE_SIZE, cfg.SQUARE_SIZE)
                )

    def _draw_overlay(self, row, col, color_with_alpha):
        """Draw a semi-transparent overlay on a single square."""
        overlay = pygame.Surface((cfg.SQUARE_SIZE, cfg.SQUARE_SIZE), pygame.SRCALPHA)
        overlay.fill(color_with_alpha)
        x, y = self.board_to_screen(row, col)
        self.surface.blit(overlay, (x, y))

    def _draw_last_move(self, last_move):
        """Highlight the from/to squares of the last move with a blue tint."""
        if last_move is None:
            return
        (fr, fc), (tr, tc) = last_move
        # Skip out-of-bounds squares (drop source or promotion encoding)
        if 0 <= fr < cfg.BOARD_H and 0 <= fc < cfg.BOARD_W:
            self._draw_overlay(fr, fc, cfg.COLOR_LAST_MOVE)
        actual_tr = tr - cfg.BOARD_H if tr >= cfg.BOARD_H else tr
        if 0 <= actual_tr < cfg.BOARD_H and 0 <= tc < cfg.BOARD_W:
            self._draw_overlay(actual_tr, tc, cfg.COLOR_LAST_MOVE)

    def _draw_selected(self, selected):
        """Highlight the currently selected piece square with a yellow tint."""
        if selected is None:
            return
        row, col = selected
        # Skip if out of bounds (e.g. hand piece selection in MiniShogi)
        if 0 <= row < cfg.BOARD_H and 0 <= col < cfg.BOARD_W:
            self._draw_overlay(row, col, cfg.COLOR_HIGHLIGHT)

    def _draw_legal_moves(self, state, selected, legal_moves):
        """Draw green indicators on each legal destination square.

        A filled green circle is drawn for empty destination squares.
        A green ring (hollow circle) is drawn if the destination contains an
        opponent piece.
        """
        if selected is None or legal_moves is None:
            return

        src = selected
        opponent = 1 - state.current_player
        radius = 12
        ring_width = 3
        drawn = set()  # avoid drawing duplicate indicators for promotion variants

        for move in legal_moves:
            (fr, fc), (tr, tc) = move
            if (fr, fc) != src:
                continue

            # Decode actual destination (promotion moves encode to_r += BOARD_H)
            actual_tr = tr - cfg.BOARD_H if tr >= cfg.BOARD_H else tr
            if actual_tr < 0 or actual_tr >= cfg.BOARD_H or tc < 0 or tc >= cfg.BOARD_W:
                continue
            if (actual_tr, tc) in drawn:
                continue
            drawn.add((actual_tr, tc))

            cx, cy = self.board_to_screen(actual_tr, tc)
            cx += cfg.SQUARE_SIZE // 2
            cy += cfg.SQUARE_SIZE // 2

            # Check whether the destination has an opponent piece
            opponent_piece = self._get_piece(state, opponent, actual_tr, tc)
            has_opponent = opponent_piece is not None

            # Use a per-pixel alpha surface for the indicator
            overlay = pygame.Surface(
                (cfg.SQUARE_SIZE, cfg.SQUARE_SIZE), pygame.SRCALPHA
            )
            local_cx = cfg.SQUARE_SIZE // 2
            local_cy = cfg.SQUARE_SIZE // 2

            if has_opponent:
                pygame.draw.circle(
                    overlay,
                    cfg.COLOR_LEGAL,
                    (local_cx, local_cy),
                    cfg.SQUARE_SIZE // 2 - 4,
                    ring_width,
                )
            else:
                pygame.draw.circle(
                    overlay, cfg.COLOR_LEGAL, (local_cx, local_cy), radius
                )

            sq_x, sq_y = self.board_to_screen(actual_tr, tc)
            self.surface.blit(overlay, (sq_x, sq_y))

    def _draw_pv_arrows(self, pv_moves):
        """Draw numbered arrows on the board for the principal variation."""
        if not pv_moves:
            return

        col_map = {chr(ord("a") + i): i for i in range(cfg.BOARD_W)}
        row_map = {str(cfg.BOARD_H - i): i for i in range(cfg.BOARD_H)}

        overlay = pygame.Surface(
            (cfg.WINDOW_W, cfg.WINDOW_H),
            pygame.SRCALPHA,
        )

        num_font = self._num_font

        max_arrows = min(len(pv_moves), 6)
        for i in range(max_arrows):
            uci = pv_moves[i]
            if len(uci) < 4:
                continue

            fc = col_map.get(uci[0])
            fr = row_map.get(uci[1])
            tc = col_map.get(uci[2])
            tr = row_map.get(uci[3])
            if any(v is None for v in (fc, fr, tc, tr)):
                continue

            alpha = max(60, 220 - i * 30)
            if i == 0:
                color = (80, 220, 80, alpha)
            else:
                color = (80, 160, 230, alpha)

            fx, fy = self.board_to_screen(fr, fc)
            tx, ty = self.board_to_screen(tr, tc)
            fx += cfg.SQUARE_SIZE // 2
            fy += cfg.SQUARE_SIZE // 2
            tx += cfg.SQUARE_SIZE // 2
            ty += cfg.SQUARE_SIZE // 2

            dx = tx - fx
            dy = ty - fy
            length = math.sqrt(dx * dx + dy * dy)
            if length < 1:
                continue
            ux, uy = dx / length, dy / length

            shaft_w = max(3, 7 - i)
            head_len = min(20, length * 0.3)
            head_w = head_len * 0.65

            # Shaft ends at the base of the arrowhead (not the tip)
            sx2 = tx - ux * head_len
            sy2 = ty - uy * head_len
            pygame.draw.line(overlay, color, (fx, fy), (sx2, sy2), shaft_w)

            # Arrowhead triangle
            px, py = -uy, ux
            points = [
                (tx, ty),
                (sx2 + px * head_w, sy2 + py * head_w),
                (sx2 - px * head_w, sy2 - py * head_w),
            ]
            pygame.draw.polygon(overlay, color, points)

            # Step number at midpoint of the arrow
            mid_x = (fx + tx) / 2
            mid_y = (fy + ty) / 2
            # Offset perpendicular to arrow so number doesn't sit on the shaft
            off = 10
            num_x = mid_x + px * off
            num_y = mid_y + py * off
            num_surf = num_font.render(str(i + 1), True, (255, 255, 255))
            # Background circle for readability
            nr = max(num_surf.get_width(), num_surf.get_height()) // 2 + 3
            pygame.draw.circle(
                overlay,
                (0, 0, 0, min(200, alpha)),
                (int(num_x), int(num_y)),
                nr,
            )
            overlay.blit(
                num_surf,
                (num_x - num_surf.get_width() / 2, num_y - num_surf.get_height() / 2),
            )

        self.surface.blit(overlay, (0, 0))

    def _draw_pv_multi(self, pv_multi, current_player=0):
        """Draw PV arrows.

        - Multi-PV first moves: GREEN arrows, very different sizes per rank
        - Best PV sequence (steps 2+): BLUE arrows with step numbers
        - No rank numbers on any arrow
        """
        if not pv_multi:
            return

        col_map = {chr(ord("a") + i): i for i in range(cfg.BOARD_W)}
        row_map = {str(cfg.BOARD_H - i): i for i in range(cfg.BOARD_H)}

        overlay = pygame.Surface(
            (cfg.WINDOW_W, cfg.WINDOW_H),
            pygame.SRCALPHA,
        )

        num_font = self._num_font

        def _parse_sq(s, pos):
            """Parse a square at position pos. Returns (row, col, next_pos) or None."""
            if pos >= len(s) or s[pos] not in col_map:
                return None
            c = col_map[s[pos]]
            pos += 1
            num_start = pos
            while pos < len(s) and s[pos].isdigit():
                pos += 1
            if num_start == pos:
                return None
            r = row_map.get(s[num_start:pos])
            if r is None:
                return None
            return (r, c, pos)

        # Build drop piece char → type mapping from config
        char_to_drop = getattr(cfg, "CHAR_TO_DROP_PIECE", {})

        def _parse_and_draw(uci, color, shaft_w, head_scale, player_turn=0):
            # Handle drop moves: X*sq (e.g. P*c3)
            if len(uci) >= 3 and uci[1] == "*":
                parsed = _parse_sq(uci, 2)
                if parsed is None:
                    return None
                tr, tc, _ = parsed
                _bx, _by = cfg.sq_xy(tr, tc)
                tx = _bx + cfg.SQUARE_SIZE // 2
                ty = _by + cfg.SQUARE_SIZE // 2

                # Try to find hand piece position from game renderer
                fx, fy = (
                    tx,
                    cfg.BOARD_Y + cfg.BOARD_H * cfg.SQUARE_SIZE + 20,
                )  # fallback
                gr = self.game_renderer
                if gr is not None and hasattr(gr, "_hand_rects"):
                    drop_pt = char_to_drop.get(
                        uci[0].upper(), char_to_drop.get(uci[0], 0)
                    )
                    hand_rect = gr._hand_rects.get((player_turn, drop_pt))
                    if hand_rect is not None:
                        fx = hand_rect.centerx
                        fy = hand_rect.centery
                    else:
                        # Fallback: generic hand area
                        if player_turn == 0:
                            fy = cfg.BOARD_Y + cfg.BOARD_H * cfg.SQUARE_SIZE + 25
                        else:
                            fy = cfg.BOARD_Y - 25

                dx, dy = tx - fx, ty - fy
                length = math.sqrt(dx * dx + dy * dy)
                if length < 1:
                    length = 1
                ux, uy = dx / length, dy / length
                head_len = min(16 * head_scale, length * 0.3)
                head_w = head_len * 0.6
                sx2 = tx - ux * head_len
                sy2 = ty - uy * head_len
                pygame.draw.line(
                    overlay, color, (int(fx), int(fy)), (int(sx2), int(sy2)), shaft_w
                )
                px, py = -uy, ux
                pts = [
                    (tx, ty),
                    (sx2 + px * head_w, sy2 + py * head_w),
                    (sx2 - px * head_w, sy2 - py * head_w),
                ]
                pygame.draw.polygon(overlay, color, pts)

                return (fx, fy, tx, ty, px, py)

            # Board move: parse two squares
            parsed_from = _parse_sq(uci, 0)
            if parsed_from is None:
                return None
            fr, fc, pos = parsed_from
            parsed_to = _parse_sq(uci, pos)
            if parsed_to is None:
                return None
            tr, tc, _ = parsed_to
            fx, fy = self.board_to_screen(fr, fc)
            tx, ty = self.board_to_screen(tr, tc)
            fx += cfg.SQUARE_SIZE // 2
            fy += cfg.SQUARE_SIZE // 2
            tx += cfg.SQUARE_SIZE // 2
            ty += cfg.SQUARE_SIZE // 2
            dx, dy = tx - fx, ty - fy
            length = math.sqrt(dx * dx + dy * dy)
            if length < 1:
                return None
            ux, uy = dx / length, dy / length
            head_len = min(20 * head_scale, length * 0.3)
            head_w = head_len * 0.65
            sx2 = tx - ux * head_len
            sy2 = ty - uy * head_len
            pygame.draw.line(overlay, color, (fx, fy), (sx2, sy2), shaft_w)
            px, py = -uy, ux
            pts = [
                (tx, ty),
                (sx2 + px * head_w, sy2 + py * head_w),
                (sx2 - px * head_w, sy2 - py * head_w),
            ]
            pygame.draw.polygon(overlay, color, pts)
            return (fx, fy, tx, ty, px, py)

        # --- Pass 1: Draw secondary PV first moves (behind best) ---
        for mpv_idx in sorted(pv_multi.keys(), reverse=True):
            if mpv_idx == 1:
                continue  # draw best PV last (on top)
            pv_moves = pv_multi[mpv_idx]
            if not pv_moves or len(pv_moves[0]) < 3:
                continue
            # Green with very distinct sizes per rank
            # PV2: bright green, thick. PV5+: dim green, thin.
            alpha = max(40, 240 - mpv_idx * 50)
            shaft_w = max(2, 9 - mpv_idx * 2)
            head_scale = max(0.5, 1.2 - mpv_idx * 0.15)
            color = (60 + mpv_idx * 10, max(120, 230 - mpv_idx * 25), 60, alpha)
            _parse_and_draw(pv_moves[0], color, shaft_w, head_scale, current_player)

        # --- Pass 2: Draw best PV first move (green, largest) ---
        best_pv = pv_multi.get(1, [])
        if best_pv and len(best_pv[0]) >= 3:
            color = (60, 230, 60, 240)
            _parse_and_draw(best_pv[0], color, 8, 1.3, current_player)

        # --- Pass 3: Draw best PV sequence steps 2+ (blue, with numbers) ---
        for i in range(1, len(best_pv)):
            uci = best_pv[i]
            if len(uci) < 3:
                continue
            player_at_step = (current_player + i) % 2
            alpha = max(80, 200 - i * 30)
            # Alternate colors: blue for side-to-move, orange for opponent
            if player_at_step == current_player:
                color = (80, 140, 230, alpha)
            else:
                color = (230, 140, 50, alpha)
            shaft_w = max(3, 6 - i)
            result = _parse_and_draw(uci, color, shaft_w, 1.0, player_at_step)
            if result:
                fx, fy, tx, ty, px, py = result
                # Step number
                mid_x = (fx + tx) / 2
                mid_y = (fy + ty) / 2
                num_x = mid_x + px * 10
                num_y = mid_y + py * 10
                label = str(i + 1)
                num_surf = num_font.render(label, True, (255, 255, 255))
                nr = max(num_surf.get_width(), num_surf.get_height()) // 2 + 3
                pygame.draw.circle(
                    overlay,
                    (0, 0, 0, min(200, alpha)),
                    (int(num_x), int(num_y)),
                    nr,
                )
                overlay.blit(
                    num_surf,
                    (
                        num_x - num_surf.get_width() / 2,
                        num_y - num_surf.get_height() / 2,
                    ),
                )

        self.surface.blit(overlay, (0, 0))

    def _draw_labels(self):
        """Draw row labels on the left and column labels below, respecting flip."""
        row_labels = cfg.ROW_LABELS
        col_labels = cfg.COL_LABELS
        if cfg.FLIPPED:
            row_labels = list(reversed(row_labels))
            col_labels = col_labels[::-1]

        for vis_row in range(cfg.BOARD_H):
            label = row_labels[vis_row]
            # Position to the left of the first column, vertically centred
            lx = cfg.BOARD_X - cfg.LABEL_MARGIN
            ly = cfg.BOARD_Y + vis_row * cfg.SQUARE_SIZE + cfg.SQUARE_SIZE // 2

            surf, rect = self.label_font.render(label, fgcolor=cfg.COLOR_TEXT_DIM)
            self.surface.blit(
                surf, (lx + (cfg.LABEL_MARGIN - rect.width) // 2, ly - rect.height // 2)
            )

        for vis_col in range(cfg.BOARD_W):
            label = col_labels[vis_col]
            # Position below the last row, horizontally centred
            lx = cfg.BOARD_X + vis_col * cfg.SQUARE_SIZE + cfg.SQUARE_SIZE // 2
            ly = cfg.BOARD_Y + cfg.BOARD_PIXEL_H

            surf, rect = self.label_font.render(label, fgcolor=cfg.COLOR_TEXT_DIM)
            self.surface.blit(
                surf, (lx - rect.width // 2, ly + (cfg.LABEL_MARGIN - rect.height) // 2)
            )

    def _draw_flip_icon(self):
        """Draw a small flip icon in the upper-left corner above the board."""
        icon_char = "\u21c5"  # ⇅ up-down arrows
        mouse_pos = pygame.mouse.get_pos()

        # Position: upper-left, between label margin and board top
        ix = 1
        iy = cfg.BOARD_Y - cfg.LABEL_MARGIN + 1
        iw, ih = cfg.LABEL_MARGIN - 2, cfg.LABEL_MARGIN - 2
        icon_rect = pygame.Rect(ix, iy, iw, ih)
        self._flip_icon_rect = icon_rect

        hovered = icon_rect.collidepoint(mouse_pos)
        if cfg.FLIPPED:
            bg = (50, 120, 70) if not hovered else (60, 140, 80)
        elif hovered:
            bg = (70, 70, 80)
        else:
            bg = (50, 50, 56)

        pygame.draw.rect(self.surface, bg, icon_rect, border_radius=4)
        fg = (200, 255, 200) if cfg.FLIPPED else cfg.COLOR_TEXT_DIM
        surf, rect = self._flip_icon_font.render(icon_char, fgcolor=fg)
        self.surface.blit(
            surf,
            (
                ix + (iw - rect.width) // 2,
                iy + (ih - rect.height) // 2,
            ),
        )
