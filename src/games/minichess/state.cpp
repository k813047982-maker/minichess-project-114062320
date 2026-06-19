#include <iostream>
#include <sstream>
#include <cstdint>
#include <cstdlib>

#include "./state.hpp"
#include "config.hpp"
#include "../../policy/game_history.hpp"


/*============================================================
 * KP (King-Piece) Evaluation tables
 *
 * Always compiled. Toggled at runtime via use_kp_eval param.
 *============================================================*/

// KP material (10x scale for fine positional granularity)
static const int kp_material[7] = {0, 20, 60, 70, 80, 200, 1000};

// Material-only (simple scale)
static const int simple_material[7] = {0, 2, 6, 7, 8, 20, 100};

// Piece-Square Tables (white perspective, mirror for black)
static const int pst[6][BOARD_H][BOARD_W] = {
    // Pawn
    {{ 0,  0,  0,  0,  0}, {15, 15, 15, 15, 15}, { 4,  6, 10,  6,  4},
     { 2,  4,  6,  4,  2}, { 0,  2,  2,  2,  0}, { 0,  0,  0,  0,  0}},
    // Rook
    {{ 2,  2,  2,  2,  2}, { 4,  4,  4,  4,  4}, { 0,  0,  2,  0,  0},
     { 0,  0,  2,  0,  0}, { 0,  0,  2,  0,  0}, { 0,  0,  0,  0,  0}},
    // Knight
    {{-4, -2,  0, -2, -4}, {-2,  2,  4,  2, -2}, { 0,  4,  6,  4,  0},
     { 0,  4,  6,  4,  0}, {-2,  2,  4,  2, -2}, {-4, -2,  0, -2, -4}},
    // Bishop
    {{-2,  0,  0,  0, -2}, { 0,  3,  4,  3,  0}, { 0,  4,  4,  4,  0},
     { 0,  4,  4,  4,  0}, { 0,  3,  4,  3,  0}, {-2,  0,  0,  0, -2}},
    // Queen
    {{-2,  0,  2,  0, -2}, { 0,  2,  4,  2,  0}, { 0,  4,  6,  4,  0},
     { 0,  4,  6,  4,  0}, { 0,  2,  4,  2,  0}, {-2,  0,  2,  0, -2}},
    // King
    {{-8, -8, -8, -8, -8}, {-4, -4, -4, -4, -4}, {-4, -4, -4, -4, -4},
     {-4, -4, -4, -4, -4}, { 4,  4,  0,  4,  4}, { 6,  6,  2,  6,  6}},
};

// King tropism weights
static const int tropism_w[7] = {0, 0, 3, 3, 2, 5, 0};

static int king_tropism(
    int piece_type,
    int pr, int pc,
    int ekr, int ekc
){
    int dist = std::max(std::abs(pr - ekr), std::abs(pc - ekc));
    if(dist <= 2){
        return tropism_w[piece_type] * (3 - dist);
    }
    return 0;
}


/*============================================================
 * Lightweight pseudo-mobility counter for evaluate()
 *
 * Defined further below (next to the bitboard tables it reuses);
 * forward-declared here so evaluate() can call it without paying
 * for a heap-allocated State + full get_legal_actions() just to
 * count the opponent's pseudo-legal moves. See the definition for
 * the full rationale (it also fixes a king-safety scoring bug).
 *============================================================*/
static int count_pseudo_mobility(const Board& board, int player);


/*============================================================
 * evaluate() — runtime-selectable eval strategy
 *============================================================*/

int State::evaluate(
    bool use_kp_eval,
    bool use_mobility,
    const GameHistory* history
){
    (void)history; // just to suppress warning

    // [ Hackathon TODO 1-1 ]
    // if in win state, return max score(you can check base_state.hpp for max score)
    if(this->game_state == WIN){
        return P_MAX;
    }

    auto self_board = this->board.board[this->player];
    auto oppn_board = this->board.board[1 - this->player];
    int self_score = 0, oppn_score = 0;

    if(use_kp_eval){
        /* === KP eval: material + PST + tropism === */

        int self_kr = -1, self_kc = -1;
        int oppn_kr = -1, oppn_kc = -1;
        // [ Hackathon TODO 1-3 ]
        // get the position for player's king and opponent's king
        for(int r = 0; r < BOARD_H; r++){
            for(int c = 0; c < BOARD_W; c++){
                if(self_board[r][c] == 6){
                    self_kr = r; self_kc = c;
                }
                if(oppn_board[r][c] == 6){
                    oppn_kr = r; oppn_kc = c;
                }
            }
        }

        // [ Hackathon TODO 1-4 ]
        // sum player/opponent pieces' value and add to score
        // if enemy king is still on the board, you should also call king_tropism for your pieces and add the value to score
        // king_tropism is already given above
        for(int r = 0; r < BOARD_H; r++){
            for(int c = 0; c < BOARD_W; c++){
                int piece = self_board[r][c];
                if(piece){
                    int pr = (this->player == 0) ? r : (BOARD_H - 1 - r);
                    self_score += kp_material[piece] + pst[piece - 1][pr][c];
                    if(oppn_kr != -1){
                        self_score += king_tropism(piece, r, c, oppn_kr, oppn_kc);
                    }
                }

                int opiece = oppn_board[r][c];
                if(opiece){
                    int pr = (this->player == 0) ? (BOARD_H - 1 - r) : r;
                    oppn_score += kp_material[opiece] + pst[opiece - 1][pr][c];
                    if(self_kr != -1){
                        oppn_score += king_tropism(opiece, r, c, self_kr, self_kc);
                    }
                }
            }
        }

    }else{
        /* === Simple material-only eval === */

        // [ Hackathon TODO 1-2 ]
        // Simply add each piece's value to score
        for(int r = 0; r < BOARD_H; r++){
            for(int c = 0; c < BOARD_W; c++){
                if(self_board[r][c]){
                    self_score += simple_material[(int)self_board[r][c]];
                }
                if(oppn_board[r][c]){
                    oppn_score += simple_material[(int)oppn_board[r][c]];
                }
            }
        }

    }

    int bonus = 0;

    /* === Mobility bonus === */
    if(use_mobility){
        // [ Hackathon TODO 1-5 ]
        // you can calculate mobility by legal actions size
        // bonus += 2 * (self_mobility - oppn_mobility);
        int self_mobility = (int)this->legal_actions.size();
        /* Was: create_null_state() + get_legal_actions() -- heap-allocates
         * a whole State and runs full move generation just to count moves,
         * on EVERY evaluate() call (i.e. every quiescence node). It was
         * also subtly wrong: get_legal_actions_bitboard() returns early
         * with just 1 move the moment it finds a king-capture, so if our
         * king happened to be attacked, the "opponent's free move" move
         * count collapsed to 1 instead of the real mobility figure --
         * exactly when an accurate mobility term matters most. Replaced
         * with a direct popcount over the same bitboard tables: no
         * allocation, no early-exit distortion, same numbers in every
         * position where the old code wasn't already wrong. */
        int oppn_mobility = count_pseudo_mobility(this->board, 1 - this->player);
        bonus += 2 * (self_mobility - oppn_mobility);
    }

    return self_score - oppn_score + bonus;
}



/*============================================================
 * Zobrist hash for transposition table
 *============================================================*/
static uint64_t zobrist_piece[2][7][BOARD_H][BOARD_W];
static uint64_t zobrist_side;
static bool zobrist_ready = false;

static void init_zobrist(){
    uint64_t s = 0x7A35C9D1E4F02B68ULL;
    auto rand64 = [&s]() -> uint64_t {
        s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s;
    };
    for(int p = 0; p < 2; p++){
        for(int t = 0; t < 7; t++){
            for(int r = 0; r < BOARD_H; r++){
                for(int c = 0; c < BOARD_W; c++){
                    zobrist_piece[p][t][r][c] = rand64();
                }
            }
        }
    }
    zobrist_side = rand64();
    zobrist_ready = true;
}

uint64_t State::compute_hash_full() const{
    if(!zobrist_ready){
        init_zobrist();
    }
    uint64_t h = 0;
    for(int p = 0; p < 2; p++){
        for(int r = 0; r < BOARD_H; r++){
            for(int c = 0; c < BOARD_W; c++){
                int piece = this->board.board[p][r][c];
                if(piece){
                    h ^= zobrist_piece[p][piece][r][c];
                }
            }
        }
    }
    if(this->player){
        h ^= zobrist_side;
    }
    return h;
}


/**
 * @brief return next state after the move
 *
 * @param move
 * @return State*
 */
State* State::next_state(const Move& move){
    if(!zobrist_ready){ init_zobrist(); }

    Board next = this->board;
    Point from = move.first, to = move.second;
    int p = this->player;
    int opp = 1 - p;

    int8_t orig_piece = next.board[p][from.first][from.second];
    int8_t moved = orig_piece;
    //promotion for pawn
    if(moved == 1 && (to.first==BOARD_H-1 || to.first==0)){
        moved = 5;
    }

    /* Incremental hash update */
    uint64_t h = this->hash();
    h ^= zobrist_side;  /* toggle side to move */

    /* XOR out piece from source */
    h ^= zobrist_piece[p][orig_piece][from.first][from.second];

    /* XOR out captured piece at destination */
    int8_t captured = next.board[opp][to.first][to.second];
    if(captured){
        h ^= zobrist_piece[opp][captured][to.first][to.second];
        next.board[opp][to.first][to.second] = 0;
    }

    /* XOR in piece at destination */
    h ^= zobrist_piece[p][moved][to.first][to.second];

    next.board[p][from.first][from.second] = 0;
    next.board[p][to.first][to.second] = moved;

    State* ns = new State(next, opp);
    ns->zobrist_hash = h;
    ns->zobrist_valid = true;
    return ns;
}


static const int move_table_rook_bishop[8][7][2] = {
  {{0, 1}, {0, 2}, {0, 3}, {0, 4}, {0, 5}, {0, 6}, {0, 7}},
  {{0, -1}, {0, -2}, {0, -3}, {0, -4}, {0, -5}, {0, -6}, {0, -7}},
  {{1, 0}, {2, 0}, {3, 0}, {4, 0}, {5, 0}, {6, 0}, {7, 0}},
  {{-1, 0}, {-2, 0}, {-3, 0}, {-4, 0}, {-5, 0}, {-6, 0}, {-7, 0}},
  {{1, 1}, {2, 2}, {3, 3}, {4, 4}, {5, 5}, {6, 6}, {7, 7}},
  {{1, -1}, {2, -2}, {3, -3}, {4, -4}, {5, -5}, {6, -6}, {7, -7}},
  {{-1, 1}, {-2, 2}, {-3, 3}, {-4, 4}, {-5, 5}, {-6, 6}, {-7, 7}},
  {{-1, -1}, {-2, -2}, {-3, -3}, {-4, -4}, {-5, -5}, {-6, -6}, {-7, -7}},
};

// [ Hackathon TODO 2-1 ]
// fill the knight move table
static const int move_table_knight[8][2] = {
  {1, 2}, {1, -2}, {-1, 2}, {-1, -2},
  {2, 1}, {2, -1}, {-2, 1}, {-2, -1},
};
static const int move_table_king[8][2] = {
  {1, 0}, {0, 1}, {-1, 0}, {0, -1}, 
  {1, 1}, {1, -1}, {-1, 1}, {-1, -1},
};


/*============================================================
 * Naive move generation (array-based, branch-heavy)
 *============================================================*/
void State::get_legal_actions_naive(){
    this->game_state = NONE;
    std::vector<Move> all_actions;
    all_actions.reserve(64);
    auto self_board = this->board.board[this->player];
    auto oppn_board = this->board.board[1 - this->player];

    int now_piece, oppn_piece;
    for(int i=0; i<BOARD_H; i+=1){
        for(int j=0; j<BOARD_W; j+=1){
            if((now_piece=self_board[i][j])){
                switch(now_piece){
                    case 1: //pawn
                        if(this->player && i<BOARD_H-1){
                            //black
                            if(!oppn_board[i+1][j] && !self_board[i+1][j]){
                                all_actions.push_back(Move(Point(i, j), Point(i+1, j)));
                            }
                            if(j<BOARD_W-1 && (oppn_piece=oppn_board[i+1][j+1])>0){
                                all_actions.push_back(Move(Point(i, j), Point(i+1, j+1)));
                                if(oppn_piece==6){
                                    this->game_state = WIN;
                                    this->legal_actions = all_actions;
                                    return;
                                }
                            }
                            if(j>0 && (oppn_piece=oppn_board[i+1][j-1])>0){
                                all_actions.push_back(Move(Point(i, j), Point(i+1, j-1)));
                                if(oppn_piece==6){
                                    this->game_state = WIN;
                                    this->legal_actions = all_actions;
                                    return;
                                }
                            }
                        }else if(!this->player && i>0){
                            //white
                            if(!oppn_board[i-1][j] && !self_board[i-1][j]){
                                all_actions.push_back(Move(Point(i, j), Point(i-1, j)));
                            }
                            if(j<BOARD_W-1 && (oppn_piece=oppn_board[i-1][j+1])>0){
                                all_actions.push_back(Move(Point(i, j), Point(i-1, j+1)));
                                if(oppn_piece==6){
                                    this->game_state = WIN;
                                    this->legal_actions = all_actions;
                                    return;
                                }
                            }
                            if(j>0 && (oppn_piece=oppn_board[i-1][j-1])>0){
                                all_actions.push_back(Move(Point(i, j), Point(i-1, j-1)));
                                if(oppn_piece==6){
                                    this->game_state = WIN;
                                    this->legal_actions = all_actions;
                                    return;
                                }
                            }
                        }
                        break;

                    case 2: //rook
                    case 4: //bishop
                    case 5: //queen
                        int st, end;
                        switch(now_piece){
                            case 2: st=0; end=4; break; //rook
                            case 4: st=4; end=8; break; //bishop
                            case 5: st=0; end=8; break; //queen
                            default: st=0; end=-1;
                        }
                        for(int part=st; part<end; part+=1){
                            auto move_list = move_table_rook_bishop[part];
                            for(int k=0; k<std::max(BOARD_H, BOARD_W); k+=1){
                                int p[2] = {move_list[k][0] + i, move_list[k][1] + j};

                                if(p[0]>=BOARD_H || p[0]<0 || p[1]>=BOARD_W || p[1]<0){
                                    break;
                                }
                                now_piece = self_board[p[0]][p[1]];
                                if(now_piece){
                                    break;
                                }

                                all_actions.push_back(Move(Point(i, j), Point(p[0], p[1])));

                                oppn_piece = oppn_board[p[0]][p[1]];
                                if(oppn_piece){
                                    if(oppn_piece==6){
                                        this->game_state = WIN;
                                        this->legal_actions = all_actions;
                                        return;
                                    }else{
                                        break;
                                    }
                                };
                            }
                        }
                        break;

                    case 3: //knight
                        // [ Hackathon TODO 2-2 ]
                        // complete knight's movement, you can refer to other pieces' movement
                        for(auto move: move_table_knight){
                            int p[2] = {move[0] + i, move[1] + j};

                            if(p[0]>=BOARD_H || p[0]<0 || p[1]>=BOARD_W || p[1]<0){
                                continue;
                            }
                            now_piece = self_board[p[0]][p[1]];
                            if(now_piece){
                                continue;
                            }

                            all_actions.push_back(Move(Point(i, j), Point(p[0], p[1])));

                            oppn_piece = oppn_board[p[0]][p[1]];
                            if(oppn_piece==6){
                                this->game_state = WIN;
                                this->legal_actions = all_actions;
                                return;
                            }
                        }
                        break;

                    case 6: //king
                        for(auto move: move_table_king){
                            int p[2] = {move[0] + i, move[1] + j};

                            if(p[0]>=BOARD_H || p[0]<0 || p[1]>=BOARD_W || p[1]<0){
                                continue;
                            }
                            now_piece = self_board[p[0]][p[1]];
                            if(now_piece){
                                continue;
                            }

                            all_actions.push_back(Move(Point(i, j), Point(p[0], p[1])));

                            oppn_piece = oppn_board[p[0]][p[1]];
                            if(oppn_piece==6){
                                this->game_state = WIN;
                                this->legal_actions = all_actions;
                                return;
                            }
                        }
                        break;
                }
            }
        }
    }
    this->legal_actions = all_actions;
}


/*============================================================
 * Bitboard move generation
 *
 * 6x5 = 30 squares fit in a uint32_t.
 * Square (r,c) -> bit index r*5+c.
 * Precomputed attack masks for leapers (knight, king, pawn).
 * Bit-scan loop (__builtin_ctz) replaces nested array iteration.
 *============================================================*/
#define BB_SQ(r, c)  ((r) * BOARD_W + (c))
#define BB_ROW(sq)   ((sq) / BOARD_W)
#define BB_COL(sq)   ((sq) % BOARD_W)

// Precomputed attack tables (initialized once)
static uint32_t bb_knight[30];       // knight attack mask per square
static uint32_t bb_king[30];         // king attack mask per square
static uint32_t bb_pawn_push[2][30]; // pawn push target per player/square
static uint32_t bb_pawn_cap[2][30];  // pawn capture targets per player/square
static bool bb_ready = false;

// Sliding piece direction vectors (0-3: rook, 4-7: bishop, 0-7: queen)
static const int bb_dr[8] = {0, 0, 1, -1, 1, 1, -1, -1};
static const int bb_dc[8] = {1, -1, 0, 0, 1, -1, 1, -1};

static void bb_init(){
    static const int kn_dr[8] = {1, 1, -1, -1, 2, 2, -2, -2};
    static const int kn_dc[8] = {2, -2, 2, -2, 1, -1, 1, -1};
    static const int ki_dr[8] = {1, 0, -1, 0, 1, 1, -1, -1};
    static const int ki_dc[8] = {0, 1, 0, -1, 1, -1, 1, -1};

    for(int r = 0; r < BOARD_H; r++){
        for(int c = 0; c < BOARD_W; c++){
            int sq = BB_SQ(r, c);

            // Knight
            bb_knight[sq] = 0;
            for(int d = 0; d < 8; d++){
                int nr = r + kn_dr[d], nc = c + kn_dc[d];
                if(nr >= 0 && nr < BOARD_H && nc >= 0 && nc < BOARD_W){
                    bb_knight[sq] |= 1u << BB_SQ(nr, nc);
                }
            }

            // King
            bb_king[sq] = 0;
            for(int d = 0; d < 8; d++){
                int nr = r + ki_dr[d], nc = c + ki_dc[d];
                if(nr >= 0 && nr < BOARD_H && nc >= 0 && nc < BOARD_W){
                    bb_king[sq] |= 1u << BB_SQ(nr, nc);
                }
            }

            // Pawn (player 0 = white, advances up = row-1)
            bb_pawn_push[0][sq] = 0;
            bb_pawn_cap[0][sq] = 0;
            if(r > 0){
                bb_pawn_push[0][sq] = 1u << BB_SQ(r-1, c);
                if(c > 0){
                    bb_pawn_cap[0][sq] |= 1u << BB_SQ(r-1, c-1);
                }
                if(c < BOARD_W-1){
                    bb_pawn_cap[0][sq] |= 1u << BB_SQ(r-1, c+1);
                }
            }

            // Pawn (player 1 = black, advances down = row+1)
            bb_pawn_push[1][sq] = 0;
            bb_pawn_cap[1][sq] = 0;
            if(r < BOARD_H-1){
                bb_pawn_push[1][sq] = 1u << BB_SQ(r+1, c);
                if(c > 0){
                    bb_pawn_cap[1][sq] |= 1u << BB_SQ(r+1, c-1);
                }
                if(c < BOARD_W-1){
                    bb_pawn_cap[1][sq] |= 1u << BB_SQ(r+1, c+1);
                }
            }
        }
    }
    bb_ready = true;
}


/*============================================================
 * count_pseudo_mobility() — see forward-declaration comment above
 * evaluate() for why this exists instead of create_null_state().
 *
 * Mirrors get_legal_actions_bitboard()'s target-square logic
 * exactly (same masks, same blocking/capture rules), but only
 * accumulates a popcount -- no Move objects, no legal_actions
 * vector, no State allocation, and critically: no early-return
 * the moment a king-capture is found. That early return is
 * correct/desired for real move generation (the position is
 * immediately terminal), but it's wrong for a "how mobile is
 * this side in general" heuristic -- it would make mobility
 * collapse to 1 whenever the side in question could capture a
 * king, instead of reporting its actual activity.
 *============================================================*/
static int count_pseudo_mobility(const Board& board, int player){
    if(!bb_ready){
        bb_init();
    }

    int opp = 1 - player;
    uint32_t self_occ = 0, oppn_occ = 0;
    int self_pt[30] = {};

    for(int r = 0; r < BOARD_H; r++){
        for(int c = 0; c < BOARD_W; c++){
            int sq = BB_SQ(r, c);
            if(board.board[player][r][c]){
                self_occ |= 1u << sq;
                self_pt[sq] = board.board[player][r][c];
            }
            if(board.board[opp][r][c]){
                oppn_occ |= 1u << sq;
            }
        }
    }

    uint32_t all_occ = self_occ | oppn_occ;
    int total = 0;

    uint32_t pieces = self_occ;
    while(pieces){
        int sq = __builtin_ctz(pieces);
        pieces &= pieces - 1;
        int r = BB_ROW(sq), c = BB_COL(sq);
        int piece = self_pt[sq];
        uint32_t targets = 0;

        switch(piece){
            case 1: { // Pawn
                uint32_t push = bb_pawn_push[player][sq] & ~all_occ;
                uint32_t cap = bb_pawn_cap[player][sq] & oppn_occ;
                targets = push | cap;
                break;
            }

            case 3: // Knight
                targets = bb_knight[sq] & ~self_occ;
                break;

            case 6: // King
                targets = bb_king[sq] & ~self_occ;
                break;

            case 2: // Rook
            case 4: // Bishop
            case 5: { // Queen
                int d_start = (piece == 4) ? 4 : 0;
                int d_end   = (piece == 2) ? 4 : 8;
                for(int d = d_start; d < d_end; d++){
                    int cr = r + bb_dr[d], cc = c + bb_dc[d];
                    while(cr >= 0 && cr < BOARD_H && cc >= 0 && cc < BOARD_W){
                        int to = BB_SQ(cr, cc);
                        uint32_t to_bit = 1u << to;
                        if(self_occ & to_bit){
                            break; // own piece blocks
                        }
                        targets |= to_bit;
                        if(oppn_occ & to_bit){
                            break; // captured, stop sliding
                        }
                        cr += bb_dr[d]; cc += bb_dc[d];
                    }
                }
                break;
            }
        }

        total += __builtin_popcount(targets);
    }

    return total;
}


void State::get_legal_actions_bitboard(){
    if(!bb_ready){
        bb_init();
    }

    this->game_state = NONE;
    this->legal_actions.clear();
    this->legal_actions.reserve(64);

    int self = this->player;
    int oppn = 1 - self;

    // Build occupancy bitmasks and piece-type lookup
    uint32_t self_occ = 0, oppn_occ = 0;
    int self_pt[30] = {};  // piece type at each square (self)
    int oppn_pt[30] = {};  // piece type at each square (opponent)

    for(int r = 0; r < BOARD_H; r++){
        for(int c = 0; c < BOARD_W; c++){
            int sq = BB_SQ(r, c);
            if(this->board.board[self][r][c]){
                self_occ |= 1u << sq;
                self_pt[sq] = this->board.board[self][r][c];
            }
            if(this->board.board[oppn][r][c]){
                oppn_occ |= 1u << sq;
                oppn_pt[sq] = this->board.board[oppn][r][c];
            }
        }
    }

    uint32_t all_occ = self_occ | oppn_occ;

    // Iterate own pieces via bit scan
    uint32_t pieces = self_occ;
    while(pieces){
        int sq = __builtin_ctz(pieces);
        pieces &= pieces - 1;
        int r = BB_ROW(sq), c = BB_COL(sq);
        int piece = self_pt[sq];
        uint32_t targets = 0;

        switch(piece){
            case 1: { // Pawn
                uint32_t push = bb_pawn_push[self][sq] & ~all_occ;
                uint32_t cap = bb_pawn_cap[self][sq] & oppn_occ;
                // Check for king capture in captures
                uint32_t cap_scan = cap;
                while(cap_scan){
                    int to = __builtin_ctz(cap_scan);
                    cap_scan &= cap_scan - 1;
                    if(oppn_pt[to] == 6){
                        this->game_state = WIN;
                        this->legal_actions.push_back(
                            Move(Point(r, c), Point(BB_ROW(to), BB_COL(to))));
                        return;
                    }
                }
                targets = push | cap;
                break;
            }

            case 3: { // Knight
                targets = bb_knight[sq] & ~self_occ;
                uint32_t opp_targets = targets & oppn_occ;
                while(opp_targets){
                    int to = __builtin_ctz(opp_targets);
                    opp_targets &= opp_targets - 1;
                    if(oppn_pt[to] == 6){
                        this->game_state = WIN;
                        this->legal_actions.push_back(
                            Move(Point(r, c), Point(BB_ROW(to), BB_COL(to))));
                        return;
                    }
                }
                break;
            }

            case 6: { // King
                targets = bb_king[sq] & ~self_occ;
                uint32_t opp_targets = targets & oppn_occ;
                while(opp_targets){
                    int to = __builtin_ctz(opp_targets);
                    opp_targets &= opp_targets - 1;
                    if(oppn_pt[to] == 6){
                        this->game_state = WIN;
                        this->legal_actions.push_back(
                            Move(Point(r, c), Point(BB_ROW(to), BB_COL(to))));
                        return;
                    }
                }
                break;
            }

            case 2: // Rook
            case 4: // Bishop
            case 5: { // Queen
                int d_start = (piece == 4) ? 4 : 0;
                int d_end   = (piece == 2) ? 4 : 8;
                for(int d = d_start; d < d_end; d++){
                    int cr = r + bb_dr[d], cc = c + bb_dc[d];
                    while(cr >= 0 && cr < BOARD_H && cc >= 0 && cc < BOARD_W){
                        int to = BB_SQ(cr, cc);
                        uint32_t to_bit = 1u << to;
                        if(self_occ & to_bit){
                            break; // own piece blocks
                        }

                        if((oppn_occ & to_bit) && oppn_pt[to] == 6){
                            this->game_state = WIN;
                            this->legal_actions.push_back(
                                Move(Point(r, c), Point(cr, cc)));
                            return;
                        }

                        targets |= to_bit;
                        if(oppn_occ & to_bit){
                            break; // captured, stop sliding
                        }
                        cr += bb_dr[d]; cc += bb_dc[d];
                    }
                }
                break;
            }
        }

        // Convert target bitmask to Move objects
        while(targets){
            int to = __builtin_ctz(targets);
            targets &= targets - 1;
            this->legal_actions.push_back(
                Move(Point(r, c), Point(BB_ROW(to), BB_COL(to))));
        }
    }
}


/*============================================================
 * Dispatcher
 *============================================================*/
void State::get_legal_actions(){
    #ifdef USE_BITBOARD
    get_legal_actions_bitboard();
    #else
    get_legal_actions_naive();
    #endif
}


const char piece_table[2][7][5] = {
  {" ", "♙", "♖", "♘", "♗", "♕", "♔"},
  {" ", "♟", "♜", "♞", "♝", "♛", "♚"}
};
/**
 * @brief encode the output for command line output
 * 
 * @return std::string 
 */
std::string State::encode_output() const{
    std::stringstream ss;
    int now_piece;
    for(int i=0; i<BOARD_H; i+=1){
        for(int j=0; j<BOARD_W; j+=1){
            if((now_piece = this->board.board[0][i][j])){
                ss << std::string(piece_table[0][now_piece]);
            }else if((now_piece = this->board.board[1][i][j])){
                ss << std::string(piece_table[1][now_piece]);
            }else{
                ss << " ";
            }
            ss << " ";
        }
        ss << "\n";
    }
    return ss.str();
}


/**
 * @brief encode the state to the format for player
 * 
 * @return std::string 
 */
std::string State::encode_state(){
    std::stringstream ss;
    ss << this->player;
    ss << "\n";
    for(int pl=0; pl<2; pl+=1){
        for(int i=0; i<BOARD_H; i+=1){
            for(int j=0; j<BOARD_W; j+=1){
                ss << int(this->board.board[pl][i][j]);
                ss << " ";
            }
            ss << "\n";
        }
        ss << "\n";
    }
    return ss.str();
}


BaseState* State::create_null_state() const{
    State* s = new State(this->board, 1 - this->player);
    s->get_legal_actions();
    return s;
}


/* === Board serialization === */
static const char* piece_chars = ".PRNBQK";
static const char* piece_chars_lower = ".prnbqk";

std::string State::encode_board() const{
    std::string s;
    for(int r = 0; r < BOARD_H; r++){
        if(r > 0){
            s += '/';
        }
        for(int c = 0; c < BOARD_W; c++){
            int w = board.board[0][r][c];
            int b = board.board[1][r][c];
            if(w > 0 && w <= 6){
                s += piece_chars[w];
            }else if(b > 0 && b <= 6){
                s += piece_chars_lower[b];
            }else{
                s += '.';
            }
        }
    }
    return s;
}

void State::decode_board(const std::string& s, int side_to_move){
    player = side_to_move;
    game_state = UNKNOWN;
    zobrist_valid = false;
    /* NOTE: `Board{}` is NOT an empty board -- Board's in-class member
     * initializer sets it to the standard MiniChess starting position
     * (so that plain `State()` / a fresh `Board()` gives a normal game
     * start everywhere else in the codebase). decode_board's whole job
     * is to set an *arbitrary* position from an encoded string, where
     * '.' means "this square is empty" -- but the loop below only ever
     * writes a square when it sees a piece letter, so any square left
     * as '.' would silently keep whatever piece the standard starting
     * layout happens to have there instead of being cleared. Zero every
     * square explicitly first so '.' really means empty. */
    for(int p = 0; p < 2; p++){
        for(int rr = 0; rr < BOARD_H; rr++){
            for(int cc = 0; cc < BOARD_W; cc++){
                board.board[p][rr][cc] = 0;
            }
        }
    }
    int r = 0, c = 0;
    for(char ch : s){
        if(ch == '/'){
            r++;
            c = 0;
            continue;
        }
        if(r >= BOARD_H || c >= BOARD_W){
            break;
        }
        if(ch >= 'A' && ch <= 'Z'){
            for(int p = 1; p <= 6; p++){
                if(piece_chars[p] == ch){
                    board.board[0][r][c] = p;
                    break;
                }
            }
        }else if(ch >= 'a' && ch <= 'z'){
            for(int p = 1; p <= 6; p++){
                if(piece_chars_lower[p] == ch){
                    board.board[1][r][c] = p;
                    break;
                }
            }
        }
        c++;
    }
    get_legal_actions();
}


/* (Zobrist tables moved above next_state) */


/*============================================================
 * Cell display for protocol (d command)
 *============================================================*/
std::string State::cell_display(int row, int col) const{
    int w = static_cast<int>(board.board[0][row][col]);
    int b = static_cast<int>(board.board[1][row][col]);
    if(w){
        const char* names = ".PRNBQK";
        return std::string(" ") + names[w] + " ";
    }else if(b){
        const char* names = ".prnbqk";
        return std::string(" ") + names[b] + " ";
    }else{
        return " . ";
    }
}

/* === Repetition: chess 3-fold rule === */
bool State::check_repetition(const GameHistory& history, int& out_score) const {
    if(history.count(hash()) >= 3){
        out_score = 0;  /* draw */
        return true;
    }
    return false;
}