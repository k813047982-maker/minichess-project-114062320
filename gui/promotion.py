"""Promotion dialog mixin for GameApp."""

import pygame

try:
    import gui.config as _cfg
except ImportError:
    import config as _cfg


class PromotionMixin:

    def _show_promotion_dialog(self, row, col, promo_move, normal_move):
        """Show an inline promotion choice overlay on the board (shogi)."""
        self._promotion_dialog = {
            "row": row,
            "col": col,
            "promo_move": promo_move,
            "normal_move": normal_move,
        }

    def _show_chess_promotion_dialog(self, row, col, promo_moves):
        """Show a chess promotion dialog with 4 piece choices (Q/R/B/N).

        promo_moves is a list of moves with promo_idx encoded in to_r.
        promo_idx = to_r // BOARD_H: 1=Queen, 2=Rook, 3=Bishop, 4=Knight.
        """
        bh = _cfg.BOARD_H
        # Sort by promo_idx so order is always Q, R, B, N
        promo_moves_sorted = sorted(promo_moves, key=lambda m: m[1][0] // bh)
        # Map promo_idx -> piece_type for display
        promo_piece_types = {1: 5, 2: 2, 3: 4, 4: 3}  # Q=5, R=2, B=4, N=3
        self._promotion_dialog = {
            "type": "chess",
            "row": row,
            "col": col,
            "promo_moves": promo_moves_sorted,
            "promo_piece_types": promo_piece_types,
        }

    def _draw_promotion_dialog(self):
        """Draw the promotion choice overlay if active."""
        dlg = getattr(self, "_promotion_dialog", None)
        if dlg is None:
            return

        if dlg.get("type") == "chess":
            self._draw_chess_promotion_dialog(dlg)
        else:
            self._draw_shogi_promotion_dialog(dlg)

    def _draw_chess_promotion_dialog(self, dlg):
        """Draw chess promotion dialog with 4 piece choices (Q/R/B/N)."""
        surf = self.board_renderer.surface

        # Semi-transparent overlay
        overlay = pygame.Surface(
            (surf.get_width(), surf.get_height()),
            pygame.SRCALPHA,
        )
        overlay.fill((0, 0, 0, 100))
        surf.blit(overlay, (0, 0))

        row, col = dlg["row"], dlg["col"]
        sq = _cfg.SQUARE_SIZE
        promo_moves = dlg["promo_moves"]
        promo_piece_types = dlg["promo_piece_types"]
        bh = _cfg.BOARD_H

        # 4 boxes arranged vertically from the destination square
        box_size = int(sq * 1.1)
        gap = 4
        num_boxes = len(promo_moves)

        # Position: column of boxes centered on the destination column
        cx = _cfg.BOARD_X + col * sq + sq // 2
        start_x = cx - box_size // 2

        # Stack downward from destination (or upward if near bottom)
        dest_y = _cfg.BOARD_Y + row * sq
        total_h = num_boxes * (box_size + gap) - gap

        # Check if stacking downward fits; if not, stack upward
        if dest_y + total_h > surf.get_height() - 4:
            start_y = dest_y - total_h
        else:
            start_y = dest_y

        # Clamp
        if start_y < 4:
            start_y = 4
        if start_x < 4:
            start_x = 4
        max_x = surf.get_width() - box_size - 4
        if start_x > max_x:
            start_x = max_x

        player = self.game_state.player
        gr = self.board_renderer.game_renderer
        label_names = {1: "Q", 2: "R", 3: "B", 4: "N"}
        box_colors = [
            (220, 190, 120),  # Queen - gold
            (180, 180, 200),  # Rook - silver
            (160, 200, 160),  # Bishop - green tint
            (200, 170, 170),  # Knight - pink tint
        ]

        rects = []
        for idx, move in enumerate(promo_moves):
            promo_idx = move[1][0] // bh
            piece_type = promo_piece_types.get(promo_idx, 5)

            bx = start_x
            by = start_y + idx * (box_size + gap)

            rect = pygame.Rect(bx, by, box_size, box_size)
            color = box_colors[idx % len(box_colors)]
            pygame.draw.rect(surf, color, rect, border_radius=6)
            pygame.draw.rect(surf, (60, 40, 20), rect, 2, border_radius=6)

            # Draw piece glyph inside box
            if gr is not None and hasattr(gr, "_glyphs"):
                glyphs = gr._glyphs
                if player in glyphs and piece_type in glyphs[player]:
                    main_surf, shadow_surf, glyph_rect = glyphs[player][piece_type]
                    px = rect.centerx - glyph_rect.width // 2
                    py = rect.centery - glyph_rect.height // 2 - 6
                    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                        surf.blit(shadow_surf, (px + dx, py + dy))
                    surf.blit(main_surf, (px, py))

            # Label below piece
            try:
                label_font = pygame.font.SysFont("Arial", 12, bold=True)
                label = label_font.render(
                    label_names.get(promo_idx, "?"), True, (40, 40, 40)
                )
                surf.blit(
                    label,
                    (
                        rect.centerx - label.get_width() // 2,
                        rect.bottom - label.get_height() - 2,
                    ),
                )
            except Exception:
                pass

            rects.append((rect, move))

        dlg["choice_rects"] = rects

    def _draw_shogi_promotion_dialog(self, dlg):
        """Draw shogi promotion dialog (promote/keep)."""
        surf = self.board_renderer.surface

        # Semi-transparent overlay
        overlay = pygame.Surface(
            (surf.get_width(), surf.get_height()),
            pygame.SRCALPHA,
        )
        overlay.fill((0, 0, 0, 100))
        surf.blit(overlay, (0, 0))

        row, col = dlg["row"], dlg["col"]
        sq = _cfg.SQUARE_SIZE

        # Position: two boxes side by side centered on the destination square
        cx = _cfg.BOARD_X + col * sq + sq // 2
        cy = _cfg.BOARD_Y + row * sq + sq // 2
        box_w = int(sq * 1.2)
        box_h = int(sq * 1.4)
        gap = 8

        # Promote box (left), Keep box (right)
        left_x = cx - box_w - gap // 2
        right_x = cx + gap // 2

        # Clamp to screen bounds
        if left_x < 4:
            left_x = 4
            right_x = left_x + box_w + gap
        max_x = surf.get_width() - box_w - 4
        if right_x > max_x:
            right_x = max_x
            left_x = right_x - box_w - gap

        top_y = cy - box_h // 2
        if top_y < 4:
            top_y = 4
        max_y = surf.get_height() - box_h - 4
        if top_y > max_y:
            top_y = max_y

        # Draw "Promote" box
        promo_rect = pygame.Rect(left_x, top_y, box_w, box_h)
        pygame.draw.rect(surf, (220, 180, 120), promo_rect, border_radius=6)
        pygame.draw.rect(surf, (80, 50, 20), promo_rect, 2, border_radius=6)

        # Draw "Keep" box
        keep_rect = pygame.Rect(right_x, top_y, box_w, box_h)
        pygame.draw.rect(surf, (200, 200, 190), keep_rect, border_radius=6)
        pygame.draw.rect(surf, (80, 50, 20), keep_rect, 2, border_radius=6)

        # Draw piece previews inside boxes
        gr = self.board_renderer.game_renderer
        player = self.game_state.player
        if gr is not None and hasattr(gr, "_piece_cache"):
            fr, fc = dlg["promo_move"][0]
            bh = _cfg.BOARD_H
            base_piece = self.game_state.board[player][fr][fc] if fr < bh else fc

            promote_map = getattr(_cfg, "PROMOTE_MAP", {})
            promoted_piece = promote_map.get(base_piece)

            cache = gr._piece_cache
            if promoted_piece and (player, promoted_piece) in cache:
                s = cache[(player, promoted_piece)]
                surf.blit(
                    s,
                    (
                        promo_rect.centerx - s.get_width() // 2,
                        promo_rect.centery - s.get_height() // 2 - 8,
                    ),
                )
            if (player, base_piece) in cache:
                s = cache[(player, base_piece)]
                surf.blit(
                    s,
                    (
                        keep_rect.centerx - s.get_width() // 2,
                        keep_rect.centery - s.get_height() // 2 - 8,
                    ),
                )

        # Labels
        try:
            label_font = pygame.font.SysFont("Arial", 14, bold=True)
            promo_label = label_font.render("Promote", True, (180, 30, 30))
            keep_label = label_font.render("Keep", True, (40, 40, 40))
            surf.blit(
                promo_label,
                (
                    promo_rect.centerx - promo_label.get_width() // 2,
                    promo_rect.bottom - promo_label.get_height() - 4,
                ),
            )
            surf.blit(
                keep_label,
                (
                    keep_rect.centerx - keep_label.get_width() // 2,
                    keep_rect.bottom - keep_label.get_height() - 4,
                ),
            )
        except Exception:
            pass

        # Store rects for click handling
        dlg["promo_rect"] = promo_rect
        dlg["keep_rect"] = keep_rect

    def _handle_promotion_click(self, x, y):
        """Handle click during promotion dialog. Returns True if handled."""
        dlg = getattr(self, "_promotion_dialog", None)
        if dlg is None:
            return False

        if dlg.get("type") == "chess":
            return self._handle_chess_promotion_click(dlg, x, y)

        promo_rect = dlg.get("promo_rect")
        keep_rect = dlg.get("keep_rect")

        if promo_rect and promo_rect.collidepoint(x, y):
            self._promotion_dialog = None
            self.execute_move(dlg["promo_move"])
            return True
        elif keep_rect and keep_rect.collidepoint(x, y):
            self._promotion_dialog = None
            self.execute_move(dlg["normal_move"])
            return True
        else:
            # Click outside — cancel promotion
            self._promotion_dialog = None
            self._deselect_piece()
            return True

    def _handle_chess_promotion_click(self, dlg, x, y):
        """Handle click during chess promotion dialog. Returns True if handled."""
        choice_rects = dlg.get("choice_rects", [])
        for rect, move in choice_rects:
            if rect.collidepoint(x, y):
                self._promotion_dialog = None
                self.execute_move(move)
                return True

        # Click outside — cancel promotion
        self._promotion_dialog = None
        self._deselect_piece()
        return True
