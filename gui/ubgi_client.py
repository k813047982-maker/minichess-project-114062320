"""UBGI protocol client for communicating with MiniChess engine.

UBGI (Universal Board Game Interface) is backward compatible with UCI.
The handshake sends 'ubgi' and accepts both 'ubgiok' and 'uciok'.
"""

import os
import subprocess
import sys
import threading
import time

try:
    import gui.config as _c
except ImportError:
    import config as _c

try:
    from gui.logger import log as _log
except ImportError:
    try:
        from logger import log as _log
    except ImportError:
        # Fallback if logger not available
        class _DummyLog:
            def debug(self, m):
                pass

            def info(self, m):
                pass

            def warning(self, m):
                pass

            def error(self, m):
                pass

        _log = _DummyLog()


class UBGIEngine:
    """Manages a UBGI/UCI engine subprocess."""

    def __init__(self, exe_path, initial_options=None):
        """Launch engine process with stdin/stdout pipes.

        Sends 'ubgi' and waits for 'ubgiok' or 'uciok', then applies
        *initial_options* (if any), then sends 'isready' and waits for
        'readyok'.

        Args:
            exe_path: Path to a UBGI or UCI compatible engine executable.
            initial_options: Optional dict of {name: value} to send as
                setoption commands before isready.

        Raises:
            RuntimeError: If the engine fails to start or doesn't respond.
        """
        self._exe_path = exe_path
        self._lock = threading.Lock()
        self._process = None
        self._reader_thread = None
        self._searching = False
        self._info_callback = None
        self._done_callback = None
        self._ready_callback = None  # fired on "readyok"
        self.options = []  # Parsed option dicts from the UBGI/UCI handshake

        # Game description (populated from engine options during handshake)
        self.game_name = "Unknown"
        self.board_width = 5
        self.board_height = 6

        # Launch the subprocess
        kwargs = {
            "args": [exe_path],
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "bufsize": 0,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self._process = subprocess.Popen(**kwargs)
        except OSError as exc:
            raise RuntimeError(f"Failed to start engine: {exc}") from exc

        # UBGI handshake -- parse option lines until ubgiok/uciok
        self._send("ubgi")
        if not self._wait_for_uciok(timeout=5.0):
            self.quit()
            raise RuntimeError("Engine did not respond with 'ubgiok' or 'uciok'")

        # Extract game description from options if present
        for opt in self.options:
            if opt["name"] == "GameName" and opt.get("default"):
                self.game_name = opt["default"]
            elif opt["name"] == "BoardWidth" and opt.get("default"):
                try:
                    self.board_width = int(opt["default"])
                except ValueError:
                    pass
            elif opt["name"] == "BoardHeight" and opt.get("default"):
                try:
                    self.board_height = int(opt["default"])
                except ValueError:
                    pass

        # Apply initial options before isready
        if initial_options:
            for name, value in initial_options.items():
                self._send(f"setoption name {name} value {value}")

        self._send("isready")
        if not self._wait_for("readyok", timeout=5.0):
            self.quit()
            raise RuntimeError("Engine did not respond with 'readyok'")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_option(self, name, value):
        """Send 'setoption name X value Y'."""
        self._send(f"setoption name {name} value {value}")

    def new_game(self):
        """Send 'ucinewgame' + 'isready' and wait for 'readyok'."""
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok", timeout=5.0)

    def set_position(self, moves=None, board_str=None, side_to_move=0):
        """Send position to engine.

        Args:
            moves: list of move strings (appended after position).
            board_str: encoded board string for 'position board' command.
            side_to_move: 0 or 1, used with board_str.
        """
        if board_str is not None:
            cmd = f"position board {board_str} {side_to_move}"
        else:
            cmd = "position startpos"
        if moves:
            cmd += " moves " + " ".join(moves)
        self._send(cmd)

    def go(
        self,
        depth=None,
        movetime=None,
        infinite=False,
        info_callback=None,
        done_callback=None,
    ):
        """Start search. Returns immediately.

        Uses a single persistent reader thread. Calling go() again
        (even while searching) just updates callbacks and sends the
        new command — the engine handles stop+go via generation counter.
        """
        parts = ["go"]
        if depth is not None:
            parts.append(f"depth {depth}")
        if movetime is not None:
            parts.append(f"movetime {movetime}")
        if infinite:
            parts.append("infinite")

        # Update callbacks atomically
        self._info_callback = info_callback
        self._done_callback = done_callback
        self._searching = True
        self._send(" ".join(parts))

        # Start persistent reader if not already running
        if self._reader_thread is None or not self._reader_thread.is_alive():
            self._reader_thread = threading.Thread(
                target=self._persistent_read_loop,
                daemon=True,
            )
            self._reader_thread.start()

    def send_ready(self, callback):
        """Send 'isready' and call callback() when 'readyok' is received."""
        self._ready_callback = callback
        self._send("isready")

    def stop(self):
        """Send 'stop' to abort current search."""
        if self._searching:
            self._send("stop")

    def stop_and_wait(self, timeout=5.0):
        """Send 'stop' and wait until bestmove is received.

        Returns True if bestmove was received, False on timeout.
        Safe to call even if not searching.
        """
        if not self._searching:
            return True
        event = threading.Event()
        old_done = self._done_callback

        def _on_done(bm):
            event.set()
            if old_done:
                old_done(bm)

        self._done_callback = _on_done
        self._send("stop")
        result = event.wait(timeout=timeout)
        return result

    def quit(self):
        """Send 'quit' and kill process immediately (non-blocking)."""
        _log.debug(f"quit() called, pid={self._process.pid if self._process else None}")
        self._searching = False
        try:
            self._send("quit")
        except (OSError, BrokenPipeError):
            pass

        if self._process is not None:
            try:
                self._process.kill()
            except Exception:
                pass
            try:
                self._process.wait(timeout=0.5)
            except Exception:
                _log.warning("quit: process.wait timed out")
            self._process = None

    def is_alive(self):
        """Check if engine process is still running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, command):
        """Send a command string to the engine's stdin (thread-safe)."""
        with self._lock:
            if self._process is None or self._process.stdin is None:
                return
            try:
                self._process.stdin.write((command + "\n").encode("utf-8"))
                self._process.stdin.flush()
            except (OSError, BrokenPipeError):
                pass

    def _readline(self, timeout=None):
        """Read a single line from stdout. Returns the line or None on EOF/error.

        Blocks until a line is available. The process kill in quit()
        closes the pipe which unblocks the read.
        """
        if self._process is None or self._process.stdout is None:
            return None
        try:
            line = self._process.stdout.readline()
            if not line:
                return None
            return line.decode("utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return None

    def _wait_for(self, target, timeout=5.0):
        """Read lines until one equals *target* (or timeout).

        Returns True if the target was found, False on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if line is None:
                return False
            if line.strip() == target:
                return True
        return False

    def _wait_for_uciok(self, timeout=5.0):
        """Read lines until 'uciok' or 'ubgiok', parsing 'option' lines along the way.

        Populates self.options with parsed option dicts.
        Returns True if 'uciok' or 'ubgiok' was found, False on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if line is None:
                return False
            stripped = line.strip()
            if stripped == "uciok" or stripped == "ubgiok":
                return True
            if stripped.startswith("option "):
                opt = UBGIEngine.parse_option_line(stripped)
                if opt is not None:
                    self.options.append(opt)
        return False

    def _persistent_read_loop(self):
        """Single persistent reader thread for the engine's lifetime.

        Dispatches info/bestmove to the current callbacks set by go().
        Survives across multiple go/stop cycles.
        """
        try:
            while self.is_alive():
                line = self._readline()
                if line is None:
                    break

                if line.startswith("info "):
                    cb = self._info_callback
                    if cb is not None:
                        info = self.parse_info(line)
                        if info:
                            try:
                                cb(info)
                            except Exception:
                                pass

                elif line.startswith("bestmove"):
                    self._searching = False
                    parts = line.split()
                    bestmove = parts[1] if len(parts) >= 2 else None
                    _log.debug(f"reader: bestmove={bestmove}")
                    cb = self._done_callback
                    if cb is not None:
                        try:
                            cb(bestmove)
                        except Exception as e:
                            _log.error(f"reader: bestmove callback error: {e}")

                elif line.strip() == "readyok":
                    cb = self._ready_callback
                    self._ready_callback = None
                    if cb is not None:
                        try:
                            cb()
                        except Exception:
                            pass
        except Exception as e:
            _log.error(f"reader thread crashed: {e}")
            self._searching = False
        _log.debug("reader thread exited")

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_info(line):
        """Parse an 'info' line from the engine.

        Example input:
            'info depth 6 seldepth 12 score cp 25 nodes 123 time 150 nps 820 pv a2a3 b5b4'

        Returns:
            dict with parsed fields, e.g.:
            {'depth': 6, 'seldepth': 12, 'score_cp': 25, 'nodes': 123,
             'time': 150, 'nps': 820, 'pv': ['a2a3', 'b5b4']}
            Returns empty dict if parsing fails.
        """
        result = {}
        tokens = line.split()

        # Remove the leading 'info' token
        if tokens and tokens[0] == "info":
            tokens = tokens[1:]

        i = 0
        while i < len(tokens):
            token = tokens[i]
            match token:
                case (
                    "depth"
                    | "seldepth"
                    | "nodes"
                    | "time"
                    | "nps"
                    | "multipv"
                    | "hashfull"
                    | "tbhits"
                    | "currmovenumber"
                ) if i + 1 < len(tokens):
                    try:
                        result[token] = int(tokens[i + 1])
                    except ValueError:
                        pass
                    i += 2

                case "score" if i + 2 < len(tokens):
                    score_type = tokens[i + 1]
                    try:
                        score_val = int(tokens[i + 2])
                    except ValueError:
                        i += 3
                        continue
                    if score_type == "cp":
                        result["score_cp"] = score_val
                    elif score_type == "mate":
                        result["score_cp"] = 10000 * (1 if score_val > 0 else -1)
                        result["score_mate"] = score_val
                    i += 3

                case "pv":
                    result["pv"] = tokens[i + 1 :]
                    break

                case "string":
                    result["string"] = " ".join(tokens[i + 1 :])
                    break

                case "currmove" if i + 1 < len(tokens):
                    result["currmove"] = tokens[i + 1]
                    i += 2

                case _:
                    i += 1

        return result

    @staticmethod
    def parse_option_line(line):
        """Parse a UCI 'option' line into a dict.

        Supported formats:
            option name X type check default true
            option name X type spin default 5 min 1 max 10
            option name X type combo default a var a var b var c
            option name X type string default hello

        Returns:
            dict with keys 'name', 'type', 'default', and type-specific
            keys ('min'/'max' for spin, 'vars' for combo), or None on
            parse failure.
        """
        # Remove leading "option " prefix
        if not line.startswith("option "):
            return None
        rest = line[len("option ") :]

        # Extract "name <NAME> type <TYPE> ..."
        # The name may contain spaces, so we find the "type " keyword
        name_prefix = "name "
        if not rest.startswith(name_prefix):
            return None
        rest = rest[len(name_prefix) :]

        type_idx = rest.find(" type ")
        if type_idx < 0:
            return None
        name = rest[:type_idx]
        rest = rest[type_idx + len(" type ") :]

        # Split the remainder to get the type and attributes
        tokens = rest.split()
        if not tokens:
            return None
        opt_type = tokens[0]
        tokens = tokens[1:]

        result = {"name": name, "type": opt_type}

        if opt_type == "check":
            # expect: default true/false
            if len(tokens) >= 2 and tokens[0] == "default":
                result["default"] = tokens[1]
            else:
                result["default"] = "false"

        elif opt_type == "spin":
            # expect: default N min N max N
            i = 0
            while i < len(tokens):
                if tokens[i] == "default" and i + 1 < len(tokens):
                    result["default"] = tokens[i + 1]
                    i += 2
                elif tokens[i] == "min" and i + 1 < len(tokens):
                    result["min"] = tokens[i + 1]
                    i += 2
                elif tokens[i] == "max" and i + 1 < len(tokens):
                    result["max"] = tokens[i + 1]
                    i += 2
                else:
                    i += 1

        elif opt_type == "combo":
            # expect: default X var A var B var C ...
            # default value is everything between "default" and first "var"
            i = 0
            if i < len(tokens) and tokens[i] == "default":
                i += 1
                # Collect default value tokens until "var"
                default_parts = []
                while i < len(tokens) and tokens[i] != "var":
                    default_parts.append(tokens[i])
                    i += 1
                result["default"] = " ".join(default_parts) if default_parts else ""
            else:
                result["default"] = ""
            # Collect var values
            vars_list = []
            while i < len(tokens):
                if tokens[i] == "var":
                    i += 1
                    var_parts = []
                    while i < len(tokens) and tokens[i] != "var":
                        var_parts.append(tokens[i])
                        i += 1
                    if var_parts:
                        vars_list.append(" ".join(var_parts))
                else:
                    i += 1
            result["vars"] = vars_list

        elif opt_type == "string":
            # expect: default <value> (rest of line)
            if len(tokens) >= 2 and tokens[0] == "default":
                result["default"] = " ".join(tokens[1:])
            else:
                result["default"] = ""

        else:
            # Unknown type -- store what we can
            result["default"] = ""

        return result

    @staticmethod
    def move_to_uci(move):
        """Convert ((from_r, from_c), (to_r, to_c)) to UBGI move string.

        Placement move (from == to): returns e.g. 'e5' or 'a10'.
        Drop move (from_r == BOARD_H): returns e.g. 'P*c3'.
        Board move: returns e.g. 'a2a3' or 'a2a10'.
        Promotion move (to_r >= BOARD_H): returns e.g. 'a1b2+'.
        """
        bh = _c.BOARD_H
        (fr, fc), (tr, tc) = move
        col_ch = lambda c: chr(ord("a") + c)
        row_ch = lambda r: str(bh - r)
        # Placement move
        if (fr, fc) == (tr, tc):
            return col_ch(tc) + row_ch(tr)
        # Drop move: from_r == BOARD_H, from_c == piece_type
        drop_char = getattr(_c, "DROP_PIECE_CHAR", {})
        if fr == bh:
            pt = fc
            ch = drop_char.get(pt, "?")
            return ch + "*" + col_ch(tc) + row_ch(tr)
        # Promotion: to_r >= BOARD_H
        promote = tr >= bh
        if promote:
            promo_idx = tr // bh
            actual_tr = tr % bh
            s = col_ch(fc) + row_ch(fr) + col_ch(tc) + row_ch(actual_tr)
            # Check if this is a shogi game (has drops) or chess game
            has_drops = bool(getattr(_c, "DROP_PIECE_CHAR", None))
            if has_drops:
                s += "+"
            else:
                # Chess-style promotion suffix: 1=q, 2=r, 3=b, 4=n
                promo_chars = {1: "q", 2: "r", 3: "b", 4: "n"}
                s += promo_chars.get(promo_idx, "q")
            return s
        s = col_ch(fc) + row_ch(fr) + col_ch(tc) + row_ch(tr)
        return s

    @staticmethod
    def uci_to_move(uci_str):
        """Convert UBGI move string to ((from_r, from_c), (to_r, to_c)).

        Placement: letter + digits (e.g. 'e5', 'a10') → from == to.
        X*sq = drop move (from = (BOARD_H, piece_type)).
        Board move: two squares concatenated (e.g. 'a2a3', 'a2a10').
        Trailing '+' = promotion (to_r += BOARD_H).
        """
        bh = _c.BOARD_H
        if uci_str is None or len(uci_str) < 2:
            return None

        # Drop letter mapping from game engine (stored in config)
        char_to_drop = getattr(_c, "CHAR_TO_DROP_PIECE", {})
        # Build case-insensitive map
        drop_map = {}
        for ch, pt in char_to_drop.items():
            drop_map[ch.upper()] = pt
            drop_map[ch.lower()] = pt

        def parse_sq(s, pos):
            """Parse a square at position pos. Returns ((row, col), next_pos)."""
            col = ord(s[pos]) - ord("a")
            pos += 1
            num_start = pos
            while pos < len(s) and s[pos].isdigit():
                pos += 1
            row = bh - int(s[num_start:pos])
            return (row, col), pos

        # Drop move: X*sq (e.g. P*c3, P*a10)
        if len(uci_str) >= 3 and uci_str[1] == "*":
            pt = drop_map.get(uci_str[0], 0)
            (row, col), _ = parse_sq(uci_str, 2)
            return ((bh, pt), (row, col))

        # Parse first square
        (fr, fc), pos = parse_sq(uci_str, 0)

        # Placement: no more alpha characters after first square
        if pos >= len(uci_str) or not uci_str[pos].isalpha():
            return ((fr, fc), (fr, fc))

        # Board move (possibly with promotion)
        (tr, tc), pos = parse_sq(uci_str, pos)
        if pos < len(uci_str):
            suffix = uci_str[pos]
            if suffix == "+":
                # Shogi-style promotion
                tr += bh
            else:
                # Chess-style promotion suffix: q=1, r=2, b=3, n=4
                promo_map = {
                    "q": 1,
                    "Q": 1,
                    "r": 2,
                    "R": 2,
                    "b": 3,
                    "B": 3,
                    "n": 4,
                    "N": 4,
                }
                pidx = promo_map.get(suffix, 0)
                if pidx > 0:
                    tr += bh * pidx
        return ((fr, fc), (tr, tc))


def discover_engines(build_dir):
    """Find UBGI/UCI engine executables in build directory.

    Looks for executables whose name contains 'uci' or 'ubgi' in the build
    directory and its subdirectories.

    Args:
        build_dir: Path to the build directory.

    Returns:
        List of (name, full_path) tuples, sorted by name.
    """
    results = []
    dirs_to_scan = [build_dir]

    # Also scan common subdirectories
    for subdir in ("Release", "Debug", "baselines"):
        candidate = os.path.join(build_dir, subdir)
        if os.path.isdir(candidate):
            dirs_to_scan.append(candidate)

    for scan_dir in dirs_to_scan:
        if not os.path.isdir(scan_dir):
            continue
        try:
            for entry in os.listdir(scan_dir):
                if sys.platform == "win32":
                    if not entry.lower().endswith(".exe"):
                        continue
                else:
                    full = os.path.join(scan_dir, entry)
                    if not os.path.isfile(full) or not os.access(full, os.X_OK):
                        continue
                full = os.path.join(scan_dir, entry)
                if os.path.isfile(full):
                    name = os.path.splitext(entry)[0]
                    if "uci" in name.lower() or "ubgi" in name.lower():
                        results.append((name, full))
        except OSError:
            continue

    results.sort(key=lambda t: t[0].lower())
    return results
