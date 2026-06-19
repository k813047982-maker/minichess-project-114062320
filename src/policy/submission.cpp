#include <algorithm>
#include <utility>
#include <vector>
#include <chrono>
#include <cstring>
#include "state.hpp"
#include "config.hpp"
#include "submission.hpp"

/*============================================================
 * Submission policy implementation notes
 *
 * Negamax + alpha-beta with PVS (principal variation search),
 * a transposition table, null-move pruning, late move
 * reductions, and quiescence search. Move ordering: TT move >
 * MVV-LVA captures > killer moves > history heuristic.
 *
 * Two additions on top of the base search:
 *  1. Check extension -- this ruleset has no formal "in check"
 *     legality rule, so a king under attack is only ever
 *     noticed by the search actually looking deep enough to see
 *     the capture. Quiescence search only looks at captures, so
 *     if the king is attacked and the only escape is a
 *     non-capturing move, it would be invisible there. Fixed by
 *     extending the main search by one ply when in check, and
 *     having quiescence search all legal moves (not just
 *     captures) on those nodes, both capped to bound worst-case
 *     search blowup from long forcing sequences.
 *  2. Move ordering optimization -- move scores used to be
 *     recomputed inside the std::stable_sort comparator on every
 *     comparison (O(n log n) redundant work per node). Now each
 *     move's priority is computed once and sorted by that
 *     precomputed key (~20% NPS improvement measured).
 *============================================================*/


/*============================================================
 * Self-contained move time budget
 *
 * ubgi.cpp (which we cannot modify) calls Submission::search()
 * once per iterative-deepening depth (1, 2, 3, ...) and lets it
 * run to completion; it only checks wall-clock time *between*
 * depths. To protect against a single deep iteration blowing far
 * past the intended per-move budget, we track our own wall-clock
 * deadline here, entirely within src/policy/.
 *
 * "depth == 1" reliably signals the start of a fresh move's
 * thinking: every call site (ubgi.cpp's do_search loop AND
 * src/benchmark.cpp's timing loop) always begins at depth 1
 * before trying deeper values. We reset our internal clock then,
 * and derive each subsequent depth's remaining budget from how
 * much wall-clock time has elapsed since that reset — so depth
 * N+1 only gets whatever budget is left, not a fresh 2 seconds.
 *
 * Crucially: time_budget_exceeded() never touches ctx.stop. See
 * submission.hpp for why that matters.
 *============================================================*/
static std::chrono::steady_clock::time_point g_move_deadline =
    std::chrono::steady_clock::time_point::max();

static inline void maybe_start_move_clock(int depth, int64_t external_movetime_ms, const SubmissionParams& p){
    if(depth <= 1){
        /* Prefer the real budget the GUI/CLI/match harness actually gave
         * us via "go movetime <ms>" (now threaded through SearchContext).
         * Falls back to the MoveBudgetMs param only when no movetime was
         * given at all (e.g. "go depth N" with no time control, used by
         * benchmark.cpp / fixed-depth testing) -- previously this fell
         * back to a hard-coded 2000ms unconditionally, so if a match was
         * actually run with a different per-move time control than our
         * default, we'd either waste granted thinking time or risk
         * overrunning it. */
        int64_t budget_ms = (external_movetime_ms > 0)
            ? external_movetime_ms
            : (int64_t)p.move_budget_ms;
        auto margin = std::chrono::milliseconds(std::min<int64_t>(150, budget_ms / 10));
        g_move_deadline = std::chrono::steady_clock::now()
            + std::chrono::milliseconds(budget_ms) - margin;
    }
}

/* Cheap to call every node: only actually reads the clock every
 * 1024 calls (tracked via the node counter already kept in ctx). */
static inline bool time_budget_exceeded(SearchContext& ctx){
    if(ctx.stop){
        return true; /* still respect a genuine external stop/quit */
    }
    if((ctx.nodes & 0x3FFULL) != 0){
        return false;
    }
    return std::chrono::steady_clock::now() >= g_move_deadline;
}


/*============================================================
 * Transposition table
 *
 * A fixed-size, "always replace" hash table keyed by the
 * position's Zobrist hash (State::hash(), which already folds
 * in side-to-move). Each slot stores enough to (a) reuse an
 * exact/bounded score without re-searching, and (b) hint the
 * best move found last time for move ordering even when the
 * stored depth is too shallow to trust the score itself.
 *
 * Scoped as static tables in this translation unit: they persist
 * across the whole iterative-deepening ladder for one `go` (so
 * depth N's results immediately help order depth N+1) and across
 * moves in the same game, without needing any change to the
 * generic SearchContext used by other algorithms. Entries are
 * always validated against the full stored hash before use, so
 * stale entries from an earlier game/position are simply
 * ignored — never a correctness risk, only a (harmless) wasted
 * lookup.
 *============================================================*/
enum class TTFlag : uint8_t { EXACT, LOWERBOUND, UPPERBOUND, EMPTY };

struct TTEntry {
    uint64_t hash = 0;
    int16_t depth = -1;
    int32_t score = 0;
    TTFlag flag = TTFlag::EMPTY;
    Move best_move;
};

static constexpr size_t TT_SIZE = 1u << 20; /* ~1M entries, power of two */
static std::vector<TTEntry> g_tt(TT_SIZE);

static inline TTEntry* tt_probe(uint64_t hash){
    TTEntry& e = g_tt[hash & (TT_SIZE - 1)];
    if(e.flag != TTFlag::EMPTY && e.hash == hash){
        return &e;
    }
    return nullptr;
}

static inline void tt_store(uint64_t hash, int depth, int score, TTFlag flag, const Move& best_move){
    TTEntry& e = g_tt[hash & (TT_SIZE - 1)];
    if(e.flag == TTFlag::EMPTY || e.hash == hash || depth >= e.depth){
        e.hash = hash;
        e.depth = (int16_t)depth;
        e.score = score;
        e.flag = flag;
        e.best_move = best_move;
    }
}

/*============================================================
 * Killer moves + history heuristic
 *
 * Killer moves: up to 2 non-capture moves per ply that previously
 * caused a beta cutoff. Tried right after the TT move and captures,
 * since a move that cut off a sibling node at the same ply is often
 * good here too (same side to move, similar local threats).
 *
 * History heuristic: a [piece][to_row][to_col] table accumulating
 * "how often (weighted by depth^2) has moving this piece to this
 * square caused a cutoff", used to break ties among the remaining
 * non-capture, non-killer moves.
 *============================================================*/
static constexpr int MAX_PLY = 128;
static Move g_killers[MAX_PLY][2];
static int g_history[7][BOARD_H][BOARD_W];

static inline void record_killer(int ply, const Move& m){
    if(ply < 0 || ply >= MAX_PLY){
        return;
    }
    if(g_killers[ply][0] == m){
        return;
    }
    g_killers[ply][1] = g_killers[ply][0];
    g_killers[ply][0] = m;
}

static inline bool is_killer(int ply, const Move& m){
    if(ply < 0 || ply >= MAX_PLY){
        return false;
    }
    return g_killers[ply][0] == m || g_killers[ply][1] == m;
}

static inline void record_history(State* state, const Move& m, int depth){
    int piece = state->piece_at(state->player, m.first.first, m.first.second);
    if(piece <= 0 || piece > 6){
        return;
    }
    int& slot = g_history[piece][m.second.first][m.second.second];
    slot += depth * depth;
    if(slot > 1000000){
        for(int pc = 0; pc < 7; pc++){
            for(int r = 0; r < BOARD_H; r++){
                for(int c = 0; c < BOARD_W; c++){
                    g_history[pc][r][c] /= 2;
                }
            }
        }
    }
}

void Submission::clear_tables(){
    std::fill(g_tt.begin(), g_tt.end(), TTEntry{});
    std::memset(g_killers, 0, sizeof(g_killers));
    std::memset(g_history, 0, sizeof(g_history));
}


/*============================================================
 * Move ordering — TT move > MVV-LVA captures > killers > history
 *
 * Computes each move's priority exactly once (a handful of
 * piece_at() virtual calls + table lookups), then sorts by that
 * precomputed key. The previous version computed all of this
 * *inside* the std::stable_sort comparator, which gets called
 * O(n log n) times for n moves -- e.g. ~20 moves means roughly
 * 80-90 comparisons, each redoing up to 4 piece_at() virtual
 * calls plus killer/history lookups for moves whose tier never
 * changes between comparisons. order_moves() runs on essentially
 * every node of the tree (main search and quiescence both call
 * it), so that redundant work was paid for at every single node.
 *
 * Tiers (descending key = higher priority), matching the original
 * comparator's behavior exactly: TT move > captures (by MVV-LVA)
 * > killers (by history) > everything else (by history). TIER is
 * comfortably larger than the max possible secondary score (MVV-LVA
 * tops out at PIECE_VALUES[king]*16 ~= 14400; history saturates
 * just above 1,000,000 before record_history()'s halving kicks in),
 * so tier always dominates regardless of the secondary value.
 *============================================================*/
static constexpr int MOVE_ORDER_TIER = 1u << 22; /* ~4.19M, well above any secondary score */

static inline int move_order_key(
    const State* state,
    const Move& m,
    int self,
    int oppn,
    int ply,
    const Move* tt_move
){
    if(tt_move && m == *tt_move){
        return 3 * MOVE_ORDER_TIER;
    }

    int victim = state->piece_at(oppn, m.second.first, m.second.second);
    if(victim){
        int attacker = state->piece_at(self, m.first.first, m.first.second);
        int mvv_lva = PIECE_VALUES[victim] * 16 - PIECE_VALUES[attacker];
        return 2 * MOVE_ORDER_TIER + mvv_lva;
    }

    int piece = state->piece_at(self, m.first.first, m.first.second);
    int hist = (piece > 0 && piece <= 6) ? g_history[piece][m.second.first][m.second.second] : 0;

    if(is_killer(ply, m)){
        return 1 * MOVE_ORDER_TIER + hist;
    }
    return hist;
}

static void order_moves(
    State* state,
    std::vector<Move>& moves,
    int ply,
    const Move* tt_move
){
    int self = state->player;
    int oppn = 1 - self;

    static thread_local std::vector<std::pair<int, Move>> scored;
    scored.clear();
    scored.reserve(moves.size());
    for(auto& m : moves){
        scored.emplace_back(move_order_key(state, m, self, oppn, ply, tt_move), m);
    }

    std::stable_sort(scored.begin(), scored.end(),
        [](const std::pair<int, Move>& a, const std::pair<int, Move>& b){
            return a.first > b.first;
        });

    for(size_t i = 0; i < moves.size(); i++){
        moves[i] = scored[i].second;
    }
}

/* Is `m` a capture in `state`? (destination square holds an opponent piece) */
static inline bool is_capture(const State* state, const Move& m){
    return state->piece_at(1 - state->player, m.second.first, m.second.second) != 0;
}

/* Does the side to move have any piece other than pawns/king? Null-move
 * pruning assumes "passing" can only be at least as good as some real
 * move would be for the side that's NOT moving, which can fail in
 * zugzwang-prone king-and-pawn endgames (where having to move at all is
 * a disadvantage). We simply disable null-move pruning in that specific
 * situation rather than try to detect zugzwang precisely. */
static inline bool has_major_or_minor_piece(const State* state, int player){
    for(int r = 0; r < BOARD_H; r++){
        for(int c = 0; c < BOARD_W; c++){
            int piece = state->piece_at(player, r, c);
            if(piece != 0 && piece != 1 && piece != 6){ /* not empty, not pawn, not king */
                return true;
            }
        }
    }
    return false;
}


/*============================================================
 * king_in_check() — is `player`'s king currently attacked?
 *
 * This game uses a king-capture win model with no separate "check"
 * legality rule, so nothing stops the side to move from walking
 * past (or failing to notice) a threat to its own king other than
 * the search actually looking deep enough to see the capture. That
 * is fine for the main search (it explores every legal reply), but
 * quiescence() only ever looks at *captures* -- if our king is
 * attacked and the only way out is a non-capturing move (stepping
 * the king away, blocking, etc.), quiescence can't find it and we
 * fall back on the static eval exactly when it matters most.
 *
 * Used for two standard, well-bounded fixes below: (1) a one-ply
 * "check extension" in pvs() so a position where the side to move
 * is in check gets a full extra ply of real search instead of
 * dropping into quiescence early, and (2) quiescence() searching
 * *all* legal moves (not just captures) on the rare nodes where the
 * side to move is in check.
 *
 * Implemented entirely via the public `piece_at()` interface (no
 * state.cpp/state.hpp changes needed) -- mirrors normal chess attack
 * patterns for this 6x5 board, early-returning as soon as any
 * attacker is found.
 *============================================================*/
static bool king_in_check(const State* state, int player){
    int kr = -1, kc = -1;
    for(int r = 0; r < BOARD_H && kr < 0; r++){
        for(int c = 0; c < BOARD_W; c++){
            if(state->piece_at(player, r, c) == 6){
                kr = r; kc = c;
                break;
            }
        }
    }
    if(kr < 0){
        return false; /* no king on board -- shouldn't happen mid-game */
    }

    int opp = 1 - player;

    /* Pawn attacks: an opponent pawn attacks diagonally toward `player`'s
     * side of the board. Player 0 (white) pawns advance toward row 0, so
     * they attack from row+1; player 1 (black) pawns advance toward
     * row BOARD_H-1, so they attack from row-1. */
    int pawn_from_dr = (opp == 0) ? 1 : -1;
    for(int dc = -1; dc <= 1; dc += 2){
        int pr = kr + pawn_from_dr, pc = kc + dc;
        if(pr >= 0 && pr < BOARD_H && pc >= 0 && pc < BOARD_W
           && state->piece_at(opp, pr, pc) == 1){
            return true;
        }
    }

    /* Knight attacks */
    static const int kn_dr[8] = {1, 1, -1, -1, 2, 2, -2, -2};
    static const int kn_dc[8] = {2, -2, 2, -2, 1, -1, 1, -1};
    for(int i = 0; i < 8; i++){
        int r = kr + kn_dr[i], c = kc + kn_dc[i];
        if(r >= 0 && r < BOARD_H && c >= 0 && c < BOARD_W
           && state->piece_at(opp, r, c) == 3){
            return true;
        }
    }

    /* King adjacency (kings can capture kings in this ruleset too) */
    for(int dr = -1; dr <= 1; dr++){
        for(int dc = -1; dc <= 1; dc++){
            if(dr == 0 && dc == 0){ continue; }
            int r = kr + dr, c = kc + dc;
            if(r >= 0 && r < BOARD_H && c >= 0 && c < BOARD_W
               && state->piece_at(opp, r, c) == 6){
                return true;
            }
        }
    }

    /* Sliding attacks: rook/queen along ranks+files, bishop/queen on
     * diagonals. Stop at the first piece found in each direction. */
    static const int rk_dr[4] = {0, 0, 1, -1};
    static const int rk_dc[4] = {1, -1, 0, 0};
    for(int i = 0; i < 4; i++){
        int r = kr + rk_dr[i], c = kc + rk_dc[i];
        while(r >= 0 && r < BOARD_H && c >= 0 && c < BOARD_W){
            if(state->piece_at(player, r, c)){
                break; /* own piece blocks the line */
            }
            int op = state->piece_at(opp, r, c);
            if(op){
                if(op == 2 || op == 5){ return true; } /* rook or queen */
                break;
            }
            r += rk_dr[i]; c += rk_dc[i];
        }
    }
    static const int bs_dr[4] = {1, 1, -1, -1};
    static const int bs_dc[4] = {1, -1, 1, -1};
    for(int i = 0; i < 4; i++){
        int r = kr + bs_dr[i], c = kc + bs_dc[i];
        while(r >= 0 && r < BOARD_H && c >= 0 && c < BOARD_W){
            if(state->piece_at(player, r, c)){
                break;
            }
            int op = state->piece_at(opp, r, c);
            if(op){
                if(op == 4 || op == 5){ return true; } /* bishop or queen */
                break;
            }
            r += bs_dr[i]; c += bs_dc[i];
        }
    }

    return false;
}


/*============================================================
 * Quiescence search
 *
 * Called once the normal search depth is exhausted. Instead of
 * returning evaluate() directly (which can badly misjudge a
 * position mid-capture-sequence — the "horizon effect"), we keep
 * searching captures only until the position is "quiet", and use
 * a stand-pat score as both the leaf value and the lower bound
 * (we are never forced to capture, so we can always choose to
 * stop and take the static score instead).
 *============================================================*/
int Submission::quiescence(
    State *state,
    int alpha,
    int beta,
    GameHistory& history,
    int ply,
    int qply,
    SearchContext& ctx,
    const SubmissionParams& p
){
    ctx.nodes++;
    if(ply > ctx.seldepth){
        ctx.seldepth = ply;
    }
    if(time_budget_exceeded(ctx)){
        return state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);
    }

    if(state->legal_actions.empty() && state->game_state == UNKNOWN){
        state->get_legal_actions();
    }

    if(state->game_state == WIN){
        return P_MAX - ply;
    }
    if(state->game_state == DRAW){
        return 0;
    }

    /* Is the side to move's king currently attacked? If so, "doing
     * nothing" (i.e. trusting the static stand-pat score as a safe
     * floor, the way normal quiescence does) is not a sound
     * assumption -- the side to move MUST address the threat, and
     * the only way to find out whether it can is to actually look at
     * every legal reply, not just captures. */
    bool in_check = king_in_check(state, state->player);

    int stand_pat = state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);

    if(!in_check){
        if(stand_pat >= beta){
            return stand_pat;
        }
        if(stand_pat > alpha){
            alpha = stand_pat;
        }
        if(qply >= p.max_quiescence_ply){
            return stand_pat;
        }
    }else if(qply >= p.max_quiescence_ply){
        /* Same cap as the normal capture-only path -- searching all
         * legal moves while in check is more expensive per node, so
         * it gets no *extra* budget on top of the existing tunable
         * limit, only the existing one applied uniformly. */
        return stand_pat;
    }

    std::vector<Move> moves_to_search;
    if(in_check){
        moves_to_search = state->legal_actions;
    }else{
        moves_to_search.reserve(state->legal_actions.size());
        for(auto& m : state->legal_actions){
            if(is_capture(state, m)){
                moves_to_search.push_back(m);
            }
        }
        if(moves_to_search.empty()){
            return stand_pat;
        }
    }
    order_moves(state, moves_to_search, -1, nullptr);

    int best_score = in_check ? M_MAX : stand_pat;

    for(auto& action : moves_to_search){
        if(time_budget_exceeded(ctx)){
            return best_score;
        }

        State* next = state->next_state(action);
        if(next->legal_actions.empty() && next->game_state == UNKNOWN){
            next->get_legal_actions();
        }

        bool same = next->same_player_as_parent();
        int raw = quiescence(next, same ? alpha : -beta, same ? beta : -alpha,
                              history, ply + 1, qply + 1, ctx, p);
        int score = same ? raw : -raw;

        delete next;

        if(score > best_score){
            best_score = score;
        }
        if(score > alpha){
            alpha = score;
        }
        if(alpha >= beta){
            break;
        }
    }

    return best_score;
}


/*============================================================
 * PVS — negamax + alpha-beta + principal variation search
 *============================================================*/
int Submission::pvs(
    State *state,
    int depth,
    int alpha,
    int beta,
    GameHistory& history,
    int ply,
    SearchContext& ctx,
    const SubmissionParams& p,
    bool allow_null,
    int ext_count
){
    ctx.nodes++;
    if(ply > ctx.seldepth){
        ctx.seldepth = ply;
    }
    if(time_budget_exceeded(ctx)){
        return state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);
    }

    if(state->legal_actions.empty() && state->game_state == UNKNOWN){
        state->get_legal_actions();
    }
    if(state->game_state == WIN){
        return P_MAX - ply;
    }
    if(state->game_state == DRAW){
        return 0;
    }
    int rep_score;
    if(state->check_repetition(history, rep_score)){
        return rep_score;
    }

    /* === Check extension ===
     * If the side to move is in check, give this node one extra ply
     * of real, full-width search instead of letting the forced
     * response run off the end of the main search and into
     * quiescence (which, even with the check-evasion handling added
     * above, is still a narrower search than the main loop). Capped
     * via ext_count so a long forcing sequence can't inflate the
     * effective depth without limit -- the wall-clock budget is the
     * final backstop regardless. */
    bool in_check = king_in_check(state, state->player);
    if(in_check && ext_count < 3){
        depth += 1;
        ext_count += 1;
    }

    /* === Transposition table probe ===
     * Conservative by design: we only ever trust a stored EXACT
     * value, and only when it was computed at >= the current depth
     * (so it's at least as informed as a fresh search would be).
     * We deliberately do NOT use LOWERBOUND/UPPERBOUND entries to
     * narrow alpha/beta — a bound proved under one (alpha,beta)
     * window is only safe to reuse for an immediate cutoff under a
     * *different* window in certain careful conditions, and getting
     * that subtly wrong silently corrupts the search (verified by
     * testing against exhaustive minimax). The move-ordering hint
     * from ANY entry (exact or bound) is still always safe to use,
     * since it's just a suggestion, not a score we trust blindly. */
    int orig_alpha = alpha;

    uint64_t h = state->hash();
    const Move* tt_move = nullptr;
    if(p.use_tt){
        TTEntry* tte = tt_probe(h);
        if(tte){
            tt_move = &tte->best_move;
            if(tte->flag == TTFlag::EXACT && tte->depth >= depth){
                return tte->score;
            }
        }
    }

    history.push(state->hash());

    if(depth <= 0){
        int score;
        if(p.use_quiescence){
            score = quiescence(state, alpha, beta, history, ply, 0, ctx, p);
        }else{
            score = state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);
        }
        history.pop(state->hash());
        return score;
    }

    /* === Null-move pruning ===
     * Idea: if we could "pass" (give the opponent a free move) and a
     * reduced-depth search of the resulting position still says the
     * opponent can't do better than beta, then a real move is almost
     * certainly at least that good too — so we can skip the full
     * search of this node entirely. Guarded against the classic
     * failure mode (zugzwang, where passing is illegal but would
     * actually be the best option) by requiring the side to move to
     * have at least one non-pawn, non-king piece, and by never trying
     * two null moves in a row (allow_null). Also skipped near the
     * top of the tree (depth too low to reduce) and when beta is
     * already close to a mate score (reduced-depth null search isn't
     * trustworthy there). */
    if(p.use_null_move && allow_null && !in_check && depth > p.null_move_reduction
       && beta < P_MAX - 1000 && beta > M_MAX + 1000
       && has_major_or_minor_piece(state, state->player)){
        State* null_state = static_cast<State*>(state->create_null_state());
        if(null_state->legal_actions.empty() && null_state->game_state == UNKNOWN){
            null_state->get_legal_actions();
        }
        bool same = null_state->same_player_as_parent();
        int null_depth = depth - 1 - p.null_move_reduction;
        int child_alpha = same ? (beta - 1) : -beta;
        int child_beta  = same ?  beta      : -(beta - 1);
        int raw = pvs(null_state, null_depth, child_alpha, child_beta, history, ply + 1, ctx, p, false, ext_count);
        int null_score = same ? raw : -raw;
        delete null_state;

        if(!time_budget_exceeded(ctx) && null_score >= beta){
            history.pop(state->hash());
            return null_score; /* fail-soft cutoff */
        }
    }

    std::vector<Move> moves = state->legal_actions;
    order_moves(state, moves, ply, tt_move);

    int best_score = M_MAX;
    Move best_local_move = moves[0];
    bool first = true;
    int quiet_index = 0;
    bool any_move_evaluated = false;

    for(auto& action : moves){
        if(time_budget_exceeded(ctx)){
            break;
        }

        State* next = state->next_state(action);
        if(next->legal_actions.empty() && next->game_state == UNKNOWN){
            next->get_legal_actions();
        }

        bool same = next->same_player_as_parent();
        int score;
        bool is_quiet = !is_capture(state, action) && !(tt_move && action == *tt_move);

        if(first){
            int child_alpha = same ? alpha : -beta;
            int child_beta  = same ? beta  : -alpha;
            int raw = pvs(next, depth - 1, child_alpha, child_beta, history, ply + 1, ctx, p, true, ext_count);
            score = same ? raw : -raw;
        }else{
            /* === Late move reductions ===
             * Quiet moves (not a capture, not the TT-hinted move) that
             * sort late in our ordering are, empirically, rarely the
             * best move once ordering is decent. Search them first at
             * a reduced depth with the usual null window; if that
             * reduced search unexpectedly beats alpha, we don't yet
             * trust it (it was a shallower, less accurate look), so we
             * re-search at full depth before deciding whether it also
             * warrants the full PVS re-search below. */
            int reduction = 0;
            if(p.use_lmr && is_quiet && !in_check && depth >= p.lmr_min_depth
               && quiet_index >= p.lmr_min_move_index){
                reduction = (quiet_index >= p.lmr_min_move_index + 4) ? 2 : 1;
                if(reduction >= depth){
                    reduction = depth - 1;
                }
            }

            int child_alpha = same ?  alpha      : -(alpha + 1);
            int child_beta  = same ? (alpha + 1) : -alpha;
            int raw = pvs(next, depth - 1 - reduction, child_alpha, child_beta, history, ply + 1, ctx, p, true, ext_count);
            score = same ? raw : -raw;

            if(reduction > 0 && score > alpha){
                /* Reduced search beat alpha: redo at full depth (still
                 * null window) before trusting it enough to consider
                 * a full-window re-search. */
                raw = pvs(next, depth - 1, child_alpha, child_beta, history, ply + 1, ctx, p, true, ext_count);
                score = same ? raw : -raw;
            }

            if(score > alpha && score < beta){
                /* Scout failed high inside the real window: the move
                 * might actually be the new best, so re-search it
                 * properly with the full window to get an exact value. */
                int re_child_alpha = same ? alpha : -beta;
                int re_child_beta  = same ? beta  : -alpha;
                raw = pvs(next, depth - 1, re_child_alpha, re_child_beta, history, ply + 1, ctx, p, true, ext_count);
                score = same ? raw : -raw;
            }
        }

        delete next;

        any_move_evaluated = true;
        if(is_quiet){
            quiet_index++;
        }

        if(score > best_score){
            best_score = score;
            best_local_move = action;
        }
        if(score > alpha){
            alpha = score;
        }
        if(alpha >= beta){
            if(is_quiet){
                record_killer(ply, action);
                record_history(state, action, depth);
            }
            break;
        }
        first = false;
    }

    if(!any_move_evaluated){
        /* Time ran out before we could evaluate even the first child
         * (can happen if a deep, heavily-extended forcing line burned
         * the whole budget a few levels down before unwinding back up
         * to here). best_score is still its unset M_MAX sentinel at
         * this point -- returning that raw would leak a bogus "this is
         * a forced loss" signal up the tree instead of a real number.
         * Fall back to a real static evaluation, exactly like the
         * time-budget check at the very top of this function does. */
        history.pop(state->hash());
        return state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);
    }

    if(p.use_tt){
        TTFlag flag;
        if(best_score <= orig_alpha){
            flag = TTFlag::UPPERBOUND;
        }else if(best_score >= beta){
            flag = TTFlag::LOWERBOUND;
        }else{
            flag = TTFlag::EXACT;
        }
        tt_store(h, depth, best_score, flag, best_local_move);
    }

    history.pop(state->hash());
    return best_score;
}


/*============================================================
 * Submission — search
 *
 * Root driver. Called once per iterative-deepening depth by
 * ubgi.cpp (always starting at depth==1 for a fresh move — see
 * the time-budget note at the top of this file).
 *
 * Note: Aspiration Windows were tried here and measured to be a
 * net slowdown on this small board (depth 11 on startpos: 1341ms
 * with vs 807ms without) — the crude "redo the whole root loop"
 * retry on a fail-high/low cost more than the narrow window
 * saved, since scores fluctuate enough between iterations on a
 * 6x5 board that aspiration misses are common. Removed.
 *============================================================*/
SearchResult Submission::search(
    State *state,
    int depth,
    GameHistory& history,
    SearchContext& ctx
){
    ctx.reset();
    SubmissionParams p = SubmissionParams::from_map(ctx.params);
    maybe_start_move_clock(depth, ctx.move_time_ms, p);

    SearchResult result;
    result.depth = depth;

    if(!state->legal_actions.size()){
        state->get_legal_actions();
    }

    if(state->game_state == WIN){
        result.best_move = state->legal_actions[0];
        result.score = P_MAX;
        result.nodes = ctx.nodes;
        result.pv = {result.best_move};
        return result;
    }

    std::vector<Move> moves = state->legal_actions;
    uint64_t root_hash = state->hash();
    const Move* tt_move = nullptr;
    if(p.use_tt){
        TTEntry* tte = tt_probe(root_hash);
        if(tte){
            tt_move = &tte->best_move;
        }
    }
    order_moves(state, moves, 0, tt_move);

    /* Safe fallback: always have a legal move to return, even if the
     * very first child search gets interrupted before completing.
     * best_score starts at a sentinel far below any real evaluation
     * so a real (possibly very bad, e.g. forced-loss) searched score
     * always wins the comparison below; we only fall back to a real
     * static eval for the *reported* score if no move was evaluated
     * at all (only possible if our budget had already elapsed when
     * this call started). */
    result.best_move = moves[0];
    bool any_move_evaluated = false;

    int alpha = M_MAX - 10;
    int beta  = P_MAX + 10;
    int orig_alpha = alpha;
    int best_score = M_MAX - 10;
    int move_index = 0;
    int total_moves = (int)moves.size();
    bool first = true;

    for(auto& action : moves){
        if(time_budget_exceeded(ctx)){
            break; /* don't start a move we might not finish evaluating */
        }

        State* next = state->next_state(action);
        if(next->legal_actions.empty() && next->game_state == UNKNOWN){
            next->get_legal_actions();
        }

        bool same = next->same_player_as_parent();
        int score;

        if(first){
            int child_alpha = same ? alpha : -beta;
            int child_beta  = same ? beta  : -alpha;
            int raw = Submission::pvs(next, depth - 1, child_alpha, child_beta, history, 1, ctx, p);
            score = same ? raw : -raw;
        }else{
            int child_alpha = same ?  alpha      : -(alpha + 1);
            int child_beta  = same ? (alpha + 1) : -alpha;
            int raw = Submission::pvs(next, depth - 1, child_alpha, child_beta, history, 1, ctx, p);
            score = same ? raw : -raw;

            if(score > alpha && score < beta){
                int re_child_alpha = same ? alpha : -beta;
                int re_child_beta  = same ? beta  : -alpha;
                raw = Submission::pvs(next, depth - 1, re_child_alpha, re_child_beta, history, 1, ctx, p);
                score = same ? raw : -raw;
            }
        }

        delete next;

        any_move_evaluated = true;
        if(score > best_score){
            best_score = score;
            result.best_move = action;

            if(p.report_partial && ctx.on_root_update){
                ctx.on_root_update({result.best_move, best_score, depth, move_index + 1, total_moves});
            }
        }
        if(score > alpha){
            alpha = score;
        }

        first = false;
        move_index++;
    }

    if(!any_move_evaluated){
        best_score = state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);
    }else if(p.use_tt){
        TTFlag flag = (best_score <= orig_alpha) ? TTFlag::UPPERBOUND : TTFlag::EXACT;
        tt_store(root_hash, depth, best_score, flag, result.best_move);
    }

    result.score = best_score;
    result.seldepth = ctx.seldepth;
    result.nodes = ctx.nodes;
    result.pv = {result.best_move};

    return result;
}


/*============================================================
 * Submission — default_params / param_defs
 *============================================================*/
ParamMap Submission::default_params(){
    return {
        {"UseKPEval", "true"},
        {"UseEvalMobility", "true"},
        {"ReportPartial", "true"},
        {"UseQuiescence", "true"},
        {"MaxQuiescencePly", "8"},
        {"UseTT", "true"},
        {"MoveBudgetMs", "2000"},
        {"UseNullMove", "true"},
        {"NullMoveReduction", "3"},
        {"UseLMR", "true"},
        {"LMRMinDepth", "3"},
        {"LMRMinMoveIndex", "3"},
    };
}

std::vector<ParamDef> Submission::param_defs(){
    return {
        {"UseKPEval", ParamDef::CHECK, "true"},
        {"UseEvalMobility", ParamDef::CHECK, "true"},
        {"ReportPartial", ParamDef::CHECK, "true"},
        {"UseQuiescence", ParamDef::CHECK, "true"},
        {"MaxQuiescencePly", ParamDef::SPIN, "8", 0, 32},
        {"UseTT", ParamDef::CHECK, "true"},
        {"MoveBudgetMs", ParamDef::SPIN, "2000", 50, 60000},
        {"UseNullMove", ParamDef::CHECK, "true"},
        {"NullMoveReduction", ParamDef::SPIN, "3", 1, 5},
        {"UseLMR", ParamDef::CHECK, "true"},
        {"LMRMinDepth", ParamDef::SPIN, "3", 1, 10},
        {"LMRMinMoveIndex", ParamDef::SPIN, "3", 0, 20},
    };
}