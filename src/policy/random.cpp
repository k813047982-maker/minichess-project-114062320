#include <cstdlib>
#include "state.hpp"
#include "random.hpp"


/*============================================================
 * Random — search
 *
 * Pick a uniformly random legal move.
 *============================================================*/
SearchResult Random::search(
    State *state,
    int depth,
    GameHistory& history,
    SearchContext& ctx
){
    (void)history;
    ctx.reset();
    SearchResult result;
    result.depth = 1;

    if(!state->legal_actions.size()){
        state->get_legal_actions();
    }

    auto actions = state->legal_actions;
    if(actions.empty()){
        result.best_move = Move();
        return result;
    }


    int idx = (rand() + depth) % actions.size();


    result.best_move = actions[idx];
    result.score = 0;
    result.nodes = 1;
    result.pv = {result.best_move};
    return result;
}


/*============================================================
 * Random — default_params / param_defs
 *============================================================*/
ParamMap Random::default_params(){
    return {};
}

std::vector<ParamDef> Random::param_defs(){
    return {};
}
