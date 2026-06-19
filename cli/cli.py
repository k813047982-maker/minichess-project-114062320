"""UBGI CLI - Run MiniChess AI vs AI or Human vs AI matches."""

import argparse
import os
import subprocess
import sys
import time

from cli.games.minichess import get_context as _minichess_ctx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Game-agnostic UCI info parsing (no game-specific imports needed)
# ---------------------------------------------------------------------------

try:
    from gui.ubgi_client import UBGIEngine as _UBGIEngineStatic

    _parse_info = _UBGIEngineStatic.parse_info
except ImportError:
    _parse_info = lambda line: {}  # fallback: no info parsing

# ---------------------------------------------------------------------------
# Game families -- reduce repeated set membership checks
# ---------------------------------------------------------------------------

_CHESS_FAMILY = frozenset({"minichess"})
_SHOGI_FAMILY = frozenset()
_BOARD_GAMES = _CHESS_FAMILY | _SHOGI_FAMILY  # games with .player / .legal_actions

# ---------------------------------------------------------------------------
# Game context -- populated once by _init_game(), replaces per-module globals
# ---------------------------------------------------------------------------

_game_ctx: dict = {}  # populated by _init_game()


def _init_game(game_name: str, board_size: int | None = None) -> None:
    """Initialize game-specific context. Called once from main()."""
    _game_ctx.update(_minichess_ctx())


ALGO_CHOICES = ["minimax", "random"]

# ---------------------------------------------------------------------------
# Board display (game-specific)
# ---------------------------------------------------------------------------


def print_board(state) -> None:
    """Dispatch to the appropriate board printer via _game_ctx."""
    printer = _game_ctx.get("print_board")
    if printer is not None:
        printer(state, _game_ctx)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_nodes(n) -> str:
    """Format node count: 1234 -> '1.2K', 1234567 -> '1.2M'."""
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def format_search_info(info: dict | None) -> str:
    """Format search info dict for display."""
    if not info:
        return ""

    parts: list[str] = []

    depth = info.get("depth")
    seldepth = info.get("seldepth")
    if depth is not None:
        d = f"depth={depth}/{seldepth}" if seldepth is not None else f"depth={depth}"
        parts.append(d)

    score_cp = info.get("score_cp")
    if score_cp is not None:
        parts.append(f"score={score_cp / 100.0:+.2f}")
    elif info.get("score_mate") is not None:
        parts.append(f"mate={info['score_mate']}")

    nodes = info.get("nodes")
    if nodes is not None:
        parts.append(f"nodes={format_nodes(nodes)}")

    nps = info.get("nps")
    if nps is not None:
        parts.append(f"{format_nodes(nps)} nps")
    elif nodes is not None and info.get("time") and info["time"] > 0:
        calc_nps = int(nodes / (info["time"] / 1000.0))
        parts.append(f"{format_nodes(calc_nps)} nps")

    elapsed = info.get("time")
    if elapsed is not None:
        parts.append(f"{elapsed}ms")

    return ", ".join(parts)


def format_move_display(move_or_uci, state=None) -> str:
    """Format a move for display, adapting to the active game type.

    For minichess/chess variants: uses the algebraic format_move (e.g. 'B2->B3').
    For connect6: shows the coordinate (e.g. 'E5').
    For generic: shows the raw UCI string.
    """
    game_name = _game_ctx.get("name", "generic")

    match game_name:
        case n if n in _BOARD_GAMES and not isinstance(move_or_uci, str):
            return _game_ctx["format_move"](move_or_uci)
        case n if n in _SHOGI_FAMILY and isinstance(move_or_uci, str):
            return move_or_uci.upper()
        case "connect6" if isinstance(move_or_uci, str):
            return move_or_uci.upper()
        case _:
            return move_or_uci if isinstance(move_or_uci, str) else str(move_or_uci)


# ---------------------------------------------------------------------------
# Engine communication (game-agnostic)
# ---------------------------------------------------------------------------


def get_engine_move(
    engine_path: str,
    algo: str,
    params: list[str] | None,
    uci_moves: list[str],
    time_limit: int,
    depth: int = 0,
) -> tuple[str | None, dict | None]:
    """Spawn engine, send UBGI/UCI commands, kill after timeout, parse output.

    Returns (bestmove_uci_str, last_info_dict) or (None, None).
    """
    kwargs = {
        "args": [os.path.abspath(engine_path)],
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(**kwargs)
    except OSError:
        return None, None

    def send(cmd):
        proc.stdin.write((cmd + "\n").encode())
        proc.stdin.flush()

    # Setup phase -- blocking communicate for handshake
    setup_cmds = ["ubgi"]
    setup_cmds.append(f"setoption name Algorithm value {algo}")
    for p in params or []:
        if "=" in p:
            k, v = p.split("=", 1)
            setup_cmds.append(f"setoption name {k} value {v}")
    if uci_moves:
        setup_cmds.append("position startpos moves " + " ".join(uci_moves))
    else:
        setup_cmds.append("position startpos")
    setup_cmds.append("isready")

    for cmd in setup_cmds:
        send(cmd)

    # Wait for readyok or ubgiok (engine is ready to search)
    while True:
        raw = proc.stdout.readline()
        if not raw:
            break
        line_str = raw.decode("utf-8", errors="replace").strip()
        if line_str in ("readyok", "ubgiok", "uciok"):
            break

    # Now send go -- timer starts HERE
    bestmove = None
    last_info = None

    if depth > 0:
        send(f"go depth {depth}")
        # Wait for engine to finish (no time limit for depth search)
        while True:
            raw = proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith("info ") and "depth" in line:
                last_info = _parse_info(line)
            elif line.startswith("bestmove"):
                parts = line.split()
                bestmove = parts[1] if len(parts) >= 2 else None
                break
        proc.kill()
        return bestmove, last_info
    else:
        send(f"go movetime {time_limit}")
        # Wait exactly the time limit, then kill and read
        time.sleep(time_limit / 1000.0)
        proc.kill()
        stdout = proc.stdout.read()

    # Parse killed output -- iterate from last to first for robustness
    # (last line may be truncated by kill)
    lines = stdout.decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        line = line.strip()
        if bestmove is None and line.startswith("bestmove"):
            parts = line.split()
            if len(parts) >= 2:
                bestmove = parts[1]
        if last_info is None and line.startswith("info ") and "depth" in line:
            parsed = _parse_info(line)
            if parsed and "depth" in parsed:
                last_info = parsed
        if bestmove is not None and last_info is not None:
            break

    # If no bestmove, extract from last info (pv or currmove)
    if bestmove is None and last_info:
        pv = last_info.get("pv")
        if pv and len(pv) > 0:
            bestmove = pv[0]
        elif last_info.get("currmove"):
            bestmove = last_info["currmove"]

    # Debug: dump raw output if no move found
    if bestmove is None:
        print(f"  [DEBUG] No bestmove found. stdout lines={len(lines)}")
        for i, l in enumerate(lines[-10:]):
            print(f"  [DEBUG]   {i}: {l.strip()}")

    return bestmove, last_info


# ---------------------------------------------------------------------------
# Human move input (generic fallback)
# ---------------------------------------------------------------------------


def get_human_move_generic(uci_moves: list[str]) -> str:
    """Prompt human player for a raw UCI move string (generic game)."""
    side_name = "Player 1" if len(uci_moves) % 2 == 0 else "Player 2"
    print(f"  {side_name}'s turn.")

    while True:
        try:
            raw = input("  Enter move (UCI format): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGame aborted.")
            sys.exit(0)

        if raw:
            return raw


# ---------------------------------------------------------------------------
# Game loop helpers
# ---------------------------------------------------------------------------


def _init_game_state(game_name: str):
    """Create initial game state from context, or None for generic."""
    if game_name == "generic":
        return None
    if "make_state" in _game_ctx:
        return _game_ctx["make_state"](_game_ctx.get("board_size", 15))
    return _game_ctx["state_class"].initial()


def _side_labels(game_name: str) -> tuple[str, str]:
    """Return (first_player_label, second_player_label) for the game."""
    if game_name in _SHOGI_FAMILY:
        return ("Sente", "Gote")
    return ("White", "Black")


def _check_game_over(state, game_name: str, verbose: bool) -> str | None:
    """Check if the game is over. Returns 'white', 'black', 'draw', or None."""
    if game_name == "generic":
        return None

    check_fn = _game_ctx.get("check_game_over")
    result, winner = check_fn(state)
    first_label, second_label = _side_labels(game_name)

    if result in ("win", "checkmate", "perpetual_check", "stalemate_loss"):
        if game_name == "connect6":
            winner_str = "Player 1 (X)" if winner == 1 else "Player 2 (O)"
            color = "white" if winner == 1 else "black"
        else:
            winner_str = first_label if winner == 0 else second_label
            color = "white" if winner == 0 else "black"
        if verbose:
            match result:
                case "checkmate":
                    print(f"  >> Checkmate! {winner_str} wins!")
                case "perpetual_check":
                    print(f"  >> Perpetual check! {winner_str} wins!")
                case "stalemate_loss":
                    loser_str = first_label if winner == 1 else second_label
                    print(f"  >> {loser_str} has no legal moves! {winner_str} wins!")
                case _:
                    print(f"  >> {winner_str} wins!")
        return color

    if result == "draw":
        if verbose:
            print("  >> Draw!")
        return "draw"

    if result == "no_moves":
        if verbose:
            loser = first_label if winner == 1 else second_label
            print(f"  >> {loser} has no legal moves!")
        # For board games, winner==0 means first player wins
        if game_name in _BOARD_GAMES:
            return "white" if winner == 0 else "black"
        # connect6: winner value is 1-indexed player
        return "white" if winner == 1 else "black"

    return None  # game continues


def _determine_side_to_move(state, game_name: str, uci_moves: list[str]) -> bool:
    """Return True if it's White's (first player's) turn."""
    if game_name in _BOARD_GAMES:
        return state.player == 0
    if game_name == "connect6":
        return state["player"] == 1  # player 1 = "white" (first player)
    return len(uci_moves) % 2 == 0


def _get_human_move(state, game_name: str, verbose: bool, uci_moves: list[str]) -> str:
    """Get a move from the human player, returning a UCI string."""
    human_fn = _game_ctx.get("get_human_move")
    if human_fn is None:
        return get_human_move_generic(uci_moves)

    if game_name in _BOARD_GAMES and verbose:
        print(f"  Step {state.step}/{_game_ctx['max_step']}")

    result = human_fn(state, _game_ctx)

    if game_name in _BOARD_GAMES:
        return _game_ctx["move_to_uci"](result)
    return result


def _validate_engine_move(
    bestmove_uci: str, state, game_name: str, side_name: str, verbose: bool
) -> bool:
    """Validate an engine move against the current state. Returns True if valid."""
    if game_name == "generic":
        return True

    try:
        move = _game_ctx["uci_to_move"](bestmove_uci)
    except (ValueError, IndexError, KeyError):
        if verbose:
            print(
                f"  >> {side_name} engine returned invalid move "
                f"'{bestmove_uci}'! {side_name} loses."
            )
        return False

    if game_name in _BOARD_GAMES:
        if move not in state.legal_actions:
            if verbose:
                print(
                    f"  >> {side_name} engine returned illegal move "
                    f"{_game_ctx['format_move'](move)}! {side_name} loses."
                )
            return False
    elif game_name == "connect6":
        _, (r, c) = move
        size = state["size"]
        if r < 0 or r >= size or c < 0 or c >= size:
            if verbose:
                print(
                    f"  >> {side_name} engine returned out-of-bounds move "
                    f"'{bestmove_uci}'! {side_name} loses."
                )
            return False
        if state["board"][r][c] != 0:
            if verbose:
                print(
                    f"  >> {side_name} engine returned move to occupied "
                    f"square '{bestmove_uci}'! {side_name} loses."
                )
            return False

    return True


# ---------------------------------------------------------------------------
# Game loop
# ---------------------------------------------------------------------------


def _quit_engine(engine) -> None:
    """Quit a UBGI/UCI engine, ignoring errors."""
    if engine is not None:
        try:
            engine.quit()
        except Exception:
            pass


def run_game(
    white_path: str,
    black_path: str,
    time_limit: int,
    white_algo: str,
    black_algo: str,
    verbose: bool = True,
    game_num: int | None = None,
    total_games: int | None = None,
    depth: int = 0,
    params: list[str] | None = None,
    white_params: list[str] | None = None,
    black_params: list[str] | None = None,
) -> str:
    """Run a single game between two players.

    Returns "white", "black", or "draw".
    params: shared params for both sides.
    white_params/black_params: per-side overrides (merged after shared).
    """
    game_name = _game_ctx.get("name", "generic")
    has_state = game_name != "generic"
    uci_moves: list[str] = []
    move_number = 0
    state = _init_game_state(game_name)

    if verbose:
        if game_num is not None and total_games is not None:
            print(f"=== Game {game_num}/{total_games} ===")
        else:
            print("=== New Game ===")
        print(f"  White: {'Human' if white_path == 'human' else white_algo}")
        print(f"  Black: {'Human' if black_path == 'human' else black_algo}")
        print(f"  Time limit: {time_limit}ms per move")
        if has_state:
            print_board(state)

    while True:
        # --- Check game over ---
        if has_state:
            over = _check_game_over(state, game_name, verbose)
            if over is not None:
                return over

            is_white = _determine_side_to_move(state, game_name, uci_moves)
        else:
            # Generic: no game-over detection, rely on engine
            is_white = len(uci_moves) % 2 == 0

        engine_path = white_path if is_white else black_path
        algo_name = white_algo if is_white else black_algo
        side_name = "White" if is_white else "Black"

        if is_white:
            move_number += 1

        bestmove_uci: str | None = None
        info: dict | None = None

        if engine_path == "human":
            bestmove_uci = _get_human_move(state, game_name, verbose, uci_moves)
        else:
            side_params = list(params or [])
            extra = white_params if is_white else black_params
            if extra:
                side_params.extend(extra)
            bestmove_uci, info = get_engine_move(
                engine_path, algo_name, side_params, uci_moves, time_limit, depth=depth
            )

            if bestmove_uci is None:
                if verbose:
                    print(
                        f"  >> {side_name} engine failed to return a move! "
                        f"{side_name} loses."
                    )
                    print(
                        f"     algo={algo_name}, moves={len(uci_moves)}, "
                        f"last_info={info}"
                    )
                return "black" if is_white else "white"

            # Move validation (for games with state)
            if has_state and not _validate_engine_move(
                bestmove_uci, state, game_name, side_name, verbose
            ):
                return "black" if is_white else "white"

        # For generic games, "none"/"(none)"/"0000" means no moves
        if game_name == "generic" and bestmove_uci in ("none", "(none)", "0000"):
            if verbose:
                print(f"  >> {side_name} has no moves. Game over.")
            return "black" if is_white else "white"

        uci_moves.append(bestmove_uci)

        # Display move
        if verbose:
            prefix = f"{move_number}." if is_white else f"{move_number}..."
            info_str = format_search_info(info)
            display_move = format_move_display(bestmove_uci)
            line = f"  {prefix} {side_name}: {display_move}"
            if info_str:
                line += f" ({info_str})"
            print(line)

        # Advance local state
        if has_state:
            apply_fn = _game_ctx.get("apply_move")
            if apply_fn is not None:
                state, _ = apply_fn(state, bestmove_uci, _game_ctx)

        if verbose and has_state:
            print_board(state)


def run_tournament(
    engine1_path: str,
    engine2_path: str,
    time_limit: int,
    algo1: str,
    algo2: str,
    num_games: int,
    verbose: bool,
    depth: int = 0,
    params: list[str] | None = None,
    engine1_params: list[str] | None = None,
    engine2_params: list[str] | None = None,
) -> None:
    """Run a tournament of N games, alternating colors."""
    engine1_wins = 0
    engine2_wins = 0
    draws = 0
    white_wins = 0
    black_wins = 0
    color_draws = 0

    try:
        for game_idx in range(num_games):
            if game_idx % 2 == 0:
                w_path, w_algo = engine1_path, algo1
                b_path, b_algo = engine2_path, algo2
                engine1_is_white = True
            else:
                w_path, w_algo = engine2_path, algo2
                b_path, b_algo = engine1_path, algo1
                engine1_is_white = False

            w_label = "Human" if w_path == "human" else w_algo
            b_label = "Human" if b_path == "human" else b_algo

            if not verbose:
                e1_color = "White" if engine1_is_white else "Black"
                e2_color = "Black" if engine1_is_white else "White"
                print(
                    f"Game {game_idx + 1}/{num_games}: "
                    f"Engine1({algo1})={e1_color} vs Engine2({algo2})={e2_color}",
                    end="",
                    flush=True,
                )

            # Per-side params follow the engine, not the color
            if engine1_is_white:
                w_params, b_params = engine1_params, engine2_params
            else:
                w_params, b_params = engine2_params, engine1_params

            result = run_game(
                w_path,
                b_path,
                time_limit,
                w_label,
                b_label,
                verbose=verbose,
                game_num=game_idx + 1,
                total_games=num_games,
                depth=depth,
                params=params,
                white_params=w_params,
                black_params=b_params,
            )

            match result:
                case "white":
                    white_wins += 1
                    if engine1_is_white:
                        engine1_wins += 1
                    else:
                        engine2_wins += 1
                case "black":
                    black_wins += 1
                    if engine1_is_white:
                        engine2_wins += 1
                    else:
                        engine1_wins += 1
                case _:
                    draws += 1
                    color_draws += 1

            if not verbose:
                winner_str = {"white": "1-0", "black": "0-1", "draw": "1/2"}[result]
                print(f" {winner_str}")

            total_played = game_idx + 1
            print(
                f"  Score after {total_played} game(s): "
                f"Engine1({algo1}) +{engine1_wins} -{engine2_wins} ={draws}"
            )

    except KeyboardInterrupt:
        print("\n\nTournament interrupted!")

    finally:
        pass  # engines are killed per-move, nothing to clean up

    total = engine1_wins + engine2_wins + draws
    print()
    print("=" * 50)
    print(f"  Tournament Results ({total} games)")
    print("=" * 50)
    print(f"  Engine1 ({algo1}): +{engine1_wins} -{engine2_wins} ={draws}")
    print(f"  Engine2 ({algo2}): +{engine2_wins} -{engine1_wins} ={draws}")
    print(f"  White wins: {white_wins}  Black wins: {black_wins}  Draws: {color_draws}")
    if total > 0:
        e1_score = engine1_wins + draws * 0.5
        print(f"  Engine1 score: {e1_score}/{total} ({e1_score / total * 100:.1f}%)")
    print("=" * 50)


def main() -> None:
    """Parse arguments and run UBGI CLI."""

    parser = argparse.ArgumentParser(
        description="UBGI CLI - Run MiniChess AI vs AI or Human vs AI matches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s --white build/minichess-ubgi --black build/minichess-ubgi --time 2000 --games 10
  %(prog)s --white human --black build/minichess-ubgi --time 2000
""",
    )

    parser.add_argument(
        "--game",
        default="minichess",
        choices=["minichess"],
        help="Game type for board display and move input (default: minichess).",
    )
    parser.add_argument(
        "--white", required=True, help='Path to UBGI/UCI engine for White, or "human".'
    )
    parser.add_argument(
        "--black", required=True, help='Path to UBGI/UCI engine for Black, or "human".'
    )
    parser.add_argument(
        "--time", type=int, default=2000, help="Time per move in ms (default: 2000)."
    )
    parser.add_argument(
        "--games", type=int, default=1, help="Number of games (default: 1)."
    )
    parser.add_argument(
        "--white-algo",
        default="minimax",
        choices=ALGO_CHOICES,
        help="Algorithm for White (default: minimax).",
    )
    parser.add_argument(
        "--black-algo",
        default="minimax",
        choices=ALGO_CHOICES,
        help="Algorithm for Black (default: minimax).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=None,
        help="Show board after each move (default: on for single game).",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Minimal output, just results."
    )
    parser.add_argument(
        "--depth", type=int, default=0, help="Fixed search depth (0 = use time limit)."
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Set engine param for both sides: --param UseKPEval=false. Can repeat.",
    )
    parser.add_argument(
        "--white-param",
        action="append",
        default=[],
        help="Set engine param for white only: --white-param UseKPEval=false",
    )
    parser.add_argument(
        "--black-param",
        action="append",
        default=[],
        help="Set engine param for black only: --black-param UseEvalMobility=false",
    )
    args = parser.parse_args()

    _init_game(args.game.lower())

    if args.quiet:
        verbose = False
    elif args.verbose is not None:
        verbose = args.verbose
    else:
        verbose = args.games == 1

    for label, path in [("--white", args.white), ("--black", args.black)]:
        if path != "human" and not os.path.isfile(path):
            print(f"Error: {label} engine not found: {path}", file=sys.stderr)
            sys.exit(1)

    if args.games < 1:
        print("Error: --games must be >= 1", file=sys.stderr)
        sys.exit(1)

    if args.time < 100:
        print("Error: --time must be >= 100ms", file=sys.stderr)
        sys.exit(1)

    wp = args.white_param or None
    bp = args.black_param or None

    if args.games > 1:
        run_tournament(
            args.white,
            args.black,
            args.time,
            args.white_algo,
            args.black_algo,
            args.games,
            verbose,
            depth=args.depth,
            params=args.param,
            engine1_params=wp,
            engine2_params=bp,
        )
        return

    try:
        result = run_game(
            args.white,
            args.black,
            args.time,
            args.white_algo if args.white != "human" else "Human",
            args.black_algo if args.black != "human" else "Human",
            verbose=verbose,
            depth=args.depth,
            params=args.param,
            white_params=wp,
            black_params=bp,
        )

        result_map = {"white": "1-0", "black": "0-1", "draw": "1/2-1/2"}
        print(f"Result: {result_map[result]}")

    except KeyboardInterrupt:
        print("\nGame aborted.")


if __name__ == "__main__":
    main()
