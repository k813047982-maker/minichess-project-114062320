"""Side panel and bottom panel rendering for the MiniChess GUI."""

import pygame

try:
    import gui.config as cfg
except ImportError:
    import config as cfg


def _make_font(size, bold=False):
    for name in ("Segoe UI", "Helvetica", "Arial", None):
        font = pygame.font.SysFont(name, size, bold=bold)
        if font is not None:
            return font


def _draw_rounded_rect(surface, rect, color, radius=10):
    x, y, w, h = rect
    radius = min(radius, w // 2, h // 2)
    pygame.draw.rect(surface, color, (x + radius, y, w - 2 * radius, h))
    pygame.draw.rect(surface, color, (x, y + radius, w, h - 2 * radius))
    corners = [
        (x + radius, y + radius),
        (x + w - radius, y + radius),
        (x + radius, y + h - radius),
        (x + w - radius, y + h - radius),
    ]
    for cx, cy in corners:
        pygame.draw.circle(surface, color, (cx, cy), radius)


class Button:
    def __init__(self, x, y, width, height, text, font):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.font = font
        self.enabled = True
        self.active = False  # "on" state — different color

    def draw(self, surface, mouse_pos):
        if not self.enabled:
            bg = (45, 45, 50)
            fg = (90, 90, 90)
        elif self.active:
            bg = (
                (40, 100, 60)
                if not self.rect.collidepoint(mouse_pos)
                else (50, 120, 70)
            )
            fg = (200, 255, 200)
        elif self.rect.collidepoint(mouse_pos):
            bg = cfg.COLOR_BTN_HOVER
            fg = cfg.COLOR_BTN_TEXT
        else:
            bg = cfg.COLOR_BTN
            fg = cfg.COLOR_BTN_TEXT
        pygame.draw.rect(surface, bg, self.rect, border_radius=6)
        pygame.draw.rect(
            surface, cfg.COLOR_TEXT_DIM, self.rect, width=1, border_radius=6
        )
        label = self.font.render(self.text, True, fg)
        lx = self.rect.x + (self.rect.width - label.get_width()) // 2
        ly = self.rect.y + (self.rect.height - label.get_height()) // 2
        surface.blit(label, (lx, ly))

    def is_clicked(self, x, y):
        return self.enabled and self.rect.collidepoint(x, y)


class SidePanel:
    _PAD_TOP = 12
    _PAD_LEFT = 14
    _LINE_GAP = 6
    _SECTION_GAP = 10
    _SEPARATOR_INSET = 8
    _BTN_HEIGHT = 36
    _BTN_GAP = 10
    _BTN_BOTTOM_MARGIN = 14
    _DOT_RADIUS = 12
    _SCORE_PLOT_MAX_CP = None  # set from cfg at draw time
    _HISTORY_LINE_H = 20

    def __init__(self, surface):
        self.surface = surface

        self.font_title = _make_font(cfg.FONT_SIZE_STATUS, bold=True)
        self.font_normal = _make_font(cfg.FONT_SIZE_PANEL)
        self.font_btn = _make_font(cfg.FONT_SIZE_BTN, bold=True)
        self.font_bold = _make_font(cfg.FONT_SIZE_PANEL, bold=True)
        self.font_small = _make_font(cfg.FONT_SIZE_PANEL - 2)

        btn2_w = (cfg.PANEL_WIDTH - 2 * self._PAD_LEFT - self._BTN_GAP) // 2
        btn3_w = (cfg.PANEL_WIDTH - 2 * self._PAD_LEFT - 2 * self._BTN_GAP) // 3
        bx = cfg.PANEL_X + self._PAD_LEFT

        # Bottom row: Analyze | Undo | Settings
        btn_y2 = cfg.PANEL_Y + cfg.PANEL_H - self._BTN_BOTTOM_MARGIN - self._BTN_HEIGHT
        self.btn_analyze = Button(
            bx, btn_y2, btn3_w, self._BTN_HEIGHT, "Analyze", self.font_btn
        )
        self.btn_undo = Button(
            bx + btn3_w + self._BTN_GAP,
            btn_y2,
            btn3_w,
            self._BTN_HEIGHT,
            "Undo",
            self.font_btn,
        )
        self.btn_settings = Button(
            bx + 2 * (btn3_w + self._BTN_GAP),
            btn_y2,
            btn3_w,
            self._BTN_HEIGHT,
            "Settings",
            self.font_btn,
        )

        # Top row: New | Stop | Reset
        btn_y1 = btn_y2 - self._BTN_HEIGHT - self._BTN_GAP
        self.btn_new_game = Button(
            bx, btn_y1, btn3_w, self._BTN_HEIGHT, "New", self.font_btn
        )
        self.btn_stop = Button(
            bx + btn3_w + self._BTN_GAP,
            btn_y1,
            btn3_w,
            self._BTN_HEIGHT,
            "Stop",
            self.font_btn,
        )
        self.btn_reset = Button(
            bx + 2 * (btn3_w + self._BTN_GAP),
            btn_y1,
            btn3_w,
            self._BTN_HEIGHT,
            "Reset",
            self.font_btn,
        )

        self._scroll_offset = 0
        self._frame = 0

    # ==================================================================
    # Right panel (status / controls)
    # ==================================================================

    def draw(
        self,
        state,
        ai_thinking=False,
        game_result=None,
        ai_depth=None,
        mode="human_vs_human",
        time_limit=cfg.DEFAULT_TIMEOUT,
        search_info=None,
        paused=False,
        analyze_enabled=False,
        gaming=False,
        player_labels=None,
        player_colors=None,
    ):
        self._frame += 1
        mouse_pos = pygame.mouse.get_pos()
        if search_info is None:
            search_info = {}
        if player_labels is None:
            player_labels = {0: "White", 1: "Black"}
        if player_colors is None:
            player_colors = {0: (255, 255, 255), 1: (30, 30, 30)}
        p0_name = player_labels.get(0, "White")
        p1_name = player_labels.get(1, "Black")

        _draw_rounded_rect(
            self.surface,
            (cfg.PANEL_X, cfg.PANEL_Y, cfg.PANEL_WIDTH, cfg.PANEL_H),
            cfg.COLOR_PANEL_BG,
            radius=10,
        )

        cx = cfg.PANEL_X + self._PAD_LEFT
        cy = cfg.PANEL_Y + self._PAD_TOP

        # Title: mode + gaming state indicator
        mode_labels = {
            "human_vs_human": "Human vs Human",
            "human_vs_ai": "Human vs AI",
            "ai_vs_ai": "AI vs AI",
        }
        if gaming:
            title_label = mode_labels.get(mode, mode)
            title_color = (100, 220, 100)  # green = game in progress
        elif analyze_enabled:
            title_label = "Analyze"
            title_color = (100, 200, 220)  # cyan
        elif game_result is not None and game_result != "stopped":
            title_label = mode_labels.get(mode, mode)
            title_color = cfg.COLOR_TEXT_DIM  # dimmed = game over
        else:
            title_label = "Free Play"
            title_color = cfg.COLOR_TEXT
        surf = self.font_title.render(title_label, True, title_color)
        self.surface.blit(surf, (cx, cy))
        cy += surf.get_height() + self._SECTION_GAP

        if game_result is not None:
            text, color = self._result_info(game_result, player_labels)
            surf = self.font_bold.render(text, True, color)
            self.surface.blit(surf, (cx, cy))
            cy += surf.get_height() + self._LINE_GAP
        else:
            dot_color = player_colors.get(state.current_player, (180, 180, 180))
            dot_cx = cx + self._DOT_RADIUS
            dot_cy = cy + self._DOT_RADIUS
            pygame.draw.circle(
                self.surface, dot_color, (dot_cx, dot_cy), self._DOT_RADIUS
            )
            pygame.draw.circle(
                self.surface,
                cfg.COLOR_TEXT_DIM,
                (dot_cx, dot_cy),
                self._DOT_RADIUS,
                width=1,
            )
            who = (
                f"{p0_name} to move"
                if state.current_player == 0
                else f"{p1_name} to move"
            )
            surf = self.font_normal.render(who, True, cfg.COLOR_TEXT)
            self.surface.blit(surf, (cx + self._DOT_RADIUS * 2 + 8, cy + 2))
            cy += max(surf.get_height(), self._DOT_RADIUS * 2) + self._LINE_GAP

        surf = self.font_normal.render(
            f"Step {state.step} / {cfg.MAX_STEP}", True, cfg.COLOR_TEXT_DIM
        )
        self.surface.blit(surf, (cx, cy))
        cy += surf.get_height() + self._SECTION_GAP

        status_text = None
        status_color = cfg.COLOR_TEXT
        if analyze_enabled and paused:
            status_text = "Paused"
            status_color = (200, 200, 100)
        elif analyze_enabled and search_info.get("depth") is not None:
            n_dots = (self._frame // (cfg.FPS // 3)) % 3 + 1
            status_text = "Analyzing" + "." * n_dots
            status_color = (100, 200, 220)
        elif analyze_enabled:
            n_dots = (self._frame // (cfg.FPS // 3)) % 3 + 1
            status_text = "Loading" + "." * n_dots
            status_color = (180, 180, 100)
        elif paused:
            status_text = "Paused"
            status_color = (200, 200, 100)
        elif ai_thinking:
            n_dots = (self._frame // (cfg.FPS // 3)) % 3 + 1
            status_text = "AI thinking" + "." * n_dots
        if status_text:
            surf = self.font_normal.render(status_text, True, status_color)
            self.surface.blit(surf, (cx, cy))
            cy += surf.get_height() + self._LINE_GAP

        cy = self._draw_search_stats(cx, cy, search_info, ai_depth, time_limit)

        pv_multi = search_info.get("pv_multi", {})
        if pv_multi:
            for mpv_idx in sorted(pv_multi.keys()):
                pv_moves = pv_multi[mpv_idx]
                if pv_moves:
                    score = search_info.get(f"score_mpv_{mpv_idx}")
                    prefix = f"PV{mpv_idx}: "
                    if score is not None:
                        prefix = f"PV{mpv_idx}({score:+d}): "
                    cy = self._draw_pv_line(cx, cy, prefix, pv_moves)
        elif search_info.get("pv"):
            cy = self._draw_pv(cx, cy, search_info["pv"])

        # Undo: disabled during gaming
        self.btn_undo.enabled = True  # always enabled (undo works during games too)
        self.btn_undo.draw(self.surface, mouse_pos)

        # Top row: New | Pause/Resume | Reset
        self.btn_new_game.draw(self.surface, mouse_pos)
        self.btn_stop.enabled = gaming
        self.btn_stop.text = "Resume" if paused else "Pause"
        self.btn_stop.draw(self.surface, mouse_pos)
        self.btn_reset.draw(self.surface, mouse_pos)

        top_btn = self.btn_new_game
        sep_y = top_btn.rect.y - self._SECTION_GAP - 2
        x1 = cfg.PANEL_X + self._SEPARATOR_INSET
        x2 = cfg.PANEL_X + cfg.PANEL_WIDTH - self._SEPARATOR_INSET
        pygame.draw.line(self.surface, cfg.COLOR_TEXT_DIM, (x1, sep_y), (x2, sep_y), 1)

        # Bottom row: Analyze | Undo | Settings
        self.btn_analyze.enabled = not gaming
        self.btn_analyze.active = analyze_enabled
        self.btn_analyze.draw(self.surface, mouse_pos)
        self.btn_undo.draw(self.surface, mouse_pos)
        self.btn_settings.draw(self.surface, mouse_pos)

    # ==================================================================
    # Bottom panel (eval bar | score plot | move table)
    # ==================================================================

    def draw_bottom(self, score_cp, score_history, move_history, player_colors=None):
        if player_colors is None:
            player_colors = {0: (255, 255, 255), 1: (30, 30, 30)}
        bx = cfg.BOTTOM_X
        by = cfg.BOTTOM_Y
        bw = cfg.WINDOW_W - 2 * cfg.BOTTOM_X
        bh = cfg.BOTTOM_H
        pad = 8

        _draw_rounded_rect(self.surface, (bx, by, bw, bh), cfg.COLOR_PANEL_BG, radius=8)

        inner_x = bx + pad
        inner_y = by + pad
        inner_h = bh - 2 * pad

        eval_w = cfg.BOTTOM_EVAL_W
        self._draw_eval_bar(inner_x, inner_y, eval_w, inner_h, score_cp, player_colors)

        plot_x = inner_x + eval_w + cfg.BOTTOM_GAP
        remaining_w = bw - 2 * pad - eval_w - cfg.BOTTOM_GAP
        plot_w = remaining_w // 2
        self._draw_score_plot(
            plot_x, inner_y, score_history, plot_w, inner_h, player_colors
        )

        table_x = plot_x + plot_w + cfg.BOTTOM_GAP
        table_w = bw - (table_x - bx) - pad
        self._draw_move_table(table_x, inner_y, table_w, inner_h, move_history)

    def _draw_eval_bar(self, x, y, w, h, score_cp, player_colors):
        """Vertical eval bar. Player0 on bottom, player1 on top.
        Positive score = player0 better = player0 section grows upward."""
        max_cp = getattr(cfg, "SCORE_PLOT_MAX_CP", 500)
        p0_color = player_colors.get(0, (230, 230, 230))
        p1_color = player_colors.get(1, (50, 50, 50))

        if score_cp is not None:
            clamped = max(-max_cp, min(max_cp, score_cp))
            p0_pct = 50 + clamped * 50 / max_cp
        else:
            p0_pct = 50

        p0_h = int(h * p0_pct / 100)
        p1_h = h - p0_h

        # Player1 on top
        if p1_h > 0:
            pygame.draw.rect(self.surface, p1_color, (x, y, w, p1_h))
        # Player0 on bottom
        if p0_h > 0:
            pygame.draw.rect(self.surface, p0_color, (x, y + p1_h, w, p0_h))

        pygame.draw.rect(self.surface, cfg.COLOR_TEXT_DIM, (x, y, w, h), 1)

        if score_cp is not None:
            divisor = getattr(cfg, "SCORE_DISPLAY_DIV", 100)
            score_display = score_cp / divisor
            sign = "+" if score_cp >= 0 else ""
            text = f"{sign}{score_display:.1f}"
        else:
            text = "0.0"
        surf = self.font_small.render(text, True, (180, 180, 0))
        tx = x + (w - surf.get_width()) // 2
        ty = y + (h - surf.get_height()) // 2
        bg_rect = pygame.Rect(tx - 1, ty, surf.get_width() + 2, surf.get_height())
        pygame.draw.rect(self.surface, (40, 40, 44), bg_rect)
        self.surface.blit(surf, (tx, ty))

    def _draw_score_plot(self, cx, cy, score_history, plot_w, plot_h, player_colors):
        """Score history chart.

        score_history entries: (player, score_cp, source)
        source: "white"/"black" (legacy) or "p0"/"p1", "analyze", "human"
        Higher = player0 better, lower = player1 better.
        Colors come from player_colors dict.
        """
        max_cp = getattr(cfg, "SCORE_PLOT_MAX_CP", 500)
        p0_color = player_colors.get(0, (230, 230, 230))
        p1_color = player_colors.get(1, (50, 50, 50))
        # Lighter variants for lines
        p0_line = tuple(min(255, c + 40) for c in p0_color)
        p1_line = tuple(min(255, c + 40) for c in p1_color)

        pygame.draw.rect(self.surface, (30, 30, 34), (cx, cy, plot_w, plot_h))

        mid_y = cy + plot_h // 2
        pygame.draw.line(
            self.surface, (80, 80, 80), (cx, mid_y), (cx + plot_w, mid_y), 1
        )
        for frac in (0.25, 0.75):
            ref_y = cy + int(plot_h * frac)
            pygame.draw.line(
                self.surface, (45, 45, 50), (cx, ref_y), (cx + plot_w, ref_y), 1
            )

        if not score_history:
            pygame.draw.rect(
                self.surface, cfg.COLOR_TEXT_DIM, (cx, cy, plot_w, plot_h), 1
            )
            return

        n_total = len(score_history)

        def to_screen(idx, score):
            if n_total <= 1:
                sx = cx + plot_w // 2
            else:
                sx = cx + int(idx / (n_total - 1) * (plot_w - 1))
            clamped = max(-max_cp, min(max_cp, score))
            sy = mid_y - int(clamped / max_cp * (plot_h // 2 - 2))
            return (sx, sy)

        # Separate points by source
        p0_pts = []
        p1_pts = []
        single_pts = []

        for i, entry in enumerate(score_history):
            player = entry[0]
            score = entry[1]
            source = entry[2] if len(entry) > 2 else "analyze"
            if score is None:
                continue
            if source in ("white", "p0"):
                p0_pts.append((i, score))
            elif source in ("black", "p1"):
                p1_pts.append((i, score))
            elif source in ("analyze", "human"):
                single_pts.append((i, player, score))

        # Single line (analyze / human-human)
        if single_pts:
            if len(single_pts) >= 2:
                pts = [to_screen(idx, s) for idx, _, s in single_pts]
                pygame.draw.lines(self.surface, (120, 120, 130), False, pts, 2)
            for idx, player, score in single_pts:
                sx, sy = to_screen(idx, score)
                c = p0_color if player == 0 else p1_color
                pygame.draw.circle(self.surface, c, (sx, sy), 3)
                pygame.draw.circle(self.surface, cfg.COLOR_TEXT_DIM, (sx, sy), 3, 1)

        # Player0 engine line
        if p0_pts:
            if len(p0_pts) >= 2:
                pts = [to_screen(idx, s) for idx, s in p0_pts]
                pygame.draw.lines(self.surface, p0_line, False, pts, 2)
            for idx, score in p0_pts:
                sx, sy = to_screen(idx, score)
                pygame.draw.circle(self.surface, p0_color, (sx, sy), 3)
                pygame.draw.circle(self.surface, cfg.COLOR_TEXT_DIM, (sx, sy), 3, 1)

        # Player1 engine line
        if p1_pts:
            if len(p1_pts) >= 2:
                pts = [to_screen(idx, s) for idx, s in p1_pts]
                pygame.draw.lines(self.surface, p1_line, False, pts, 2)
            for idx, score in p1_pts:
                sx, sy = to_screen(idx, score)
                pygame.draw.circle(self.surface, p1_color, (sx, sy), 3)
                pygame.draw.circle(self.surface, cfg.COLOR_TEXT_DIM, (sx, sy), 3, 1)

        pygame.draw.rect(self.surface, cfg.COLOR_TEXT_DIM, (cx, cy, plot_w, plot_h), 1)

        divisor = getattr(cfg, "SCORE_DISPLAY_DIV", 100)
        label_top = self.font_small.render(
            f"+{max_cp / divisor:.0f}", True, (90, 90, 90)
        )
        label_bot = self.font_small.render(
            f"-{max_cp / divisor:.0f}", True, (90, 90, 90)
        )
        self.surface.blit(label_top, (cx + 2, cy + 1))
        self.surface.blit(label_bot, (cx + 2, cy + plot_h - label_bot.get_height() - 1))

    def _draw_move_table(self, x, y, w, h, move_history):
        pygame.draw.rect(self.surface, (30, 30, 34), (x, y, w, h))
        pygame.draw.rect(self.surface, cfg.COLOR_TEXT_DIM, (x, y, w, h), 1)

        header = self.font_small.render("Moves", True, cfg.COLOR_TEXT_DIM)
        self.surface.blit(header, (x + 4, y + 2))
        header_h = header.get_height() + 4
        pygame.draw.line(
            self.surface, (60, 60, 64), (x, y + header_h), (x + w, y + header_h), 1
        )

        line_h = self._HISTORY_LINE_H
        avail_h = h - header_h - 2
        max_lines = max(1, avail_h // line_h)

        total = len(move_history)
        if total <= max_lines:
            self._scroll_offset = 0
        else:
            max_scroll = total - max_lines
            self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

        start = self._scroll_offset
        end = start + max_lines
        visible = move_history[start:end]

        ly = y + header_h + 2
        color_even = cfg.COLOR_TEXT
        color_odd = tuple(min(c + 15, 255) for c in cfg.COLOR_TEXT)

        for idx, line in enumerate(visible):
            color = color_even if idx % 2 == 0 else color_odd
            surf = self.font_small.render(line, True, color)
            self.surface.blit(surf, (x + 4, ly), area=(0, 0, w - 8, surf.get_height()))
            ly += line_h

        if total > end:
            dots = self.font_small.render("...", True, cfg.COLOR_TEXT_DIM)
            self.surface.blit(dots, (x + 4, ly))

    # ==================================================================
    # Interaction
    # ==================================================================

    def handle_click(self, x, y, **_kw):
        if self.btn_reset.is_clicked(x, y):
            return "reset"
        if self.btn_new_game.is_clicked(x, y):
            return "new_game"
        if self.btn_settings.is_clicked(x, y):
            return "settings"
        if self.btn_undo.is_clicked(x, y):
            return "undo"
        if self.btn_analyze.is_clicked(x, y):
            return "analyze"
        if self.btn_stop.is_clicked(x, y):
            return "stop"
        return None

    def set_scroll(self, direction):
        self._scroll_offset = max(0, self._scroll_offset + direction)

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _result_info(game_result, player_labels=None):
        if player_labels is None:
            player_labels = {0: "White", 1: "Black"}
        p0 = player_labels.get(0, "White")
        p1 = player_labels.get(1, "Black")
        if game_result in ("p0_checkmate",):
            return f"Checkmate! {p0} wins!", (100, 220, 100)
        if game_result in ("p1_checkmate",):
            return f"Checkmate! {p1} wins!", (220, 80, 80)
        if game_result == "p0_perpetual_check":
            return f"Perpetual check! {p0} wins!", (100, 220, 100)
        if game_result == "p1_perpetual_check":
            return f"Perpetual check! {p1} wins!", (220, 80, 80)
        if game_result in ("white_wins", "p0_wins"):
            return f"{p0} wins!", (100, 220, 100)
        if game_result in ("black_wins", "p1_wins"):
            return f"{p1} wins!", (220, 80, 80)
        if game_result == "stalemate_draw":
            return "Stalemate -- Draw!", (200, 200, 100)
        if game_result == "stopped":
            return "Game stopped", (180, 180, 180)
        return "Draw!", (200, 200, 100)

    def _draw_search_stats(self, cx, cy, search_info, ai_depth, time_limit):
        depth = search_info.get("depth")
        seldepth = search_info.get("seldepth")
        nodes = search_info.get("nodes")
        nps = search_info.get("nps")
        elapsed = search_info.get("time")

        if depth is not None:
            dt = f"Depth: {depth}/{seldepth}" if seldepth else f"Depth: {depth}"
            surf = self.font_normal.render(dt, True, cfg.COLOR_TEXT_DIM)
            self.surface.blit(surf, (cx, cy))
            cy += surf.get_height() + self._LINE_GAP
        elif ai_depth is not None:
            surf = self.font_normal.render(
                f"Depth: {ai_depth}", True, cfg.COLOR_TEXT_DIM
            )
            self.surface.blit(surf, (cx, cy))
            cy += surf.get_height() + self._LINE_GAP

        parts = []
        if nodes is not None:
            parts.append(f"Nodes: {self._fmt(nodes)}")
        if nps is not None:
            parts.append(f"NPS: {self._fmt(nps)}")
        if parts:
            surf = self.font_normal.render("  ".join(parts), True, cfg.COLOR_TEXT_DIM)
            self.surface.blit(surf, (cx, cy))
            cy += surf.get_height() + self._LINE_GAP

        if elapsed is not None:
            tt = f"Time: {elapsed / 1000.0:.2f}s"
        else:
            tt = f"Time: {time_limit}s"
        surf = self.font_normal.render(tt, True, cfg.COLOR_TEXT_DIM)
        self.surface.blit(surf, (cx, cy))
        cy += surf.get_height() + self._SECTION_GAP
        return cy

    def _draw_pv(self, cx, cy, pv_moves):
        return self._draw_pv_line(cx, cy, "PV: ", pv_moves)

    def _draw_pv_line(self, cx, cy, prefix, pv_moves):
        max_text_w = cfg.PANEL_WIDTH - 2 * self._PAD_LEFT
        pv_str = prefix + " ".join(pv_moves)
        surf = self.font_normal.render(pv_str, True, cfg.COLOR_TEXT_DIM)
        if surf.get_width() > max_text_w:
            for n in range(len(pv_moves), 0, -1):
                pv_str = prefix + " ".join(pv_moves[:n]) + " ..."
                surf = self.font_normal.render(pv_str, True, cfg.COLOR_TEXT_DIM)
                if surf.get_width() <= max_text_w:
                    break
        self.surface.blit(surf, (cx, cy))
        cy += surf.get_height() + self._LINE_GAP
        return cy

    @staticmethod
    def _fmt(value):
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return str(value)
