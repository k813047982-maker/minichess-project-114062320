"""Engine management mixin for GameApp."""

import time

try:
    from gui.ubgi_client import UBGIEngine, discover_engines
    from gui.logger import log
    import gui.config as _cfg
except ImportError:
    from ubgi_client import UBGIEngine, discover_engines
    from logger import log
    import config as _cfg


class EngineManagerMixin:

    def _best_engine_for_game(self):
        """Return the best engine path for the current game.

        Prefers engines whose name starts with the game name
        (e.g. 'minishogi-ubgi' for game 'minishogi'), then falls back
        to the first available engine.
        """
        if not self._available_engines:
            return None
        game = self._game_name.lower().replace(" ", "")
        for name, path in self._available_engines:
            if name.lower().startswith(game):
                return path
        return self._available_engines[0][1]

    def _probe_engine(self, exe_path):
        """Launch *exe_path* and read its algorithms and per-algorithm options.

        Returns a dict with keys: algorithms, default_algo, algo_options
        (algo -> [opt_dicts]), algo_defaults (algo -> {name: default}),
        game_name, board_width, board_height, options. Returns None if the
        engine cannot be started.
        """
        try:
            probe = UBGIEngine(exe_path)
            initial_options = list(probe.options)
        except RuntimeError:
            return None

        info = {
            "algorithms": [],
            "default_algo": None,
            "algo_options": {},
            "algo_defaults": {},
            "game_name": probe.game_name,
            "board_width": probe.board_width,
            "board_height": probe.board_height,
            "options": initial_options,
        }

        # Extract algorithm list from the Algorithm combo
        for opt in initial_options:
            if opt["name"] == "Algorithm" and opt["type"] == "combo":
                info["algorithms"] = list(opt.get("vars", []))
                if opt.get("default") in info["algorithms"]:
                    info["default_algo"] = opt["default"]
                break

        # Store options for the default algo (already loaded), then probe each
        # other algorithm by switching and re-reading its options.
        if info["algorithms"]:
            first_algo = info["algorithms"][0]
            algo_opts = [o for o in initial_options if o["name"] != "Algorithm"]
            info["algo_options"][first_algo] = algo_opts
            info["algo_defaults"][first_algo] = {
                o["name"]: o.get("default", "") for o in algo_opts
            }

            for algo in info["algorithms"][1:]:
                try:
                    probe.set_option("Algorithm", algo)
                    # Re-handshake to get new options
                    probe._send("ubgi")
                    probe.options = []
                    probe._wait_for_uciok(timeout=3.0)
                    algo_opts = [o for o in probe.options if o["name"] != "Algorithm"]
                    info["algo_options"][algo] = algo_opts
                    info["algo_defaults"][algo] = {
                        o["name"]: o.get("default", "") for o in algo_opts
                    }
                except Exception:
                    info["algo_options"][algo] = []
                    info["algo_defaults"][algo] = {}

        try:
            probe.quit()
        except Exception:
            pass

        return info

    def _engine_info(self, exe_path):
        """Return cached probe info for *exe_path*, probing once on demand.

        Each engine is probed and cached separately so the two sides can use
        different engines (e.g. minichess vs boss) with their own algorithm
        lists and parameter sets.
        """
        if exe_path is None:
            return None
        if not hasattr(self, "_engine_cache"):
            self._engine_cache = {}
        if exe_path not in self._engine_cache:
            info = self._probe_engine(exe_path)
            if info is None:
                return None
            self._engine_cache[exe_path] = info
        return self._engine_cache[exe_path]

    def _publish_primary(self, exe_path, info):
        """Publish *info* as the flat attributes used for board rendering and
        as the fallback algorithm list in the dialogs."""
        self._last_probed_engine = exe_path
        self._game_name = info["game_name"]
        self._board_width = info["board_width"]
        self._board_height = info["board_height"]
        self._engine_algorithms = info["algorithms"]
        self._algo_options = info["algo_options"]
        self._algo_defaults = info["algo_defaults"]
        self._engine_options = info["options"]

    def _probe_engine_options(self):
        """Probe the primary engine and adopt its algorithm as the default."""
        exe_path = (
            self.white["engine"] or self.black["engine"] or self._best_engine_for_game()
        )
        info = self._engine_info(exe_path)
        if info is None:
            return
        self._publish_primary(exe_path, info)
        if info["default_algo"]:
            self.white["algo"] = info["default_algo"]
            self.black["algo"] = info["default_algo"]
            self.analyze["algo"] = info["default_algo"]
        # Initialize each side's params with their algo's defaults
        for side in (self.white, self.black, self.analyze):
            side["params"] = dict(info["algo_defaults"].get(side["algo"], {}))

    def _probe_engine_options_from(self, exe_path):
        """Re-probe a specific engine and publish it as the primary."""
        info = self._engine_info(exe_path)
        if info is not None:
            self._publish_primary(exe_path, info)

    def _get_or_create_uci_engine(self, side_config, attr_name):
        """Create or reuse a UCI engine for a given side configuration.

        Args:
            side_config: dict with 'engine', 'algo', 'params' keys.
            attr_name: attribute name on self to store the engine instance.
        """
        existing = getattr(self, attr_name, None)
        if existing is not None and existing.is_alive():
            log.debug(f"_get_or_create: reusing {attr_name}")
            return existing
        log.debug(f"_get_or_create: creating new {attr_name}")
        t0 = time.monotonic()
        try:
            # Build initial options: Algorithm + all params.
            # Sent before isready so the engine has them when it finishes setup.
            init_opts = {"Algorithm": side_config["algo"]}
            init_opts.update({k: str(v) for k, v in side_config["params"].items()})
            engine = UBGIEngine(side_config["engine"], initial_options=init_opts)
            setattr(self, attr_name, engine)
            dt = (time.monotonic() - t0) * 1000
            log.debug(f"_get_or_create: {attr_name} ready ({dt:.1f}ms)")
            return engine
        except RuntimeError as e:
            dt = (time.monotonic() - t0) * 1000
            log.debug(f"_get_or_create: {attr_name} FAILED ({dt:.1f}ms): {e}")
            return None

    def _quit_engine(self, attr):
        """Quit a single UCI engine by attribute name and clear it."""
        engine = getattr(self, attr, None)
        if engine is not None:
            log.debug(f"_quit_engine: {attr}")
            with log.timed(f"quit {attr}"):
                try:
                    engine.quit()
                except Exception:
                    pass
            setattr(self, attr, None)

    def _shutdown_uci_engines(self):
        """Quit all active UCI engine instances."""
        self._stop_analysis()
        for attr in ("_analyze_engine", "white_uci_engine", "black_uci_engine"):
            self._quit_engine(attr)

    # ------------------------------------------------------------------
    # Analyze mode
    # ------------------------------------------------------------------

    def _get_or_create_analyze_engine(self):
        if self._analyze_engine is not None and self._analyze_engine.is_alive():
            return self._analyze_engine
        # Use explicit analyze engine path, or fall back to game-matched engine
        exe_path = (
            self.analyze["engine"]
            or self.white["engine"]
            or self.black["engine"]
            or self._best_engine_for_game()
        )
        if exe_path is None:
            return None
        try:
            init_opts = {"Algorithm": self.analyze["algo"]}
            init_opts.update({k: str(v) for k, v in self.analyze["params"].items()})
            engine = UBGIEngine(exe_path, initial_options=init_opts)
            self._analyze_engine = engine
            return engine
        except RuntimeError:
            return None

    def _start_analysis(self):
        if self.game_result is not None:
            return
        if not self.analyze["enabled"]:
            return
        # Kill old engine and create fresh — instant stop, no races
        self._kill_analyze_engine()
        engine = self._get_or_create_analyze_engine()
        if engine is None:
            return
        self.search_info = {}
        # Send MultiPV setting before starting search
        if self.multi_pv > 1:
            engine.set_option("MultiPV", str(self.multi_pv))
        if self.uci_moves:
            engine.set_position(moves=list(self.uci_moves))
        else:
            engine.set_position()
        engine.go(
            infinite=True,
            info_callback=self._on_analyze_info,
            done_callback=self._on_analyze_done,
        )
        self._analyze_active = True

    def _stop_analysis(self):
        self._kill_analyze_engine()
        self._analyze_active = False
        self.search_info = {}

    def _kill_analyze_engine(self):
        if self._analyze_engine is not None:
            log.debug("_kill_analyze_engine")
            with log.timed("kill analyze engine"):
                try:
                    self._analyze_engine.quit()
                except Exception:
                    pass
            self._analyze_engine = None

    def _on_analyze_info(self, info_dict):
        """Normalize score to White-labeled player's perspective for the score bar."""
        if "score_cp" in info_dict and self.game_state.player == 1:
            info_dict["score_cp"] = -info_dict["score_cp"]

        mpv_idx = info_dict.get("multipv", 1)

        # Maintain pv_multi dict across info updates
        if "pv_multi" not in self.search_info:
            self.search_info["pv_multi"] = {}

        pv_multi = dict(self.search_info.get("pv_multi", {}))

        if "pv" in info_dict:
            pv_multi[mpv_idx] = info_dict["pv"]

        # Store per-PV score
        if "score_cp" in info_dict:
            score_key = f"score_mpv_{mpv_idx}"
            info_dict[score_key] = info_dict["score_cp"]

        # For multipv 1 (the best line), update the main search_info
        if mpv_idx == 1:
            # Preserve last known PV if new info doesn't have one
            if "pv" not in info_dict and "pv" in self.search_info:
                info_dict["pv"] = self.search_info["pv"]
            info_dict["pv_multi"] = pv_multi
            self.search_info = info_dict
        else:
            # For secondary PVs, update pv_multi and per-PV score
            self.search_info["pv_multi"] = pv_multi
            if "score_cp" in info_dict:
                self.search_info[f"score_mpv_{mpv_idx}"] = info_dict["score_cp"]

    def _on_analyze_done(self, bestmove_str):
        # Engine stopped (either by our stop or by completing depth limit).
        # Don't clear _analyze_active here — a new go may already be in flight.
        pass

    # ------------------------------------------------------------------
    # AI management
    # ------------------------------------------------------------------

    def trigger_ai_move(self):
        player = self.game_state.player
        side = self.white if player == 0 else self.black
        log.debug(f"trigger_ai_move: player={player} depth={side.get('depth',0)}")

        if side["engine"] is None:
            return  # human's turn

        self.ai_thinking = True
        self.ai_result = {"move": None, "depth": 0, "ready": False}
        self.search_info = {}
        self._ai_start_time = time.time()

        attr = "white_uci_engine" if player == 0 else "black_uci_engine"
        uci = self._get_or_create_uci_engine(side, attr)

        if uci is None:
            # Engine failed to start
            self.ai_result = {"move": None, "depth": 0, "ready": True}
            return

        if self.uci_moves:
            uci.set_position(moves=list(self.uci_moves))
        else:
            uci.set_position()

        max_depth = side["depth"]
        if max_depth > 0:
            uci.go(
                depth=max_depth,
                info_callback=self._on_uci_info,
                done_callback=self._on_uci_bestmove,
            )
        else:
            movetime_ms = int(self.time_limit * 1000)
            uci.go(
                movetime=movetime_ms,
                info_callback=self._on_uci_info,
                done_callback=self._on_uci_bestmove,
            )

    def _force_kill_ai_engine(self):
        """Kill the AI engine after timeout; use last known best move."""
        player = self.game_state.player
        attr = "white_uci_engine" if player == 0 else "black_uci_engine"
        engine = getattr(self, attr, None)

        # Extract best move from last search info (currmove or pv[0])
        bestmove = None
        info = self.search_info
        if info.get("pv"):
            bestmove = UBGIEngine.uci_to_move(info["pv"][0])
        elif info.get("currmove"):
            bestmove = UBGIEngine.uci_to_move(info["currmove"])

        # Kill engine process
        if engine is not None:
            try:
                engine.quit()
            except Exception:
                pass
            setattr(self, attr, None)

        depth = info.get("depth", 0)
        self.ai_result = {"move": bestmove, "depth": depth, "ready": True}

    def _on_uci_info(self, info_dict):
        if "score_cp" in info_dict and self.game_state.player == 1:
            info_dict["score_cp"] = -info_dict["score_cp"]
        # Preserve last known PV and currmove for timeout fallback
        if "pv" not in info_dict and "pv" in self.search_info:
            info_dict["pv"] = self.search_info["pv"]
        if "currmove" not in info_dict and "currmove" in self.search_info:
            info_dict["currmove"] = self.search_info["currmove"]
        self.search_info = info_dict

    def _on_uci_bestmove(self, bestmove_str):
        log.info(f"bestmove received: {bestmove_str}")
        if bestmove_str is None:
            self.ai_result = {"move": None, "depth": 0, "ready": True}
            return

        move = UBGIEngine.uci_to_move(bestmove_str)

        # If move not in legal actions, try auto-promotion (chess pawn to last rank)
        if move is not None and move not in self.game_state.legal_actions:
            (fr, fc), (tr, tc) = move
            bh = _cfg.BOARD_H
            # Check if this is a pawn reaching last rank without promotion encoding
            if tr < bh:
                player = self.game_state.player
                try:
                    piece = self.game_state.board[player][fr][fc]
                except (TypeError, IndexError):
                    piece = 0
                is_pawn = piece == 1  # PAWN = 1 in both chess variants
                is_last_rank = (tr == 0 and player == 0) or (
                    tr == bh - 1 and player == 1
                )
                if is_pawn and is_last_rank:
                    # Try queen promotion (promo_idx=1 → to_r + BOARD_H)
                    promo_move = ((fr, fc), (tr + bh, tc))
                    if promo_move in self.game_state.legal_actions:
                        move = promo_move

        depth = self.search_info.get("depth", 0)
        self.ai_result = {"move": move, "depth": depth, "ready": True}
