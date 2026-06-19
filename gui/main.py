"""UBGI GUI -- entry point and game loop."""

import time
import tkinter as tk
import argparse

import pygame

try:
    from gui.board_renderer import BoardRenderer
    from gui.ui_panels import SidePanel
    from gui.ubgi_client import UBGIEngine, discover_engines
    from gui.engine_manager import EngineManagerMixin
    from gui.promotion import PromotionMixin
    from gui.dialogs import DialogsMixin
    from gui.game_registry import get_game_module, configure_board_size
    from gui.logger import log
    import gui.config as _cfg
except ImportError:
    from board_renderer import BoardRenderer
    from ui_panels import SidePanel
    from ubgi_client import UBGIEngine, discover_engines
    from engine_manager import EngineManagerMixin
    from promotion import PromotionMixin
    from dialogs import DialogsMixin
    from game_registry import get_game_module, configure_board_size
    from logger import log
    import config as _cfg


class GameApp(EngineManagerMixin, PromotionMixin, DialogsMixin):
    """Main application class."""

    def __init__(self, game_name="minichess"):
        # Configure board size BEFORE creating the window
        configure_board_size(game_name)

        # Initialize Tk BEFORE pygame to avoid NSApplication conflict on macOS.
        # SDL and Tk both register their own NSApplication subclass; whichever
        # comes second crashes.  Keeping a hidden Tk root alive lets us reuse
        # it for settings dialogs later.
        self._tk_root = tk.Tk()
        self._tk_root.withdraw()

        pygame.init()
        pygame.display.set_caption(game_name.capitalize())

        self.screen = pygame.display.set_mode((_cfg.WINDOW_W, _cfg.WINDOW_H))
        self.clock = pygame.time.Clock()

        # Select game module (state class, move formatter, renderer, labels, colors)
        state_cls, fmt_move, renderer_cls, player_labels, player_colors = (
            get_game_module(game_name)
        )
        self._state_class = state_cls
        self._format_move = fmt_move
        self._game_name = game_name
        self._player_labels = player_labels  # {0: "White"/"Black", 1: "Black"/"White"}
        self._player_colors = player_colors  # {0: (r,g,b), 1: (r,g,b)}

        game_renderer = renderer_cls(self.screen)
        self.board_renderer = BoardRenderer(self.screen, game_renderer=game_renderer)
        self.side_panel = SidePanel(self.screen)

        self.game_state = state_cls.initial()

        # Discover engines
        self._available_engines = discover_engines(_cfg.BUILD_DIR)

        # Engine option definitions
        self._engine_options = []
        self._engine_algorithms = []
        self._algo_options = {}
        self._algo_defaults = {}
        self._engine_cache = {}  # exe_path -> probe info (algorithms/options/defaults)
        self._last_probed_engine = None
        self._board_width = _cfg.BOARD_W
        self._board_height = _cfg.BOARD_H

        # Per-side state
        self.white = {
            "engine": None,  # path or None for human
            "algo": _cfg.DEFAULT_ALGORITHM,
            "params": {},  # algo-specific search params
            "depth": 0,  # 0 = use time limit
        }
        self.black = {
            "engine": self._best_engine_for_game(),
            "algo": _cfg.DEFAULT_ALGORITHM,
            "params": {},
            "depth": 0,
        }
        self.analyze = {
            "enabled": False,
            "engine": None,  # auto-select first available
            "algo": _cfg.DEFAULT_ALGORITHM,
            "params": {},
        }

        self.time_limit = _cfg.DEFAULT_TIMEOUT

        self._probe_engine_options()

        # Selection / interaction
        self.selected_piece = None
        self.legal_moves_for_selected = []
        self.last_move = None
        self._promotion_dialog = None

        # History
        self.move_history = []
        self.score_history = []

        self.game_result = None

        # AI state
        self.ai_thinking = False
        self.ai_result = {"move": None, "depth": 0, "ready": False}
        self.ai_depth = None

        # UCI state
        self.uci_moves = []
        self.search_info = {}
        self.white_uci_engine = None
        self.black_uci_engine = None

        # Analyze mode
        self._analyze_engine = None
        self._analyze_active = False  # True when we expect info lines
        self._undo_stack = []

        # MultiPV and PV display settings
        self.multi_pv = 1  # Number of PVs to search (1-10)
        self.pv_display_steps = 3  # How many moves to show per PV line

        # AI vs AI pacing
        self._last_ai_time = 0.0
        self._paused = False
        self._game_started = False  # only True after explicit New Game + OK

        self._running = True

    # ------------------------------------------------------------------
    # Mode property -- derived from engine selections
    # ------------------------------------------------------------------

    @property
    def mode(self):
        w_is_ai = self.white["engine"] is not None
        b_is_ai = self.black["engine"] is not None
        if w_is_ai and b_is_ai:
            return "ai_vs_ai"
        elif w_is_ai or b_is_ai:
            return "human_vs_ai"
        else:
            return "human_vs_human"

    # ------------------------------------------------------------------
    # Pause / Undo
    # ------------------------------------------------------------------

    def toggle_analyze(self):
        """Toggle analyze mode on/off. Only allowed when not gaming."""
        if self._is_gaming():
            return
        self.analyze["enabled"] = not self.analyze["enabled"]
        if self.analyze["enabled"]:
            self._start_analysis()
        else:
            self._stop_analysis()
            self.search_info = {}

    def stop_game(self):
        """Stop the current game. Declares it over so user can analyze."""
        if not self._is_gaming():
            return
        self._paused = False
        if self.ai_thinking:
            # Force stop current search
            for attr in ("white_uci_engine", "black_uci_engine"):
                eng = getattr(self, attr, None)
                if eng is not None:
                    try:
                        eng.stop()
                    except Exception:
                        pass
            self.ai_thinking = False
            self.ai_result = {"move": None, "depth": 0, "ready": False}
        self.game_result = "stopped"
        self._game_started = False

    def _is_gaming(self):
        """True when a game was explicitly started and not yet finished/stopped."""
        return self._game_started and self.game_result is None

    def undo_move(self):
        if not self._undo_stack:
            return
        # Stop AI if thinking
        if self.ai_thinking:
            for attr in ("white_uci_engine", "black_uci_engine"):
                eng = getattr(self, attr, None)
                if eng is not None:
                    try:
                        eng.stop()
                    except Exception:
                        pass
            self.ai_thinking = False
            self.ai_result = {"move": None, "depth": 0, "ready": False}
        if self.analyze["enabled"]:
            self._stop_analysis()
        snap = self._undo_stack.pop()
        self.game_state = snap["game_state"]
        self.uci_moves = snap["uci_moves"]
        self.move_history = snap["move_history"]
        self.score_history = snap["score_history"]
        self.last_move = snap["last_move"]
        self.game_result = None
        self._promotion_dialog = None
        self.search_info = {}
        self.selected_piece = None
        self.legal_moves_for_selected = []
        self._sync_hand_highlight(None)
        if self.analyze["enabled"]:
            self._start_analysis()
        elif self._is_gaming() and not self._paused:
            self._trigger_ai_if_needed()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        log.info("Main loop started")
        try:
            while self._running:
                t0 = time.monotonic()
                self.handle_events()
                t1 = time.monotonic()
                self.update()
                t2 = time.monotonic()
                self.draw()
                t3 = time.monotonic()
                self.clock.tick(_cfg.FPS)
                total = (t3 - t0) * 1000
                if total > 200:
                    log.warning(
                        f"Slow frame: {total:.0f}ms "
                        f"(events={1000*(t1-t0):.0f} "
                        f"update={1000*(t2-t1):.0f} "
                        f"draw={1000*(t3-t2):.0f})"
                    )
        finally:
            self._shutdown_uci_engines()
            pygame.quit()
            try:
                self._tk_root.destroy()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    self._handle_left_click(event.pos)
                elif event.button == 3:  # Right click -- deselect
                    self._deselect_piece()

            elif event.type == pygame.MOUSEWHEEL:
                self.side_panel.set_scroll(-event.y)

            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key)

    def _handle_left_click(self, pos):
        x, y = pos

        # Promotion dialog intercepts all clicks when active
        if self._handle_promotion_click(x, y):
            return

        # Flip icon (upper-left corner of board area)
        if self.board_renderer.hit_flip_icon(x, y):
            _cfg.FLIPPED = not _cfg.FLIPPED
            return

        board_pos = self.board_renderer.screen_to_board(x, y)
        if board_pos is not None:
            if self._is_human_turn():
                self.handle_board_click(board_pos[0], board_pos[1])
            return

        # Check hand piece click (MiniShogi drop support)
        gr = self.board_renderer.game_renderer
        if gr is not None and hasattr(gr, "screen_to_hand") and self._is_human_turn():
            hand_sel = gr.screen_to_hand(x, y, self.game_state)
            if hand_sel is not None:
                self._select_hand_piece(hand_sel)
                return

        action = self.side_panel.handle_click(x, y)
        match action:
            case "reset":
                self.reset()
            case "new_game":
                self.open_new_game_dialog()
            case "settings":
                self.open_settings()
            case "undo":
                self.undo_move()
            case "analyze":
                self.toggle_analyze()
            case "stop":
                if self._is_gaming():
                    self._paused = not self._paused
                    if not self._paused:
                        self._trigger_ai_if_needed()

    def _handle_keydown(self, key):
        if key == pygame.K_n:
            self.open_new_game_dialog()
        elif key == pygame.K_s:
            self.open_settings()
        elif key == pygame.K_ESCAPE:
            if self.selected_piece is not None:
                self._deselect_piece()
            else:
                self._running = False
        elif key == pygame.K_SPACE:
            if self._is_gaming():
                self._paused = not self._paused
        elif key == pygame.K_z:
            self.undo_move()
        elif key == pygame.K_a:
            self.toggle_analyze()
        elif key == pygame.K_f:
            _cfg.FLIPPED = not _cfg.FLIPPED
        elif key == pygame.K_q:
            self.stop_game()

    # ------------------------------------------------------------------
    # Board interaction
    # ------------------------------------------------------------------

    def _is_human_turn(self):
        if self.ai_thinking:
            return False
        # Not gaming (stopped, game over, or no engines) → always allow clicks
        if not self._is_gaming():
            return True
        # During a game, only human side can click
        player = self.game_state.player
        side = self.white if player == 0 else self.black
        return side["engine"] is None

    def handle_board_click(self, row, col):
        player = self.game_state.player

        # Get the clicked piece; board layout differs per game
        try:
            clicked_piece = self.game_state.board[player][row][col]
        except (TypeError, IndexError):
            clicked_piece = _cfg.EMPTY

        if self.selected_piece is None:
            # For placement games, check if any legal move targets (row,col)
            placement_move = None
            for m in self.game_state.legal_actions:
                if m[1] == (row, col):
                    placement_move = m
                    break
            if placement_move is not None and clicked_piece == _cfg.EMPTY:
                self.execute_move(placement_move)
            elif clicked_piece != _cfg.EMPTY:
                self._select_piece(row, col)
        else:
            target_move = self._find_legal_move(row, col)
            if target_move is not None:
                self.execute_move(target_move)
            elif clicked_piece != _cfg.EMPTY and (row, col) != self.selected_piece:
                self._select_piece(row, col)
            else:
                self._deselect_piece()

    def _select_piece(self, row, col):
        self.selected_piece = (row, col)
        self.legal_moves_for_selected = [
            m for m in self.game_state.legal_actions if m[0] == (row, col)
        ]
        self._sync_hand_highlight(None)

    def _select_hand_piece(self, hand_key):
        """Select a hand piece for dropping.

        Args:
            hand_key: (BOARD_SIZE, piece_type) tuple from the renderer.
        """
        self.selected_piece = hand_key
        self.legal_moves_for_selected = [
            m for m in self.game_state.legal_actions if m[0] == hand_key
        ]
        self._sync_hand_highlight(hand_key)

    def _deselect_piece(self):
        """Clear selection and hand highlight."""
        self.selected_piece = None
        self.legal_moves_for_selected = []
        self._sync_hand_highlight(None)

    def _sync_hand_highlight(self, hand_key):
        """Update the renderer's hand highlight if it supports it."""
        gr = self.board_renderer.game_renderer
        if gr is not None and hasattr(gr, "set_selected_hand"):
            gr.set_selected_hand(hand_key)

    def _find_legal_move(self, dest_row, dest_col):
        """Find a legal move to (dest_row, dest_col) from the current selection.

        If both promotion and non-promotion moves exist, show a promotion
        choice dialog instead of auto-promoting.

        For chess-style promotion (4 choices: Q/R/B/N), show a piece
        selection dialog.
        """
        bh = _cfg.BOARD_H
        matches = []
        for move in self.legal_moves_for_selected:
            (_, _), (tr, tc) = move
            actual_tr = tr % bh if tr >= bh else tr
            if actual_tr == dest_row and tc == dest_col:
                matches.append(move)

        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]

        # Multiple matches: separate promotion and non-promotion moves
        promo_moves = []
        normal_move = None
        for m in matches:
            if m[1][0] >= bh:
                promo_moves.append(m)
            else:
                normal_move = m

        if len(promo_moves) >= 4:
            # Chess-style promotion: 4 promotion choices (Q/R/B/N)
            self._show_chess_promotion_dialog(dest_row, dest_col, promo_moves)
            return None  # dialog handles it

        if promo_moves and normal_move:
            # Shogi-style promotion: promote or keep
            self._show_promotion_dialog(dest_row, dest_col, promo_moves[0], normal_move)
            return None  # don't execute yet — dialog handles it
        if promo_moves:
            return promo_moves[0]
        return normal_move

    # ------------------------------------------------------------------
    # Move execution
    # ------------------------------------------------------------------

    def execute_move(self, move):
        log.info(f"execute_move: {move}")

        # Clear "stopped" state so user can keep exploring
        if self.game_result == "stopped":
            self.game_result = None

        # Save undo snapshot (always — allows undo during games too)
        self._undo_stack.append(
            {
                "game_state": self.game_state,
                "uci_moves": list(self.uci_moves),
                "move_history": list(self.move_history),
                "score_history": list(self.score_history),
                "last_move": self.last_move,
            }
        )

        mover = self.game_state.player
        prefix = "W" if mover == 0 else "B"
        step = self.game_state.step
        move_str = f"{step}. {prefix}: {self._format_move(move)}"

        new_state = self.game_state.next_state(move)
        self.game_state = new_state

        self.move_history.append(move_str)
        self.last_move = move
        self.uci_moves.append(UBGIEngine.move_to_uci(move))
        # Determine score source
        score_cp = self.search_info.get("score_cp")
        if self.analyze["enabled"]:
            source = "analyze"
        elif mover == 0 and self.white["engine"] is not None:
            source = "p0"
        elif mover == 1 and self.black["engine"] is not None:
            source = "p1"
        else:
            source = "human"
        self.score_history.append((mover, score_cp, source))

        self.side_panel._scroll_offset = max(0, len(self.move_history))
        self.selected_piece = None
        self.legal_moves_for_selected = []
        self._sync_hand_highlight(None)

        with log.timed("check_game_over"):
            result, winner = self.game_state.check_game_over()
        if result is not None:
            log.info(f"game over: {result} winner={winner}")
        if result in ("win", "checkmate", "perpetual_check", "stalemate_loss"):
            if result == "checkmate":
                self.game_result = "p0_checkmate" if winner == 0 else "p1_checkmate"
            elif result == "perpetual_check":
                self.game_result = (
                    "p0_perpetual_check" if winner == 0 else "p1_perpetual_check"
                )
            else:
                self.game_result = "p0_wins" if winner == 0 else "p1_wins"
            return
        if result == "stalemate":
            self.game_result = "stalemate_draw"
            return
        if result == "draw":
            self.game_result = "draw"
            return

        if self.analyze["enabled"] and not self._is_gaming():
            self._start_analysis()  # sends position+go, engine supersedes old search
        elif self._is_gaming():
            self._trigger_ai_if_needed()

    def _trigger_ai_if_needed(self):
        if (
            not self._game_started
            or self.game_result is not None
            or self.ai_thinking
            or self._paused
        ):
            return
        player = self.game_state.player
        side = self.white if player == 0 else self.black
        if side["engine"] is None:
            return  # human's turn
        self.trigger_ai_move()

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self):
        # Force-kill engine if it exceeds the timeout (time-based search only)
        if self.ai_thinking and not self.ai_result.get("ready"):
            player = self.game_state.player
            side = self.white if player == 0 else self.black
            using_fixed_depth = side.get("depth", 0) > 0
            if not using_fixed_depth:
                elapsed = time.time() - getattr(self, "_ai_start_time", 0)
                kill_after = self.time_limit + 2.0
                if elapsed > kill_after:
                    self._force_kill_ai_engine()

        if self.ai_result.get("ready"):
            move = self.ai_result["move"]
            depth = self.ai_result["depth"]
            self.ai_result = {"move": None, "depth": 0, "ready": False}
            self.ai_thinking = False
            log.info(f"AI result ready: move={move} depth={depth}")

            # Discard stale results if game was reset/stopped
            if not self._game_started:
                return

            if move is not None and move in self.game_state.legal_actions:
                self.ai_depth = depth
                t0 = time.monotonic()
                self.execute_move(move)
                dt = (time.monotonic() - t0) * 1000
                log.info(f"execute_move done: {dt:.1f}ms")
                self._last_ai_time = time.time()
            else:
                log.info(f"AI move invalid or None: {move}")
                loser = self.game_state.player
                self.game_result = "p1_wins" if loser == 0 else "p0_wins"
            return

        # AI vs AI auto-trigger
        if (
            self.mode == "ai_vs_ai"
            and self.game_result is None
            and not self.ai_thinking
            and not self._paused
        ):
            elapsed = time.time() - self._last_ai_time
            if elapsed >= _cfg.AI_VS_AI_DELAY:
                self._trigger_ai_if_needed()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self):
        self.screen.fill(_cfg.COLOR_BG)

        # Only show PV arrows in analyze mode, NOT during gaming
        pv = None
        pv_multi = None
        if self.analyze["enabled"] and not self._is_gaming():
            pv = self.search_info.get("pv")
            pv_multi_raw = self.search_info.get("pv_multi")
            if pv_multi_raw:
                # Always use pv_multi (handles drops correctly)
                pv_multi = {}
                for idx, moves in pv_multi_raw.items():
                    pv_multi[idx] = moves[: self.pv_display_steps] if moves else []
            # Also truncate main PV as fallback
            if pv:
                pv = pv[: self.pv_display_steps]
        self.board_renderer.draw(
            self.game_state,
            selected=self.selected_piece,
            legal_moves=self.legal_moves_for_selected,
            last_move=self.last_move,
            pv_arrows=pv,
            pv_multi=pv_multi,
        )

        self.side_panel.draw(
            self.game_state,
            ai_thinking=self.ai_thinking,
            game_result=self.game_result,
            ai_depth=self.ai_depth,
            mode=self.mode,
            time_limit=self.time_limit,
            search_info=self.search_info,
            paused=self._paused,
            analyze_enabled=self.analyze["enabled"],
            gaming=self._is_gaming(),
            player_labels=self._player_labels,
            player_colors=self._player_colors,
        )

        self.side_panel.draw_bottom(
            score_cp=self.search_info.get("score_cp"),
            score_history=self.score_history,
            move_history=self.move_history,
            player_colors=self._player_colors,
        )

        # Draw promotion dialog overlay if active
        self._draw_promotion_dialog()

        pygame.display.flip()

    # ------------------------------------------------------------------
    # New game / settings
    # ------------------------------------------------------------------

    def reset(self):
        """Reset to initial position, clear history, close engines."""
        # Stop any in-progress search first
        for attr in ("white_uci_engine", "black_uci_engine"):
            eng = getattr(self, attr, None)
            if eng is not None:
                try:
                    eng.stop()
                except Exception:
                    pass
        self._stop_analysis()
        self._kill_analyze_engine()
        # Now quit engines
        for attr in ("white_uci_engine", "black_uci_engine"):
            self._quit_engine(attr)

        self.game_state = self._state_class.initial()
        self.selected_piece = None
        self.legal_moves_for_selected = []
        self.last_move = None
        self._promotion_dialog = None
        self.move_history = []
        self.score_history = []
        self.game_result = None
        self.ai_thinking = False
        self.ai_result = {"move": None, "depth": 0, "ready": False}
        self.ai_depth = None
        self.uci_moves = []
        self.search_info = {}
        self._last_ai_time = 0.0
        self._paused = False
        self._undo_stack = []
        self._game_started = False

    def new_game(self):
        """Reset + start game (trigger AI if needed)."""
        self.reset()
        self._game_started = True
        self._trigger_ai_if_needed()


def main():
    parser = argparse.ArgumentParser(description="UBGI GUI")
    parser.add_argument(
        "--game",
        default="minichess",
        choices=["minichess"],
        help="Game type: minichess (default: minichess)",
    )
    args = parser.parse_args()

    app = GameApp(game_name=args.game)
    app.run()


if __name__ == "__main__":
    main()
