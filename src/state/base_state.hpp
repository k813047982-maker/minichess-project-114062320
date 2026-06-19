#pragma once
#include <vector>
#include <string>
#include <utility>
#include <cstddef>
#include <cstdint>

/* Forward-declare GameHistory so evaluate() can accept an optional pointer. */
struct GameHistory;

/* === Type aliases === */
typedef std::pair<size_t, size_t> Point;
typedef std::pair<Point, Point> Move;

enum GameState { UNKNOWN = 0, WIN, DRAW, NONE };

/* === Score bounds === */
constexpr int P_MAX = 100000;
constexpr int M_MAX = -100000;

class BaseState {
public:
    int player = 0;
    int step = 0;
    GameState game_state = UNKNOWN;
    std::vector<Move> legal_actions;

    virtual ~BaseState() = default;

    /* === Core === */
    virtual BaseState* next_state(const Move& m) = 0;
    virtual void get_legal_actions() = 0;
    virtual int evaluate(
        bool use_kp = true,
        bool use_mobility = true,
        const GameHistory* history = nullptr
    ) = 0;

    /* === Multi-stone turns (Connect6 etc.) ===
     * Returns true if this state's player is the SAME as the parent's.
     * Standard games always return false (player alternates every move).
     * Connect6 returns true for the first of 2 stones in a turn.
     * Search uses this to skip score negation between same-player moves. */
    virtual bool same_player_as_parent() const { return false; }

    /* === Game description === */
    virtual int board_h() const = 0;
    virtual int board_w() const = 0;
    virtual const char* game_name() const = 0;

    /* === Repetition detection (game-specific) ===
     * Returns true if the current position triggers a repetition rule.
     * Sets out_score to the appropriate score (0=draw, -P_MAX=loss, etc.).
     * Default: no repetition rule. Override per game. */
    virtual bool check_repetition(const GameHistory& /*history*/, int& /*out_score*/) const {
        return false;
    }

    /* === Null move: create a state with side-to-move flipped (pass) === */
    virtual BaseState* create_null_state() const { return nullptr; }

    /* === Piece query: returns piece type at (row, col) for given player === */
    virtual int piece_at(int /*player*/, int /*row*/, int /*col*/) const { return 0; }

    /* === Board hash for transposition table === */
    virtual uint64_t hash() const { return 0; }

    /* === Display string for a cell at (row, col) === */
    virtual std::string cell_display(int /*row*/, int /*col*/) const { return " . "; }

    /* === Hand pieces (for games with captures-to-hand like shogi) === */
    virtual int hand_count(int /*player*/, int /*piece_type*/) const { return 0; }
    virtual int num_hand_types() const { return 0; }

    /* === Board serialization for UBGI 'position board' command === */
    virtual std::string encode_board() const = 0;
    virtual void decode_board(const std::string& s, int side_to_move) = 0;

    /* === Display === */
    virtual std::string encode_output() const = 0;
};
