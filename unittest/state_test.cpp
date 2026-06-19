#include <iostream>
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstdlib>

#include "../src/games/minichess/state.hpp"
#include "../src/games/minichess/config.hpp"


// Compare two move lists (order-independent)
bool same_moves(std::vector<Move> a, std::vector<Move> b){
  std::sort(a.begin(), a.end());
  std::sort(b.begin(), b.end());
  return a == b;
}

int tests_passed = 0;
int tests_failed = 0;

void test_position(Board board, int player, const char* name){
  State s1(board, player);
  s1.get_legal_actions_naive();

  State s2(board, player);
  s2.get_legal_actions_bitboard();

  bool ok = true;

  // Compare game state
  if(s1.game_state != s2.game_state){
    std::cerr << "FAIL " << name << ": game_state mismatch "
              << s1.game_state << " vs " << s2.game_state << "\n";
    ok = false;
  }

  // Compare move sets
  if(ok && s1.game_state != WIN && !same_moves(s1.legal_actions, s2.legal_actions)){
    std::cerr << "FAIL " << name << ": move list mismatch\n";
    std::cerr << "  Naive:    " << s1.legal_actions.size() << " moves\n";
    std::cerr << "  Bitboard: " << s2.legal_actions.size() << " moves\n";

    // Show diff
    auto a = s1.legal_actions, b = s2.legal_actions;
    std::sort(a.begin(), a.end());
    std::sort(b.begin(), b.end());
    std::cerr << "  In naive only:\n";
    for(auto& m : a){
      if(std::find(b.begin(), b.end(), m) == b.end())
        std::cerr << "    (" << m.first.first << "," << m.first.second
                  << ")->(" << m.second.first << "," << m.second.second << ")\n";
    }
    std::cerr << "  In bitboard only:\n";
    for(auto& m : b){
      if(std::find(a.begin(), a.end(), m) == a.end())
        std::cerr << "    (" << m.first.first << "," << m.first.second
                  << ")->(" << m.second.first << "," << m.second.second << ")\n";
    }
    ok = false;
  }

  // For WIN states, just verify both agree on WIN
  if(ok && s1.game_state == WIN){
    if(s2.legal_actions.empty()){
      std::cerr << "FAIL " << name << ": bitboard WIN but no king-capture move\n";
      ok = false;
    }
  }

  if(ok){
    std::cout << "PASS " << name
              << " (state=" << s1.game_state
              << ", moves=" << s1.legal_actions.size() << ")\n";
    tests_passed++;
  }else{
    tests_failed++;
  }
}


// Play a game using both implementations, compare at each step
void test_game_playthrough(int max_steps){
  std::cout << "\n=== Game playthrough test (" << max_steps << " steps) ===\n";
  State game;
  int step = 0;
  while(step < max_steps){
    State s1(game.board, game.player);
    s1.get_legal_actions_naive();

    State s2(game.board, game.player);
    s2.get_legal_actions_bitboard();

    if(s1.game_state != s2.game_state){
      std::cerr << "FAIL step " << step << ": game_state mismatch\n";
      tests_failed++;
      return;
    }
    if(s1.game_state == WIN) break;

    if(!same_moves(s1.legal_actions, s2.legal_actions)){
      std::cerr << "FAIL step " << step << ": move mismatch ("
                << s1.legal_actions.size() << " vs "
                << s2.legal_actions.size() << ")\n";
      tests_failed++;
      return;
    }

    // Make a deterministic move (pick first from sorted list)
    auto moves = s1.legal_actions;
    std::sort(moves.begin(), moves.end());
    Move chosen = moves[step % moves.size()];

    State* next = game.next_state(chosen);
    game = *next;
    delete next;
    step++;
  }
  std::cout << "PASS game playthrough (" << step << " steps, all matched)\n";
  tests_passed++;
}


void benchmark(int iterations){
  std::cout << "\n=== Benchmark (" << iterations << " iterations) ===\n";
  Board board; // initial position

  auto t1 = std::chrono::high_resolution_clock::now();
  for(int i = 0; i < iterations; i++){
    State s(board, i % 2);
    s.get_legal_actions_naive();
  }
  auto t2 = std::chrono::high_resolution_clock::now();
  for(int i = 0; i < iterations; i++){
    State s(board, i % 2);
    s.get_legal_actions_bitboard();
  }
  auto t3 = std::chrono::high_resolution_clock::now();

  auto naive_us = std::chrono::duration_cast<std::chrono::microseconds>(t2 - t1).count();
  auto bb_us = std::chrono::duration_cast<std::chrono::microseconds>(t3 - t2).count();

  std::cout << "  Naive:    " << naive_us << " us\n"
            << "  Bitboard: " << bb_us << " us\n"
            << "  Speedup:  " << (double)naive_us / (bb_us ? bb_us : 1) << "x\n";
}


int main(){
  srand(RANDOM_SEED);

  std::cout << "=== Static position tests ===\n";

  // Test 1: Initial position, white to move
  {
    Board b;
    test_position(b, 0, "initial_white");
  }

  // Test 2: Initial position, black to move
  {
    Board b;
    test_position(b, 1, "initial_black");
  }

  // Test 3: Mid-game with captures available
  {
    Board b;
    // Clear default, set up custom position
    for(int p=0;p<2;p++) for(int r=0;r<BOARD_H;r++) for(int c=0;c<BOARD_W;c++) b.board[p][r][c]=0;
    // White: King(5,4), Rook(3,0), Pawn(3,2)
    b.board[0][5][4] = 6; b.board[0][3][0] = 2; b.board[0][3][2] = 1;
    // Black: King(0,0), Knight(3,3), Pawn(2,2)
    b.board[1][0][0] = 6; b.board[1][3][3] = 3; b.board[1][2][2] = 1;
    test_position(b, 0, "midgame_white");
    test_position(b, 1, "midgame_black");
  }

  // Test 4: Position where king can be captured (WIN state)
  {
    Board b;
    for(int p=0;p<2;p++) for(int r=0;r<BOARD_H;r++) for(int c=0;c<BOARD_W;c++) b.board[p][r][c]=0;
    // White: King(5,4), Queen(1,0)
    b.board[0][5][4] = 6; b.board[0][1][0] = 5;
    // Black: King(0,0)
    b.board[1][0][0] = 6;
    test_position(b, 0, "king_capture_win");
  }

  // Test 5: Endgame with few pieces
  {
    Board b;
    for(int p=0;p<2;p++) for(int r=0;r<BOARD_H;r++) for(int c=0;c<BOARD_W;c++) b.board[p][r][c]=0;
    // White: King(5,2)
    b.board[0][5][2] = 6;
    // Black: King(0,2), Pawn(4,3)
    b.board[1][0][2] = 6; b.board[1][4][3] = 1;
    test_position(b, 0, "endgame_white");
    test_position(b, 1, "endgame_black");
  }

  // Test 6: Pawn about to promote
  {
    Board b;
    for(int p=0;p<2;p++) for(int r=0;r<BOARD_H;r++) for(int c=0;c<BOARD_W;c++) b.board[p][r][c]=0;
    b.board[0][5][0] = 6; b.board[0][1][2] = 1;  // white pawn at row 1 (one step from promotion)
    b.board[1][0][4] = 6;
    test_position(b, 0, "pawn_promote_white");
  }

  // Test 7: Bishop on open board
  {
    Board b;
    for(int p=0;p<2;p++) for(int r=0;r<BOARD_H;r++) for(int c=0;c<BOARD_W;c++) b.board[p][r][c]=0;
    b.board[0][5][0] = 6; b.board[0][3][2] = 4;  // bishop center
    b.board[1][0][4] = 6; b.board[1][1][0] = 1;   // black pawn as target
    test_position(b, 0, "bishop_open");
  }

  // Test 8: Queen in center with lots of moves
  {
    Board b;
    for(int p=0;p<2;p++) for(int r=0;r<BOARD_H;r++) for(int c=0;c<BOARD_W;c++) b.board[p][r][c]=0;
    b.board[0][5][0] = 6; b.board[0][3][2] = 5;  // queen center
    b.board[1][0][4] = 6; b.board[1][3][4] = 2;   // black rook
    b.board[1][1][2] = 1;                          // black pawn on queen's file
    test_position(b, 0, "queen_center");
  }

  // Test 9: Knight at corner (limited moves)
  {
    Board b;
    for(int p=0;p<2;p++) for(int r=0;r<BOARD_H;r++) for(int c=0;c<BOARD_W;c++) b.board[p][r][c]=0;
    b.board[0][5][0] = 6; b.board[0][5][4] = 3;  // knight at corner
    b.board[1][0][0] = 6;
    test_position(b, 0, "knight_corner");
  }

  // Test 10: Full game playthrough
  test_game_playthrough(50);

  // Benchmark
  benchmark(100000);

  std::cout << "\n=== Results: " << tests_passed << " passed, "
            << tests_failed << " failed ===\n";
  return tests_failed ? 1 : 0;
}
