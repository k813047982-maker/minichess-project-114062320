#include <utility>
#include <chrono>
#include "state.hpp"
#include "minimax.hpp"


/*============================================================
 * Self-contained time guard (see submission.cpp for the full
 * rationale — only src/policy/ may be modified, so this cannot
 * rely on anything added to search_types.hpp/ubgi.cpp; ctx.stop
 * is only ever read here, never written, to avoid colliding with
 * ubgi.cpp's "stop" == "externally cancelled" semantics).
 *============================================================*/
static std::chrono::steady_clock::time_point g_mm_deadline =
    std::chrono::steady_clock::time_point::max();

static inline void mm_maybe_start_clock(int depth, int64_t external_movetime_ms, int budget_ms){
    if(depth <= 1){
        int64_t effective_ms = (external_movetime_ms > 0) ? external_movetime_ms : (int64_t)budget_ms;
        auto margin = std::chrono::milliseconds(std::min<int64_t>(150, effective_ms / 10));
        g_mm_deadline = std::chrono::steady_clock::now()
            + std::chrono::milliseconds(effective_ms) - margin;
    }
}

static inline bool mm_time_up(SearchContext& ctx){
    if(ctx.stop){
        return true;
    }
    if((ctx.nodes & 0x3FFULL) != 0){
        return false;
    }
    return std::chrono::steady_clock::now() >= g_mm_deadline;
}


/*============================================================
 * MiniMax — eval_ctx
 *
 * Negamax without pruning. Caller manages memory.
 *============================================================*/
int MiniMax::eval_ctx(
    State *state,
    int depth,
    GameHistory& history,
    int ply,
    SearchContext& ctx,
    const MMParams& p
){
    ctx.nodes++;
    if(ply > ctx.seldepth){
        ctx.seldepth = ply;
    }
    if(mm_time_up(ctx)){
        return state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);
    }

    /* === Lazy move generation (sets game_state) === */
    if(state->legal_actions.empty() && state->game_state == UNKNOWN){
        state->get_legal_actions();
    }

    /* === Terminal / leaf checks === */

    // [ Hackathon TODO 3-1 ]
    // return the score for a winning terminal state
    // Hint: prefer faster wins by using ply.
    if(state->game_state == WIN){
        return P_MAX - ply;
    }

    if(state->game_state == DRAW){
        return 0;
    }

    /* === Repetition check (game-specific) === */
    int rep_score;
    if(state->check_repetition(history, rep_score)){
        return rep_score;
    }
    history.push(state->hash());

    if(depth <= 0){
        int score = state->evaluate(
            p.use_kp_eval, p.use_eval_mobility, &history
        ); 
        history.pop(state->hash());
        return score;
    }

    /* === Negamax loop === */
    int best_score = M_MAX;

    for(auto& action : state->legal_actions){
        // [ Hackathon TODO 3-2 ]
        // create the child state after applying action
        if(mm_time_up(ctx)){
            break;
        }
        State* next = state->next_state(action);
        if(next->legal_actions.empty() && next->game_state == UNKNOWN){
            next->get_legal_actions();
        }

        bool same = next->same_player_as_parent();

        // [Hackathon TODO 3-3]
        // search the child one level deeper
        int raw = eval_ctx(next, depth - 1, history, ply + 1, ctx, p);

        // [Hackathon TODO 3-4]
        // convert raw to the current player's perspective.
        int score = same ? raw : -raw;

        delete next;

        // [ Hackathon TODO 3-5 ]
        // update best_score if this child is better.
        if(score > best_score){
            best_score = score;
        }

    }

    history.pop(state->hash());
    return best_score;
}


/*============================================================
 * MiniMax — search
 *
 * Iterate legal moves, call eval_ctx, return SearchResult.
 *============================================================*/
SearchResult MiniMax::search(
    State *state,
    int depth,
    GameHistory& history,
    SearchContext& ctx
){
    ctx.reset();
    MMParams p = MMParams::from_map(ctx.params);
    mm_maybe_start_clock(depth, ctx.move_time_ms, p.move_budget_ms);
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

    int best_score = M_MAX - 10;
    int move_index = 0;
    int total_moves = (int)state->legal_actions.size();
    result.best_move = state->legal_actions[0]; /* safe fallback */
    bool any_move_evaluated = false;

    for(auto& action : state->legal_actions){
        /* [ Hackathon TODO 4-1 ]
         * search this move like TODO 3, but starting from the root */
        if(mm_time_up(ctx)){
            break; /* don't start a move we might not finish evaluating */
        }
        State* next = state->next_state(action);
        if(next->legal_actions.empty() && next->game_state == UNKNOWN){
            next->get_legal_actions();
        }

        bool same = next->same_player_as_parent();
        int raw = MiniMax::eval_ctx(next, depth - 1, history, 1, ctx, p);
        int score = same ? raw : -raw;

        delete next;

        any_move_evaluated = true;
            if(score > best_score){
                // [ Hackathon TODO 4-2 ]
                // keep this move if it is the best so far
                best_score = score;
                result.best_move = action;

                if(p.report_partial && ctx.on_root_update){
                   ctx.on_root_update({result.best_move, best_score, depth, move_index + 1, total_moves});
                }
            }  
        move_index++;
    }

    if(!any_move_evaluated){
        best_score = state->evaluate(p.use_kp_eval, p.use_eval_mobility, &history);
    }

    // [ Hackathon TODO 4-3 ]
    // update result and return
    result.score = best_score;
    result.seldepth = ctx.seldepth;
    result.nodes = ctx.nodes;
    result.pv = {result.best_move};

        return result;
} 


/*============================================================
 * MiniMax — default_params / param_defs
 *============================================================*/
ParamMap MiniMax::default_params(){
    return {
        {"UseKPEval", "true"},
        {"UseEvalMobility", "true"},
        {"ReportPartial", "true"},
        {"MoveBudgetMs", "2000"},
    };
}

std::vector<ParamDef> MiniMax::param_defs(){
    return {
        {"UseKPEval", ParamDef::CHECK, "true"},
        {"UseEvalMobility", ParamDef::CHECK, "true"},
        {"ReportPartial", ParamDef::CHECK, "true"},
        {"MoveBudgetMs", ParamDef::SPIN, "2000", 50, 60000},
    };
}