#pragma once
#include "base_state.hpp"
#include "search_params.hpp"
#include <vector>
#include <cstdint>
#include <functional>

class State;

struct RootUpdate {
    Move best_move;
    int score;
    int depth;
    int move_number;
    int total_moves;
};

struct SearchContext {
    uint64_t nodes = 0;
    int seldepth = 0;
    bool stop = false;
    ParamMap params;
    std::function<void(const RootUpdate&)> on_root_update;

    /* Wall-clock budget (ms) for the *entire* current move's thinking,
     * across all iterative-deepening depths, exactly as given by the
     * UBGI "go movetime <ms>" command (0 means no external time limit
     * was given for this go -- e.g. "go depth N" or "go infinite").
     * Set once by ubgi.cpp's cmd_go() before the search thread starts;
     * algorithms read this instead of guessing/hard-coding a per-move
     * budget, so they actually honor whatever time control a match
     * harness (GUI, CLI, or an opponent's launcher) imposes. */
    int64_t move_time_ms = 0;

    void reset(){
        nodes = 0;
        seldepth = 0;
    }
};

struct SearchResult {
    Move best_move;
    int score = 0;
    int depth = 0;
    int seldepth = 0;
    uint64_t nodes = 0;
    double time_ms = 0;
    std::vector<Move> pv;
};