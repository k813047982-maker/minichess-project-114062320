"""MiniChess game module for CLI -- board display, human input, game logic."""

import sys

try:
    from gui.games.minichess_engine import MiniChessState, format_move
    from gui.ubgi_client import UBGIEngine
    from gui.config import (
        BOARD_H,
        BOARD_W,
        MAX_STEP,
        PIECE_UNICODE,
        COL_LABELS,
        ROW_LABELS,
    )
except ImportError:
    raise ImportError(
        "MiniChess CLI requires gui.games.minichess_engine and gui.config. "
        "Make sure the gui package is on sys.path."
    )


def print_board(state, game_ctx):
    """Print MiniChess board with Unicode chess pieces from White's perspective."""
    print()
    print("    " + "  ".join(game_ctx["col_labels"]))
    for r in range(game_ctx["board_h"]):
        rank_label = game_ctx["row_labels"][r]
        row_chars = []
        for c in range(game_ctx["board_w"]):
            w_piece = state.board[0][r][c]
            b_piece = state.board[1][r][c]
            if w_piece:
                row_chars.append(game_ctx["piece_unicode"][0][w_piece])
            elif b_piece:
                row_chars.append(game_ctx["piece_unicode"][1][b_piece])
            else:
                row_chars.append(".")
        print(f" {rank_label}  " + "  ".join(row_chars) + f"  {rank_label}")
    print("    " + "  ".join(game_ctx["col_labels"]))
    print()


def get_human_move(state, game_ctx):
    """Prompt human player for a MiniChess move via numbered list or algebraic notation."""
    legal = state.legal_actions
    player_name = "White" if state.player == 0 else "Black"

    print(f"  {player_name}'s legal moves:")
    entries = [
        f"{i + 1:>3}. {game_ctx['format_move'](mv)}" for i, mv in enumerate(legal)
    ]
    cols = 4
    for i in range(0, len(entries), cols):
        row = entries[i : i + cols]
        print("  " + "    ".join(f"{e:<16}" for e in row))
    print()

    while True:
        try:
            raw = input(f"  Enter move number (or algebraic e.g. b2b3): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGame aborted.")
            sys.exit(0)

        if not raw:
            continue

        try:
            num = int(raw)
            if 1 <= num <= len(legal):
                return legal[num - 1]
            print(f"  Invalid number. Enter 1-{len(legal)}.")
            continue
        except ValueError:
            pass

        uci_str = raw.replace("-", "").replace(">", "").lower()
        if len(uci_str) == 4:
            try:
                move = game_ctx["uci_to_move"](uci_str)
                if move in legal:
                    return move
                print(f"  '{raw}' is not a legal move.")
                continue
            except (ValueError, IndexError, KeyError):
                pass

        print(
            f"  Could not parse '{raw}'. Enter a move number or algebraic (e.g. b2b3)."
        )


def check_game_over(state):
    """Check if the game is over. Returns (result, winner).

    result: 'win', 'draw', 'no_moves', or None (game continues).
    winner: 0 (White) or 1 (Black) for 'win'/'no_moves', None otherwise.
    """
    result, winner = state.check_game_over()
    if result == "win":
        return ("win", winner)
    elif result == "draw":
        return ("draw", None)

    if not state.legal_actions:
        # Side to move has no legal moves -- they lose
        return ("no_moves", 1 - state.player)

    return (None, None)


def apply_move(state, uci_str, game_ctx):
    """Apply a UCI move string to the state. Returns (new_state, move_tuple)."""
    move = game_ctx["uci_to_move"](uci_str)
    return state.next_state(move), move


def get_context():
    """Return the game context dict for MiniChess."""
    ctx = {
        "name": "minichess",
        "state_class": MiniChessState,
        "format_move": format_move,
        "uci_to_move": UBGIEngine.uci_to_move,
        "move_to_uci": UBGIEngine.move_to_uci,
        "board_h": BOARD_H,
        "board_w": BOARD_W,
        "max_step": MAX_STEP,
        "piece_unicode": PIECE_UNICODE,
        "col_labels": COL_LABELS,
        "row_labels": ROW_LABELS,
        "print_board": print_board,
        "get_human_move": get_human_move,
        "check_game_over": check_game_over,
        "apply_move": apply_move,
    }
    return ctx
