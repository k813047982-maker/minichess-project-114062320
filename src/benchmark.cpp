#include <iostream>
#include <chrono>
#include <iomanip>

#include "config.hpp"
#include "state.hpp"
#include "./policy/registry.hpp"
#include "./policy/game_history.hpp"


/* === Test position === */

struct TestPos {
    const char* name;
    State* state;
};


/* === Timing helper === */

static double time_search(
    const AlgoEntry& algo,
    const TestPos& pos,
    int depth,
    double prev_ms
) {
    if(prev_ms > 5000.0){
        return -1.0;
    }
    State* state = new State(*pos.state);
    state->get_legal_actions();
    SearchContext ctx;
    ctx.params = algo.default_params;
    GameHistory history;
    auto t0 = std::chrono::high_resolution_clock::now();
    algo.search(state, depth, history, ctx);
    auto t1 = std::chrono::high_resolution_clock::now();
    double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    delete state;
    return ms;
}


/* === Build test positions by playing random opening moves === */

static State* play_random_moves(int n_moves) {
    State* state = new State();
    state->get_legal_actions();
    for(int i = 0; i < n_moves; i++){
        if(state->game_state == WIN || state->game_state == DRAW){
            break;
        }
        if(state->legal_actions.empty()){
            break;
        }
        int idx = rand() % (int)state->legal_actions.size();
        State* next = state->next_state(state->legal_actions[idx]);
        delete state;
        state = next;
        state->get_legal_actions();
    }
    return state;
}


/* === Main === */

int main(int argc, char* argv[]) {
    srand(42);

    /* Optional label from command line */
    const char* label = (argc > 1) ? argv[1] : "";

    /* Get game name from State */
    State temp_state;
    std::cout << "Game: " << temp_state.game_name() << " ("
        << BOARD_H << "x" << BOARD_W << ")\n";

    /* === Test positions === */
    constexpr int NUM_POS = 3;
    TestPos positions[NUM_POS];

    /* 1. Starting position */
    positions[0].name = "init";
    positions[0].state = new State();
    positions[0].state->get_legal_actions();

    /* 2. Midgame: play some random opening moves */
    positions[1].name = "mid";
    positions[1].state = play_random_moves(10);

    /* 3. Late game: more random moves */
    positions[2].name = "late";
    positions[2].state = play_random_moves(20);

    /* === Algorithm table from registry === */
    const auto& algos = get_algo_table();
    int max_depth = 6;

    if(label[0]){
        std::cout << "[ " << label << " ]\n";
    }

    for(int p = 0; p < NUM_POS; p++){
        std::cout << "\n=== " << positions[p].name << " ===\n";

        /* Header */
        std::cout << std::setw(12) << "algo";
        for(int d = 1; d <= max_depth; d++){
            std::cout << " | " << std::setw(9) << ("d=" + std::to_string(d));
        }
        std::cout << "\n";
        std::cout << std::string(12, '-');
        for(int d = 1; d <= max_depth; d++){
            std::cout << "-+-" << std::string(9, '-');
        }
        std::cout << "\n";

        /* Each algorithm */
        for(const auto& algo : algos){
            std::cout << std::setw(12) << algo.name;
            double prev = 0;
            for(int d = 1; d <= max_depth; d++){
                double ms = time_search(algo, positions[p], d, prev);
                if(ms < 0){
                    std::cout << " | " << std::setw(9) << "-";
                } else {
                    std::cout << " | " << std::setw(7) << std::fixed
                        << std::setprecision(1) << ms << "ms";
                    prev = ms;
                }
            }
            std::cout << "\n";
        }
    }

    /* Clean up */
    for(int p = 0; p < NUM_POS; p++){
        delete positions[p].state;
    }

    std::cout << std::endl;
    return 0;
}
