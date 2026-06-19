#pragma once
#include "search_types.hpp"
#include "game_history.hpp"

/*============================================================
 * Submission — PVS (negamax + alpha-beta + principal variation
 * search) with quiescence search at horizon nodes, a
 * transposition table, and killer-move/history-heuristic move
 * ordering.
 *
 * IMPORTANT — time budget is fully self-contained:
 * Only files under src/policy/ may be modified for this
 * assignment, so this code cannot rely on any change to
 * SearchContext (src/search_types.hpp) or to the UBGI driver
 * (src/ubgi/ubgi.cpp). Both of those are used exactly as
 * provided. In particular: ubgi.cpp calls search() once per
 * iterative-deepening depth and lets it run to completion; the
 * only thing that can stop a single depth's search partway is
 * either an externally-set ctx.stop (a real `stop`/`quit`
 * command — see base_state.hpp/ubgi.cpp) or this file's own
 * internal wall-clock tracking below. We deliberately never set
 * ctx.stop ourselves for our own time-budget reasons: ubgi.cpp's
 * `alive()` helper treats ctx.stop as "this whole search was
 * externally cancelled, suppress the final bestmove" — so if we
 * repurposed it to mean "our own soft budget elapsed", a normal,
 * expected soft-timeout would silently swallow the engine's
 * output. Instead, time_budget_exceeded() is a pure, read-only
 * check that just makes pvs()/quiescence() return their current
 * best-so-far value early, exactly like running out of depth.
 *============================================================*/

struct SubmissionParams {
    bool use_kp_eval        = true;
    bool use_eval_mobility  = true;
    bool report_partial     = true;
    bool use_quiescence     = true;
    int  max_quiescence_ply = 8;    // hard cap on quiescence extension depth
    bool use_tt              = true; // transposition table + killer/history move ordering
    int  move_budget_ms      = 2000; // self-imposed wall-clock budget per move (see header note above)
    bool use_null_move       = true; // null-move pruning
    int  null_move_reduction = 3;    // R: depth reduction applied to the null-move search
    bool use_lmr             = true; // late move reductions
    int  lmr_min_depth       = 3;    // only reduce when depth >= this
    int  lmr_min_move_index  = 3;    // only reduce moves at/after this index (0-based) among quiet moves

    static SubmissionParams from_map(const ParamMap& m){
        SubmissionParams p;
        p.use_kp_eval        = param_bool(m, "UseKPEval", true);
        p.use_eval_mobility  = param_bool(m, "UseEvalMobility", true);
        p.report_partial     = param_bool(m, "ReportPartial", true);
        p.use_quiescence     = param_bool(m, "UseQuiescence", true);
        p.max_quiescence_ply = param_int(m, "MaxQuiescencePly", 8);
        p.use_tt             = param_bool(m, "UseTT", true);
        p.move_budget_ms     = param_int(m, "MoveBudgetMs", 2000);
        p.use_null_move      = param_bool(m, "UseNullMove", true);
        p.null_move_reduction = param_int(m, "NullMoveReduction", 3);
        p.use_lmr             = param_bool(m, "UseLMR", true);
        p.lmr_min_depth        = param_int(m, "LMRMinDepth", 3);
        p.lmr_min_move_index   = param_int(m, "LMRMinMoveIndex", 3);
        return p;
    }
};

class Submission{
public:
    /* Quiescence search: only explores captures (and king-capture wins)
     * past the normal horizon, to avoid the horizon effect. Returns a
     * score from the side-to-move's perspective. */
    static int quiescence(
        State *state,
        int alpha,
        int beta,
        GameHistory& history,
        int ply,
        int qply,
        SearchContext& ctx,
        const SubmissionParams& p
    );

    /* PVS: negamax with alpha-beta pruning, principal variation search
     * (full-window search for the first move, null-window scout +
     * re-search for the rest), MVV-LVA + killer-move + history-heuristic
     * move ordering, a transposition table for cross-iteration and
     * cross-branch position reuse, null-move pruning, late move
     * reductions, and a one-ply check extension (see king_in_check() in
     * submission.cpp). `allow_null` disables a second consecutive null
     * move (passed false for the child of a null-move search).
     * `ext_count` tracks how many check extensions have already been
     * applied along this line, so a long forcing sequence can't inflate
     * the effective search depth without limit. */
    static int pvs(
        State *state,
        int depth,
        int alpha,
        int beta,
        GameHistory& history,
        int ply,
        SearchContext& ctx,
        const SubmissionParams& p,
        bool allow_null = true,
        int ext_count = 0
    );

    static SearchResult search(
        State *state,
        int depth,
        GameHistory& history,
        SearchContext& ctx
    );

    /* Clear the transposition table and killer/history move-ordering
     * tables. Optional housekeeping — entries are always validated
     * against the full position hash before use, so stale entries are
     * never a correctness risk, only a (harmless) wasted lookup. */
    static void clear_tables();

    static ParamMap default_params();
    static std::vector<ParamDef> param_defs();
};