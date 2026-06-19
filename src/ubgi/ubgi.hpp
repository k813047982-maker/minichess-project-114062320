#pragma once
#include "state.hpp"
#include <string>

namespace ubgi {
    /* === Move conversion: "a6c5" format === */
    std::string move_to_str(const Move& m);
    Move str_to_move(const std::string& s);

    /* === Board position from move list === */
    void set_position(const std::string& line, Board& board, int& player, int& step);

    /* === Main UBGI loop === */
    void loop();
}
