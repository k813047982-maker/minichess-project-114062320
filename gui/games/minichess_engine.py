"""MiniChess game engine -- faithful Python port of the C++ game state.

Provides game state management, legal move generation, AI subprocess
communication, and action file parsing.
"""

try:
    import gui.config as cfg
except ImportError:
    import config as cfg

PLAYER_LABELS = {0: "White", 1: "Black"}
PLAYER_COLORS = {0: (255, 255, 255), 1: (30, 30, 30)}

# ---------------------------------------------------------------------------
# Move tables (exact port from state.cpp)
# ---------------------------------------------------------------------------

# Sliding directions: indices 0-3 = rook, 4-7 = bishop, 0-7 = queen
# Each direction has up to 7 steps (max board dimension).
_move_table_rook_bishop = [
    [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7)],
    [(0, -1), (0, -2), (0, -3), (0, -4), (0, -5), (0, -6), (0, -7)],
    [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0)],
    [(-1, 0), (-2, 0), (-3, 0), (-4, 0), (-5, 0), (-6, 0), (-7, 0)],
    [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7)],
    [(1, -1), (2, -2), (3, -3), (4, -4), (5, -5), (6, -6), (7, -7)],
    [(-1, 1), (-2, 2), (-3, 3), (-4, 4), (-5, 5), (-6, 6), (-7, 7)],
    [(-1, -1), (-2, -2), (-3, -3), (-4, -4), (-5, -5), (-6, -6), (-7, -7)],
]

_move_table_knight = [
    (1, 2),
    (1, -2),
    (-1, 2),
    (-1, -2),
    (2, 1),
    (2, -1),
    (-2, 1),
    (-2, -1),
]

_move_table_king = [
    (1, 0),
    (0, 1),
    (-1, 0),
    (0, -1),
    (1, 1),
    (1, -1),
    (-1, 1),
    (-1, -1),
]

# Material values for MAX_STEP game-over (matching main.cpp material_table)
_material_table = [0, 2, 6, 7, 8, 20, 100]


# ---------------------------------------------------------------------------
# Initial board layout (matching C++ Board default)
# ---------------------------------------------------------------------------


def _make_initial_board():
    """Return the starting position as board[2][BOARD_H][BOARD_W]."""
    board = [[[0] * cfg.BOARD_W for _ in range(cfg.BOARD_H)] for _ in range(2)]
    # White (player 0)
    # Row 4: pawns
    for c in range(cfg.BOARD_W):
        board[0][4][c] = cfg.PAWN
    # Row 5: rook, knight, bishop, queen, king
    board[0][5][0] = cfg.ROOK
    board[0][5][1] = cfg.KNIGHT
    board[0][5][2] = cfg.BISHOP
    board[0][5][3] = cfg.QUEEN
    board[0][5][4] = cfg.KING

    # Black (player 1)
    # Row 1: pawns
    for c in range(cfg.BOARD_W):
        board[1][1][c] = cfg.PAWN
    # Row 0: king, queen, bishop, knight, rook
    board[1][0][0] = cfg.KING
    board[1][0][1] = cfg.QUEEN
    board[1][0][2] = cfg.BISHOP
    board[1][0][3] = cfg.KNIGHT
    board[1][0][4] = cfg.ROOK

    return board


def _deep_copy_board(board):
    """Deep-copy a board[2][BOARD_H][BOARD_W] list."""
    return [[row[:] for row in player_board] for player_board in board]


# ---------------------------------------------------------------------------
# MiniChessState
# ---------------------------------------------------------------------------


class MiniChessState:
    """Game state matching the C++ State class."""

    def __init__(self, board=None, player=0, step=1):
        """Create a state.

        Args:
            board: [2][BOARD_H][BOARD_W] list of ints (0-6).
                   If *None*, the initial position is used.
            player: 0 (white) or 1 (black).
            step: current move number (1-based).
        """
        if board is None:
            self.board = _make_initial_board()
        else:
            self.board = _deep_copy_board(board)
        self.player = player
        self.step = step
        # game_state mirrors the C++ enum: "none", "win", "draw", "unknown"
        self.game_state = "unknown"
        self.legal_actions = []
        self.hash_counts = {}  # position_key -> count for repetition detection

    # ------------------------------------------------------------------ #
    # Legal move generation (port of get_legal_actions_naive)
    # ------------------------------------------------------------------ #

    def get_legal_actions(self):
        """Populate *self.legal_actions* and set *self.game_state*.

        Faithfully ports ``State::get_legal_actions_naive`` from state.cpp,
        preserving the same iteration order and early-return on king capture.
        """
        self.game_state = "none"
        all_actions = []
        self_board = self.board[self.player]
        oppn_board = self.board[1 - self.player]

        for i in range(cfg.BOARD_H):
            for j in range(cfg.BOARD_W):
                now_piece = self_board[i][j]
                if not now_piece:
                    continue

                if now_piece == 1:  # Pawn
                    if self.player and i < cfg.BOARD_H - 1:
                        # Black pawn -- moves DOWN (row increases)
                        if not oppn_board[i + 1][j] and not self_board[i + 1][j]:
                            all_actions.append(((i, j), (i + 1, j)))
                        if j < cfg.BOARD_W - 1:
                            oppn_piece = oppn_board[i + 1][j + 1]
                            if oppn_piece > 0:
                                all_actions.append(((i, j), (i + 1, j + 1)))
                                if oppn_piece == 6:
                                    self.game_state = "win"
                                    self.legal_actions = all_actions
                                    return
                        if j > 0:
                            oppn_piece = oppn_board[i + 1][j - 1]
                            if oppn_piece > 0:
                                all_actions.append(((i, j), (i + 1, j - 1)))
                                if oppn_piece == 6:
                                    self.game_state = "win"
                                    self.legal_actions = all_actions
                                    return

                    elif not self.player and i > 0:
                        # White pawn -- moves UP (row decreases)
                        if not oppn_board[i - 1][j] and not self_board[i - 1][j]:
                            all_actions.append(((i, j), (i - 1, j)))
                        if j < cfg.BOARD_W - 1:
                            oppn_piece = oppn_board[i - 1][j + 1]
                            if oppn_piece > 0:
                                all_actions.append(((i, j), (i - 1, j + 1)))
                                if oppn_piece == 6:
                                    self.game_state = "win"
                                    self.legal_actions = all_actions
                                    return
                        if j > 0:
                            oppn_piece = oppn_board[i - 1][j - 1]
                            if oppn_piece > 0:
                                all_actions.append(((i, j), (i - 1, j - 1)))
                                if oppn_piece == 6:
                                    self.game_state = "win"
                                    self.legal_actions = all_actions
                                    return

                elif now_piece in (2, 4, 5):  # Rook / Bishop / Queen
                    if now_piece == 2:
                        st, end = 0, 4
                    elif now_piece == 4:
                        st, end = 4, 8
                    else:  # queen
                        st, end = 0, 8

                    for part in range(st, end):
                        move_list = _move_table_rook_bishop[part]
                        for k in range(max(cfg.BOARD_H, cfg.BOARD_W)):
                            dr, dc = move_list[k]
                            pr, pc = dr + i, dc + j

                            if (
                                pr >= cfg.BOARD_H
                                or pr < 0
                                or pc >= cfg.BOARD_W
                                or pc < 0
                            ):
                                break
                            if self_board[pr][pc]:
                                break

                            all_actions.append(((i, j), (pr, pc)))

                            oppn_piece = oppn_board[pr][pc]
                            if oppn_piece:
                                if oppn_piece == 6:
                                    self.game_state = "win"
                                    self.legal_actions = all_actions
                                    return
                                else:
                                    break

                elif now_piece == 3:  # Knight
                    for dr, dc in _move_table_knight:
                        x = dr + i
                        y = dc + j

                        if x >= cfg.BOARD_H or x < 0 or y >= cfg.BOARD_W or y < 0:
                            continue
                        if self_board[x][y]:
                            continue
                        all_actions.append(((i, j), (x, y)))

                        oppn_piece = oppn_board[x][y]
                        if oppn_piece == 6:
                            self.game_state = "win"
                            self.legal_actions = all_actions
                            return

                elif now_piece == 6:  # King
                    for dr, dc in _move_table_king:
                        pr, pc = dr + i, dc + j

                        if pr >= cfg.BOARD_H or pr < 0 or pc >= cfg.BOARD_W or pc < 0:
                            continue
                        if self_board[pr][pc]:
                            continue

                        all_actions.append(((i, j), (pr, pc)))

                        oppn_piece = oppn_board[pr][pc]
                        if oppn_piece == 6:
                            self.game_state = "win"
                            self.legal_actions = all_actions
                            return

        self.legal_actions = all_actions

    def position_key(self):
        """Hashable key for the current board + side-to-move."""
        return (
            self.player,
            tuple(
                self.board[p][r][c]
                for p in range(2)
                for r in range(cfg.BOARD_H)
                for c in range(cfg.BOARD_W)
            ),
        )

    # ------------------------------------------------------------------ #
    # Next state
    # ------------------------------------------------------------------ #

    def next_state(self, move):
        """Return a **new** MiniChessState after applying *move*.

        Handles pawn promotion (pawn reaching row 0 or row BOARD_H-1 becomes
        queen), captures, player switch, and step increment.  Mirrors
        ``State::next_state`` from state.cpp.
        """
        frm, to = move
        fr, fc = frm
        tr, tc = to

        new_board = _deep_copy_board(self.board)

        moved = new_board[self.player][fr][fc]

        # Promotion: pawn reaching the far rank becomes queen
        if moved == cfg.PAWN and (tr == cfg.BOARD_H - 1 or tr == 0):
            moved = cfg.QUEEN

        # Capture: clear opponent piece on destination
        if new_board[1 - self.player][tr][tc]:
            new_board[1 - self.player][tr][tc] = cfg.EMPTY

        # Move the piece
        new_board[self.player][fr][fc] = cfg.EMPTY
        new_board[self.player][tr][tc] = moved

        ns = MiniChessState(new_board, 1 - self.player, self.step + 1)
        ns.hash_counts = dict(self.hash_counts)
        key = self.position_key()
        ns.hash_counts[key] = ns.hash_counts.get(key, 0) + 1

        if self.game_state != "win":
            ns.get_legal_actions()

        return ns

    # ------------------------------------------------------------------ #
    # Game-over by MAX_STEP (material count, matching main.cpp)
    # ------------------------------------------------------------------ #

    def check_game_over(self):
        """Check if the game ended due to king capture, checkmate, or MAX_STEP.

        Returns:
            ("checkmate", winner_player) -- in check with no escape.
            ("win", winner_player) -- if king can be captured.
            ("draw", None) -- if material is equal after MAX_STEP.
            (None, None) -- game is not over.
        """
        if self.game_state == "win":
            # The current player can capture the king => current player wins
            return ("win", self.player)

        # 4-fold repetition → draw
        key = self.position_key()
        if self.hash_counts.get(key, 0) + 1 >= 4:
            return ("draw", None)

        if self.step > cfg.MAX_STEP:
            white_material = 0
            black_material = 0
            for i in range(cfg.BOARD_H):
                for j in range(cfg.BOARD_W):
                    piece = self.board[0][i][j]
                    if piece:
                        white_material += _material_table[piece]
                    piece = self.board[1][i][j]
                    if piece:
                        black_material += _material_table[piece]

            if white_material < black_material:
                return ("win", 1)
            elif white_material > black_material:
                return ("win", 0)
            else:
                return ("draw", None)

        # Checkmate: current player is in check and every move
        # still leaves king capturable.
        probe = MiniChessState(self.board, 1 - self.player, self.step)
        probe.get_legal_actions()
        if probe.game_state == "win":  # we are in check
            for move in self.legal_actions:
                child = self.next_state(move)
                if child.game_state != "win":
                    return (None, None)  # at least one escape
            return ("checkmate", 1 - self.player)

        return (None, None)

    # ------------------------------------------------------------------ #
    # State encoding (for communicating with C++ player exe)
    # ------------------------------------------------------------------ #

    def encode_state(self):
        """Encode state in the exact format the C++ player exe expects.

        Format::

            player
            white_board (6 rows of 5 space-separated ints)
            <blank line>
            black_board (6 rows of 5 space-separated ints)
            <blank line>
        """
        lines = []
        lines.append(str(self.player))
        for pl in range(2):
            for i in range(cfg.BOARD_H):
                lines.append(
                    " ".join(str(self.board[pl][i][j]) for j in range(cfg.BOARD_W))
                    + " "
                )
            lines.append("")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ #
    # Deep copy
    # ------------------------------------------------------------------ #

    @property
    def current_player(self):
        return self.player

    def copy(self):
        """Return a deep copy of this state."""
        s = MiniChessState.__new__(MiniChessState)
        s.board = _deep_copy_board(self.board)
        s.player = self.player
        s.step = self.step
        s.game_state = self.game_state
        s.legal_actions = list(self.legal_actions)
        s.hash_counts = dict(self.hash_counts)
        return s

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #

    @staticmethod
    def initial():
        """Return the starting-position state with legal actions computed."""
        s = MiniChessState()
        s.get_legal_actions()
        return s

    # ------------------------------------------------------------------ #
    # Convenience / debugging
    # ------------------------------------------------------------------ #

    def __repr__(self):
        return (
            f"MiniChessState(player={self.player}, step={self.step}, "
            f"game_state={self.game_state!r}, "
            f"legal_actions={len(self.legal_actions)})"
        )


# ---------------------------------------------------------------------------
# Move formatting
# ---------------------------------------------------------------------------


def format_move(move):
    """Format *move* as an algebraic string like ``'B2->B3'``.

    Uses *COL_LABELS* and *ROW_LABELS* from config.
    """
    (fr, fc), (tr, tc) = move
    return (
        f"{cfg.COL_LABELS[fc]}{cfg.ROW_LABELS[fr]}->"
        f"{cfg.COL_LABELS[tc]}{cfg.ROW_LABELS[tr]}"
    )
