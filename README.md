# MiniChess Engine (6×5)

A compact, game-agnostic board-game search engine. The game (MiniChess, played
on a 6×5 board) lives behind an abstract `BaseState` interface; the search
algorithms and the protocol layer contain **no** game-specific knowledge. The
engine speaks **UBGI** — a superset of the UCI chess protocol — over
stdin/stdout, and ships with Python GUI and CLI front-ends.

```
+----------------------------------------------+
|        Front-ends (UBGI engine, GUI, CLI)     |
+----------------------------------------------+
                      |
                      v
+----------------------------------------------+
|   Search (game-agnostic): MiniMax, Random     |
+----------------------------------------------+
                      |
                      v
+----------------------------------------------+
|            BaseState (abstract class)         |
|   next_state / get_legal_actions / evaluate   |
|   hash / encode_board / ...                    |
+----------------------------------------------+
                      |
                      v
+----------------------------------------------+
|       MiniChess State  (src/games/minichess)  |
+----------------------------------------------+
```

---

## Build & run

Requires `g++` with C++20 (`--std=c++2a`); compiles with `-O3 -march=native`.

```bash
make all          # engine + benchmark + unit tests
make minichess    # -> build/minichess-ubgi    (the UBGI engine)
make benchmark    # -> build/minichess-benchmark (per-depth timing of each algorithm)
make test         # -> unittest/build/state_test (move-generation self-check)
make clean
```

A single unit-test target is built by stripping the `_test.cpp` suffix:

```bash
make state                      # builds unittest/build/state_test
./unittest/build/state_test
```

Run the engine directly (it then waits for UBGI commands on stdin):

```bash
./build/minichess-ubgi
```

> **Build status.** The hands-on exercises are four groups of `[Hackathon
> TODO]` markers across `src/games/minichess/state.cpp` (group 1: `evaluate()`;
> group 2: the knight case of the *naive* move generator) and
> `src/policy/minimax.cpp` (group 3: recursive `eval_ctx()`; group 4: the root
> `search()`). Every target compiles `state.cpp` together with the policy
> sources, and group 4 has a build-stopping error, so **no** target links until
> `minimax.cpp` is filled in. Once it compiles, `state_test` (the
> naive-vs-bitboard move-generation check) builds — and passes only after the
> naive generator's knight moves (group 2) are added; until then the two
> generators disagree, which is exactly what the test catches.
>
> `random.cpp`, the bitboard move generator, the UBGI layer, the registry, and
> Zobrist hashing are complete.

---

## MiniChess rules

A 6-row × 5-column chess variant.

| Piece | Movement |
|-------|----------|
| `P` Pawn | Forward one square; captures diagonally; promotes to Queen on the back rank. |
| `R` `N` `B` `Q` `K` | Standard chess movement, on the smaller 6×5 board. |

- **King capture wins.** The engine uses a king-capture model rather than
  checkmate: a position where the side to move can capture the opponent's king
  is terminal (`WIN`).
- **Draw** by 4-fold repetition.
- No castling, no double-step pawn, no en passant.

Initial position (uppercase = White / player 0, lowercase = Black / player 1):

```
   a  b  c  d  e
6  k  q  b  n  r      <- Black back rank
5  p  p  p  p  p
4  .  .  .  .  .
3  .  .  .  .  .
2  P  P  P  P  P
1  R  N  B  Q  K      <- White back rank
```

Squares are named column-letter + rank-number (`a1` is the bottom-left square
from White's perspective). White's king starts on `e1`, Black's on `a6`.

---

## Architecture

### Layers

1. **Game-agnostic core** — search algorithms (`src/policy/`), the UBGI
   protocol (`src/ubgi/`), and shared types (`src/search_types.hpp`,
   `src/search_params.hpp`). None of this code names a piece or a coordinate;
   it talks only to `BaseState`.
2. **Per-game `State`** — `src/games/minichess/` implements `BaseState`.
3. **Front-ends** — the UBGI engine binary, plus the Python GUI and CLI.

### Compile-time game selection

The game is bound at **compile time** through the include path, not by the
search code. The Makefile sets:

```makefile
MINICHESS_INC = -Isrc/games/minichess -Isrc/state -Isrc
```

Search and protocol code `#include "state.hpp"` and `#include "config.hpp"`
**without a path prefix**; the preprocessor resolves them to the game directory
that appears first on the include path. Swapping in a different game is a
matter of changing the `-I` flags, not the search code.

### Key seams

| Seam | File | Role |
|------|------|------|
| `BaseState` | `src/state/base_state.hpp` | Virtual interface every game implements. |
| `SearchContext` / `SearchResult` / `RootUpdate` | `src/search_types.hpp` | What every search produces; `on_root_update` reports live progress. |
| `ParamMap` / `ParamDef` | `src/search_params.hpp` | Runtime parameters per algorithm, advertised to the GUI via UBGI options. |
| `registry.hpp` | `src/policy/registry.hpp` | Static table mapping algorithm name → `{default_params, param_defs, search}`. |
| `GameHistory` | `src/policy/game_history.hpp` | Game-agnostic position-hash counter for repetition detection. |
| `UBGI` | `src/ubgi/ubgi.cpp` | UCI-superset protocol loop. |

Score bounds (`src/state/base_state.hpp`): `P_MAX = 100000`,
`M_MAX = -100000`. Winning terminals are scored `P_MAX - ply` so that faster
wins are preferred.

---

## The `State` interface

### Type aliases & enums (`base_state.hpp`)

```cpp
typedef std::pair<size_t, size_t> Point;   // (row, col)
typedef std::pair<Point, Point>   Move;    // (from, to)

enum GameState { UNKNOWN = 0, WIN, DRAW, NONE };

constexpr int P_MAX =  100000;   // current player wins
constexpr int M_MAX = -100000;   // current player loses
```

### `BaseState`

```cpp
class BaseState {
public:
    int player = 0;                 // side to move: 0 or 1
    int step = 0;
    GameState game_state = UNKNOWN;
    std::vector<Move> legal_actions;

    // --- core (pure virtual) ---
    virtual BaseState* next_state(const Move& m) = 0;     // heap-allocated successor; caller deletes
    virtual void get_legal_actions() = 0;                 // fills legal_actions, sets game_state
    virtual int  evaluate(bool use_kp = true,
                          bool use_mobility = true,
                          const GameHistory* history = nullptr) = 0;

    // --- description (pure virtual) ---
    virtual int board_h() const = 0;
    virtual int board_w() const = 0;
    virtual const char* game_name() const = 0;

    // --- serialization (pure virtual) ---
    virtual std::string encode_board() const = 0;
    virtual void        decode_board(const std::string& s, int side_to_move) = 0;
    virtual std::string encode_output() const = 0;

    // --- optional hooks (have defaults) ---
    virtual bool       same_player_as_parent() const;                       // multi-stone turns (Connect6); default false
    virtual bool       check_repetition(const GameHistory&, int& out) const; // default: no repetition rule
    virtual BaseState* create_null_state() const;                           // for null-move pruning; default nullptr
    virtual int        piece_at(int player, int row, int col) const;        // default 0
    virtual uint64_t   hash() const;                                        // default 0
    virtual std::string cell_display(int row, int col) const;               // default " . "
    virtual int        hand_count(int player, int piece_type) const;        // shogi drops; default 0
    virtual int        num_hand_types() const;                              // default 0
};
```

| Method | Contract |
|--------|----------|
| `next_state(m)` | Returns a **heap-allocated** successor; the caller owns and must `delete` it. Typically calls `get_legal_actions()` on the child. |
| `get_legal_actions()` | Populates `legal_actions` and sets `game_state`. Must run before inspecting moves or terminal status. |
| `evaluate(...)` | Integer score from the **current player's** perspective. `P_MAX` = current player wins. Flags toggle KP eval (material + PST + king tropism) and the mobility term. |
| `hash()` | Zobrist hash of the position. |
| `check_repetition(history, out)` | Returns `true` and sets `out` (e.g. `0` for draw) when a repetition rule fires. |
| `create_null_state()` | A state with the side-to-move flipped (a "pass"); `nullptr` if the game has no null move. |

### MiniChess `State` (`src/games/minichess/state.hpp`)

```cpp
class Board {
public:
    char board[2][BOARD_H][BOARD_W];   // board[player][row][col]; 0=empty, 1..6 = P R N B Q K
};

class State : public BaseState {
    Board board;
    mutable uint64_t zobrist_hash;     // incremental Zobrist hash (lazy)
    // overrides: next_state, get_legal_actions, evaluate, hash, check_repetition,
    //            create_null_state, piece_at, encode_board/decode_board, encode_output, ...
    void get_legal_actions_naive();    // straightforward reference move generator
    void get_legal_actions_bitboard(); // fast bitboard move generator (used by the engine)
};
```

Two move generators exist on purpose. The fast `get_legal_actions_bitboard()`
is what the engine uses; `get_legal_actions_naive()` is a straightforward
cross-check. The unit test (`make test`) runs both on the same positions and
asserts they produce identical move lists — a differential check that flags any
divergence between the two implementations.

---

## Search algorithms

Algorithms are registered in `src/policy/registry.hpp` and selected at runtime
via the UBGI `Algorithm` option. The default is **`minimax`**.

| Name | File | Description |
|------|------|-------------|
| `minimax` | `src/policy/minimax.cpp` | Exhaustive negamax to a fixed depth, no pruning. The correctness baseline. |
| `random`  | `src/policy/random.cpp`  | Picks a uniformly random legal move; no search or evaluation. |

Every algorithm exposes the same entry point and registers it in the table:

```cpp
SearchResult search(State* state, int depth, GameHistory& history, SearchContext& ctx);
```

`SearchContext` carries the node counter, selective depth, the `stop` flag, the
parameter map, and the `on_root_update` progress callback. `SearchResult`
carries `best_move`, `score`, `depth`, `seldepth`, `nodes`, `time_ms`, and the
principal variation `pv`.

**Iterative deepening** lives in the UBGI layer (`src/ubgi/ubgi.cpp`), not in
the algorithms: it calls `search()` at depth 1, 2, 3, … emitting an `info` line
after each completed depth and honoring `depth` / `movetime` / `stop` limits.

---

## Evaluation

`evaluate()` returns a score from the side-to-move's perspective. A won
position returns `P_MAX`. Otherwise the score is

```
score = self_material - opponent_material + bonus
```

with two optional refinements toggled by flags:

- **`use_kp` (KP eval)** — adds piece-square tables and king tropism (a bonus
  for pieces close to the enemy king) on top of material; otherwise a plain
  material count is used.
- **`use_mobility`** — adds `2 × (self_moves − opponent_moves)`.

Per-piece material and ordering values are defined in
`src/games/minichess/config.hpp`.

---

## Hashing & repetition detection

**Zobrist hashing** (`State::hash()`): each position has a 64-bit Zobrist key
built from per-(player, piece, square) random values plus a side-to-move key,
seeded by a fixed deterministic xorshift PRNG so hashes are reproducible across
runs. The key is cached on the `State` and recomputed lazily.

**Repetition** is tracked game-agnostically by `GameHistory`
(`src/policy/game_history.hpp`), a `position-hash → count` map. The search
`push()`es/`pop()`s positions as it descends and unwinds;
`State::check_repetition()` reads the count and reports a draw at the 4th
occurrence (`limit = 4`).

---

## UBGI protocol

UBGI (Universal Board Game Interface) is a UCI superset. Communication is one
command per line over stdin/stdout; a trailing `\r` is tolerated and blank
lines are ignored. Sending `uci` instead of `ubgi` runs in UCI-compatible mode
(the engine answers `uciok` instead of `ubgiok`).

### GUI → engine

| Command | Description |
|---------|-------------|
| `ubgi` / `uci` | Handshake. Engine replies with `id`, `option` lines, then `ubgiok`/`uciok`. |
| `isready` | Sync ping; engine replies `readyok`. |
| `setoption name <N> value <V>` | Set an option (see below). |
| `position startpos [moves <m1> …]` | Set the start position, optionally replaying moves. |
| `position board <encoded> <side> [moves …]` | Set a position from an encoded board string (`<side>` = 0 or 1). |
| `go [depth <N>] [movetime <ms>] [infinite]` | Start searching on a background thread. |
| `stop` | Interrupt the search; engine returns the best move found so far. |
| `ubginewgame` / `ucinewgame` | Reset board, side-to-move, and step counter. |
| `d` | Print the current board (debug). |
| `quit` | Exit. |

### Engine → GUI

`id name <name>` · `id author <author>` · `option name …` ·
`ubgiok`/`uciok` · `readyok` · `info …` · `bestmove <move>`.

An `info` line may carry `depth`, `seldepth`, `score cp <n>`, `nodes`, `time`
(ms), `nps`, `currmove`, `currmovenumber`, and `pv` (which must come last).

### Options

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `GameName` | string | `MiniChess` | Read-only metadata. |
| `BoardWidth` / `BoardHeight` | spin | `5` / `6` | Read-only metadata. |
| `Algorithm` | combo | `minimax` | One of `minimax`, `random`. Switching resets that algorithm's parameters to its defaults. |
| `MultiPV` | spin | `1` (1–10) | Report the top-N candidate moves with scores. |
| `UseKPEval` | check | `true` | Use KP evaluation (material + PST + tropism). |
| `UseEvalMobility` | check | `true` | Include the mobility term. |
| `ReportPartial` | check | `true` | Emit per-root-move `info` updates during search. |

(The algorithm-specific options above are advertised for the active algorithm;
`random` takes no parameters.)

### Move notation

Coordinates are column letter (`a`–`e`) + rank number (`1`–`6`). A board move
is the origin square followed by the destination square (4 characters). Pawn
promotion appends a piece letter (`q`/`r`/`b`/`n`). `0000` means "no legal
move".

```
a2a3     move from a2 to a3
e1d2     move from e1 to d2
b2b1q    pawn promotion to queen
```

### Example session

```
GUI:    ubgi
ENGINE: id name MiniChess
ENGINE: id author MiniChess Team
ENGINE: option name GameName type string default MiniChess
ENGINE: option name BoardWidth type spin default 5 min 1 max 26
ENGINE: option name BoardHeight type spin default 6 min 1 max 26
ENGINE: option name Algorithm type combo default minimax var minimax var random
ENGINE: option name UseKPEval type check default true
ENGINE: option name UseEvalMobility type check default true
ENGINE: option name ReportPartial type check default true
ENGINE: option name MultiPV type spin default 1 min 1 max 10
ENGINE: ubgiok
GUI:    isready
ENGINE: readyok
GUI:    position startpos
GUI:    go depth 6
ENGINE: info depth 1 seldepth 1 score cp 12 nodes 30 time 0 nps 0 pv a2a3
ENGINE: info depth 6 seldepth 8 score cp 25 nodes 48201 time 120 nps 401675 pv a2a3 e5e4 b1c3
ENGINE: bestmove a2a3
GUI:    quit
```

---

## GUI & CLI

Python wrappers that drive the UBGI binary as a subprocess.

```bash
# GUI: per-side engine/algorithm/param config, live PV, eval bar, Multi-PV arrows
python gui/main.py

# CLI: human vs engine
python cli/cli.py --white human --black build/minichess-ubgi --time 2000

# CLI: engine vs engine, fixed depth
python cli/cli.py --white build/minichess-ubgi --black build/minichess-ubgi --depth 8

# CLI: pick algorithms per side
python cli/cli.py --white build/minichess-ubgi --black build/minichess-ubgi \
    --white-algo minimax --black-algo random --games 100 --time 2000
```

---

## Project structure

```
src/
  config.hpp                  # global settings (RANDOM_SEED, NUM_HAND_TYPES)
  search_types.hpp            # SearchContext, SearchResult, RootUpdate
  search_params.hpp           # ParamMap, ParamDef, param_bool/param_int
  state/
    base_state.hpp            # BaseState — the virtual game interface
  games/
    minichess/
      config.hpp              # BOARD_H=6, BOARD_W=5, piece values, display table
      state.hpp               # Board (2-plane), State : BaseState
      state.cpp               # move generation (naive + bitboard), evaluate, hash
  policy/
    registry.hpp              # algorithm registry (name -> search)
    game_history.hpp          # position-hash counter for repetition
    minimax.hpp/cpp           # negamax search
    random.hpp/cpp            # random legal move
  ubgi/
    ubgi.hpp/cpp              # UBGI protocol loop, iterative deepening, MultiPV
  benchmark.cpp               # per-depth timing of every registered algorithm
gui/                          # Pygame GUI (subprocess UBGI client)
cli/                          # CLI runner
unittest/
  state_test.cpp              # naive-vs-bitboard move-generation differential test
docs/                         # design/reference notes (from the parent project)
```

> Note: `docs/` is carried over from the larger multi-game project this engine
> was derived from, and describes features not present here (other games, NNUE
> evaluation, additional search algorithms). Treat this README as the source of
> truth for the current code.
