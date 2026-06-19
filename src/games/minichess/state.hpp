#pragma once
#include <string>
#include <cstdlib>
#include <vector>
#include <utility>

#include "base_state.hpp"
#include "config.hpp"


class Board {
public:
    char board[2][BOARD_H][BOARD_W] = {{
        {0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0},
        {1, 1, 1, 1, 1},
        {2, 3, 4, 5, 6},
    }, {
        {6, 5, 4, 3, 2},
        {1, 1, 1, 1, 1},
        {0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0},
    }};
};


class State : public BaseState {
public:
    Board board;
    int score = 0;
    mutable uint64_t zobrist_hash = 0;
    mutable bool zobrist_valid = false;

    State(){}
    State(int player){
        this->player = player;
    }
    State(Board board): board(board){}
    State(Board board, int player): board(board){
        this->player = player;
    }

    int evaluate(
        bool use_kp_eval = true,
        bool use_mobility = true,
        const GameHistory* history = nullptr
    ) override;
    State* next_state(const Move& move) override;
    void get_legal_actions() override;
    void get_legal_actions_naive();
    void get_legal_actions_bitboard();
    std::string encode_output() const override;
    std::string encode_state();

    bool check_repetition(const GameHistory& history, int& out_score) const override;
    BaseState* create_null_state() const override;

    int piece_at(int player, int row, int col) const override {
        return board.board[player][row][col];
    }
    uint64_t hash() const override {
        if(!zobrist_valid){
            zobrist_hash = compute_hash_full();
            zobrist_valid = true;
        }
        return zobrist_hash;
    }
    uint64_t compute_hash_full() const;
    std::string cell_display(int row, int col) const override;

    std::string encode_board() const override;
    void decode_board(const std::string& s, int side_to_move) override;

    /* === Game description === */
    int board_h() const override { return BOARD_H; }
    int board_w() const override { return BOARD_W; }
    const char* game_name() const override { return "MiniChess"; }
};
