#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <mutex>
#include <chrono>
#include <algorithm>
#include <cstdlib>

#include "ubgi.hpp"
#include "config.hpp"
#include "search_types.hpp"
#include "../policy/registry.hpp"
#include "../policy/game_history.hpp"

namespace ubgi {


/* === Global State === */

static Board              g_board;
static int                g_player = 0;
static int                g_step   = 0;
static GameHistory        g_history;
static const AlgoEntry*   g_algo   = nullptr;
static ParamMap           g_params;
static SearchContext      g_ctx;
static std::thread        g_search_thread;
static std::mutex         g_io_mutex;
static std::atomic<bool>  g_searching{false};
static std::atomic<bool>  g_bestmove_sent{true};
static Move               g_best_move;
static int                g_multi_pv = 1;


/* === Helpers === */

static void send(const std::string& msg){
    std::lock_guard<std::mutex> lock(g_io_mutex);
    std::cout << msg << std::endl;
}


/* === Move Conversion === */

/* DROP_LETTERS is defined per-game in config.hpp for games with drops.
 * Maps hand piece index (1..NUM_HAND_TYPES) to a letter for UBGI protocol.
 * E.g. MiniShogi: " PSGBR", Kohaku Shogi: " PSGLNBR".
 * Games without drops don't define it — provide a fallback. */
#if NUM_HAND_TYPES == 0
static const char DROP_LETTERS[] = " ";
#endif

static int drop_letter_to_type(char ch){
    /* Search DROP_LETTERS for the character */
    for(int i = 1; i <= NUM_HAND_TYPES; i++){
        if(DROP_LETTERS[i] == ch
           || DROP_LETTERS[i] == (ch >= 'a' ? ch - 32 : ch + 32)){
            return i;
        }
    }
    return 0;
}

/* Helper: encode a square as column letter + row number string (e.g. "a15") */
static std::string sq_to_str(size_t row, size_t col){
    std::string s;
    s += static_cast<char>('a' + col);
    s += std::to_string(BOARD_H - static_cast<int>(row));
    return s;
}

std::string move_to_str(const Move& m){
    /* Placement move: from == to → output just the destination */
    if(m.first == m.second){
        return sq_to_str(m.second.first, m.second.second);
    }
    /* Drop move: from.first == BOARD_H, from.second == piece_type */
    if(m.first.first == static_cast<size_t>(BOARD_H)){
        int pt = static_cast<int>(m.first.second);
        std::string s;
        s += (pt >= 1 && pt <= NUM_HAND_TYPES) ? DROP_LETTERS[pt] : '?';
        s += '*';
        s += sq_to_str(m.second.first, m.second.second);
        return s;
    }
    /* Board move: from + to (+ promotion if to.first >= BOARD_H) */
    bool promote = (m.second.first >= static_cast<size_t>(BOARD_H));
    if(promote){
#if NUM_HAND_TYPES > 0
        /* Shogi-style promotion: to.first = actual_row + BOARD_H */
        size_t to_row = m.second.first - BOARD_H;
        std::string s = (
            sq_to_str(m.first.first, m.first.second)
            + sq_to_str(to_row, m.second.second)
        );
        s += '+';
        return s;
#else
        /* Chess-style promotion: to.first = actual_row + BOARD_H * promo_idx
         * promo_idx: 1=Queen, 2=Rook, 3=Bishop, 4=Knight */
        int promo_idx = static_cast<int>(m.second.first / BOARD_H);
        size_t to_row = m.second.first % BOARD_H;
        std::string s = (
            sq_to_str(m.first.first, m.first.second)
            + sq_to_str(to_row, m.second.second)
        );
        static const char promo_chars[] = "?qrbn";
        if(promo_idx >= 1 && promo_idx <= 4){
            s += promo_chars[promo_idx];
        }
        return s;
#endif
    }
    std::string s = (
        sq_to_str(m.first.first, m.first.second)
        + sq_to_str(m.second.first, m.second.second)
    );
    return s;
}

/* Helper: parse a square from a string starting at position pos.
 * Returns (row, col) and advances pos past the consumed characters.
 * Format: column letter + row number (possibly multi-digit), e.g. "a15". */
static std::pair<size_t, size_t> parse_sq(const std::string& s, size_t& pos){
    size_t col = static_cast<size_t>(s[pos] - 'a');
    pos++;
    /* Parse integer row number (may be multi-digit) */
    size_t num_start = pos;
    while(pos < s.size() && s[pos] >= '0' && s[pos] <= '9'){
        pos++;
    }
    int row_num = std::stoi(s.substr(num_start, pos - num_start));
    size_t row = static_cast<size_t>(BOARD_H - row_num);
    return {row, col};
}

Move str_to_move(const std::string& s){
    /* Drop move: X*sq (e.g. P*c3) */
    if(s.size() >= 3 && s[1] == '*'){
        int pt = drop_letter_to_type(s[0]);
        size_t pos = 2;
        auto [row, col] = parse_sq(s, pos);
        return Move(
            Point(static_cast<size_t>(BOARD_H), static_cast<size_t>(pt)),
            Point(row, col)
        );
    }
    /* Parse first square */
    size_t pos = 0;
    auto [fr, fc] = parse_sq(s, pos);
    /* Placement move: no more squares to parse */
    if(pos >= s.size() || !std::isalpha(s[pos])){
        return Move(Point(fr, fc), Point(fr, fc));
    }
    /* Board move: parse second square [+promote or qrbn suffix] */
    auto [tr, tc] = parse_sq(s, pos);
    if(pos < s.size()){
        char suffix = s[pos];
        if(suffix == '+'){
            /* Shogi-style promotion */
            tr += BOARD_H;
        }else{
            /* Chess-style promotion suffix: q=1, r=2, b=3, n=4 */
            int pidx = 0;
            switch(suffix){
                case 'q': case 'Q': pidx = 1; break;
                case 'r': case 'R': pidx = 2; break;
                case 'b': case 'B': pidx = 3; break;
                case 'n': case 'N': pidx = 4; break;
            }
            if(pidx > 0){
                tr += BOARD_H * pidx;
            }
        }
    }
    return Move(Point(fr, fc), Point(tr, tc));
}


/* === Position Handling === */

void set_position(
    const std::string& line,
    Board& board,
    int& player,
    int& step
){
    std::istringstream iss(line);
    std::string token;
    iss >> token; /* "startpos" or "board" */

    g_history.clear();

    if(token == "board"){
        /* position board <encoded_board> <side: 0 or 1> [moves ...] */
        std::string board_str;
        int side = 0;
        iss >> board_str >> side;
        State state;
        state.decode_board(board_str, side);
        board = state.board;
        player = state.player;
        step = 0;
    }else{
        /* position startpos [moves ...] */
        Board start_board;
        board = start_board;
        player = 0;
        step = 0;
    }

    /* Push the starting position hash */
    {
        State start_state(board, player);
        g_history.push(start_state.hash());
    }

    /* Replay any trailing moves via chained next_state calls.
     * This preserves game-specific state (e.g. stones_left for Connect6)
     * that would be lost by constructing State(board, player) each step. */
    std::string moves_token;
    if(iss >> moves_token && moves_token == "moves"){
        State* cur = new State(board, player);
        cur->get_legal_actions();
        std::string move_str;
        while(iss >> move_str){
            if(move_str.size() < 2){
                continue;
            }
            Move mv = str_to_move(move_str);
            State* next = cur->next_state(mv);
            next->get_legal_actions();
            g_history.push(next->hash());
            delete cur;
            cur = next;
            step++;
        }
        board = cur->board;
        player = cur->player;
        delete cur;
    }
}


/* === PV Formatting === */

static std::string format_pv(const std::vector<Move>& pv){
    std::string result;
    for(size_t i = 0; i < pv.size(); i++){
        if(i > 0){
            result += ' ';
        }
        result += move_to_str(pv[i]);
    }
    return result;
}


/* === Search Dispatch (worker thread) === */

static std::atomic<uint32_t> g_search_gen{0};

static void do_search(
    int max_depth,
    int64_t movetime_ms,
    [[maybe_unused]] bool infinite,
    uint32_t my_gen,
    SearchContext ctx,
    Board board,
    int player,
    GameHistory history,
    int step
){
    State state(board, player);
    state.step = step;
    state.get_legal_actions();

    auto alive = [&](){
        if(my_gen != g_search_gen.load()){
            return false;
        }
        if(g_ctx.stop){
            ctx.stop = true;
        }
        return !ctx.stop;
    };

    if(state.legal_actions.empty()){
        if(alive()){
            send("bestmove 0000");
            g_bestmove_sent = true;
        }
        g_searching = false;
        return;
    }
    if(state.game_state == WIN){
        if(alive()){
            send("bestmove " + move_to_str(state.legal_actions[0]));
            g_bestmove_sent = true;
        }
        g_searching = false;
        return;
    }

    Move best_move = state.legal_actions[0];
    g_best_move = best_move;
    int depth_limit = (max_depth > 0) ? max_depth : 100;
    uint64_t total_nodes = 0;

    auto search_start = std::chrono::high_resolution_clock::now();

    /* === Root move partial-result callback === */
    ctx.on_root_update = [&](const RootUpdate& upd){
        if(my_gen != g_search_gen.load()){
            return;
        }
        best_move = upd.best_move;
        g_best_move = upd.best_move;

        auto now = std::chrono::high_resolution_clock::now();
        int64_t elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now - search_start
        ).count();
        uint64_t cur_nodes = total_nodes + ctx.nodes;
        uint64_t nps = (elapsed_ms > 0)
            ? (cur_nodes * 1000ULL / static_cast<uint64_t>(elapsed_ms))
            : 0;

        std::ostringstream oss;
        oss << "info depth " << upd.depth
            << " seldepth " << ctx.seldepth
            << " score cp " << upd.score
            << " nodes " << cur_nodes
            << " time " << elapsed_ms
            << " nps " << nps
            << " currmove " << move_to_str(upd.best_move)
            << " currmovenumber " << upd.move_number;
        send(oss.str());
    };

    int multi_pv = g_multi_pv;

    for(int depth = 1; depth <= depth_limit; depth++){
        if(!alive()){
            break;
        }

        auto depth_start = std::chrono::high_resolution_clock::now();
        SearchResult result = g_algo->search(&state, depth, history, ctx);

        if(!alive() && depth > 1){
            break;
        }

        auto now = std::chrono::high_resolution_clock::now();
        int64_t depth_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now - depth_start
        ).count();
        int64_t total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now - search_start
        ).count();

        best_move = result.best_move;
        g_best_move = best_move;
        total_nodes += result.nodes;

        uint64_t nps = (depth_ms > 0)
            ? (result.nodes * 1000ULL / static_cast<uint64_t>(depth_ms))
            : 0;

        std::ostringstream info;
        info << "info depth " << depth
            << " seldepth " << result.seldepth;
        if(multi_pv > 1){
            info << " multipv 1";
        }
        info << " score cp " << result.score
            << " nodes " << total_nodes
            << " time " << total_ms
            << " nps " << nps;
        if(!result.pv.empty()){
            info << " pv " << format_pv(result.pv);
        }

        if(alive()){
            send(info.str());
        }

        /* === MultiPV: search for additional PVs === */
        if(multi_pv > 1 && alive()){
            std::vector<Move> excluded;
            excluded.push_back(result.best_move);
            auto saved_actions = state.legal_actions;

            for(int mpv = 2; mpv <= multi_pv; mpv++){
                /* Remove excluded moves from legal_actions */
                state.legal_actions = saved_actions;
                state.legal_actions.erase(
                    std::remove_if(state.legal_actions.begin(), state.legal_actions.end(),
                        [&](const Move& m){
                            return std::find(excluded.begin(), excluded.end(), m) != excluded.end();
                        }),
                    state.legal_actions.end()
                );
                if(state.legal_actions.empty()){
                    break;
                }
                if(!alive()){
                    break;
                }

                SearchContext sub_ctx;
                sub_ctx.params = ctx.params;
                sub_ctx.move_time_ms = ctx.move_time_ms;
                SearchResult sub = g_algo->search(&state, depth, history, sub_ctx);

                if(!alive()){
                    break;
                }

                total_nodes += sub.nodes;

                auto now2 = std::chrono::high_resolution_clock::now();
                int64_t total_ms2 = std::chrono::duration_cast<std::chrono::milliseconds>(
                    now2 - search_start
                ).count();

                std::ostringstream sub_info;
                uint64_t sub_nps = (
                    (total_ms2 > 0)
                    ? (total_nodes * 1000ULL / static_cast<uint64_t>(total_ms2))
                    : 0
                );
                sub_info << "info depth " << depth
                    << " seldepth " << sub.seldepth
                    << " multipv " << mpv
                    << " score cp " << sub.score
                    << " nodes " << total_nodes
                    << " time " << total_ms2
                    << " nps " << sub_nps;
                if(!sub.pv.empty()){
                    sub_info << " pv " << format_pv(sub.pv);
                }

                send(sub_info.str());

                excluded.push_back(sub.best_move);
            }

            state.legal_actions = saved_actions;  /* restore */
        }

        if(!alive()){
            break;
        }
        if(movetime_ms > 0 && total_ms * 2 >= movetime_ms){
            break;
        }
        if(result.score >= P_MAX - 100 || result.score <= M_MAX + 100){
            break;
        }
    }

    if(alive()){
        send("bestmove " + move_to_str(best_move));
        g_bestmove_sent = true;
    }
    g_searching = false;
}


/* === Command: go === */

static void cmd_go(std::istringstream& iss){
    g_ctx.stop = true;
    if(g_search_thread.joinable()){
        g_search_thread.join();
    }

    int max_depth = 0;
    int64_t movetime_ms = 0;
    bool infinite = false;

    std::string token;
    while(iss >> token){
        if(token == "depth"){
            iss >> max_depth;
        }else if(token == "movetime"){
            iss >> movetime_ms;
        }else if(token == "infinite"){
            infinite = true;
        }
    }

    if(max_depth == 0 && movetime_ms == 0 && !infinite){
        max_depth = 6;
    }

    SearchContext ctx;
    ctx.params = g_params;
    ctx.move_time_ms = movetime_ms;
    g_ctx.stop = false;
    g_searching = true;
    g_bestmove_sent = false;
    uint32_t gen = g_search_gen.load();
    g_best_move = Move();
    g_search_thread = std::thread(
        do_search, max_depth, movetime_ms, infinite, gen, ctx, g_board, g_player, g_history, g_step
    );
}


/* === Command: position === */

static void cmd_position(std::istringstream& iss){
    std::string rest;
    std::getline(iss, rest);
    size_t start = rest.find_first_not_of(' ');
    if(start != std::string::npos){
        rest = rest.substr(start);
    }
    set_position(rest, g_board, g_player, g_step);
}


/* === Command: setoption === */

static void cmd_setoption(std::istringstream& iss){
    std::string token, name, value;
    while(iss >> token){
        if(token == "name"){
            iss >> name;
        }else if(token == "value"){
            iss >> value;
        }
    }

    if(name == "Algorithm" || name == "algorithm"){
        std::string lower = value;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        const AlgoEntry* entry = find_algo(lower);
        if(entry){
            g_algo = entry;
            g_params = entry->default_params;
        }
    }else if(name == "MultiPV"){
        int mpv = std::atoi(value.c_str());
        if(mpv >= 1 && mpv <= 10){
            g_multi_pv = mpv;
        }
    }else{
        g_params[name] = value;
    }
}


/* === Command: d (debug display) === */

static void cmd_display(){
    State state(g_board, g_player);
    std::ostringstream oss;
    oss << "\n  ";
    for(int c = 0; c < BOARD_W; c++){
        oss << " " << static_cast<char>('a' + c) << " ";
    }
    oss << "\n";

    for(int r = 0; r < BOARD_H; r++){
        int row_label = BOARD_H - r;
        oss << row_label << " ";
        for(int c = 0; c < BOARD_W; c++){
            oss << state.cell_display(r, c);
        }
        oss << " " << row_label << "\n";
    }

    oss << "  ";
    for(int c = 0; c < BOARD_W; c++){
        oss << " " << static_cast<char>('a' + c) << " ";
    }
    oss << "\n";

    oss << "Side to move: " << (g_player == 0 ? "white" : "black") << "\n";
    oss << "Step: " << g_step << "\n";
    oss << "Algorithm: " << g_algo->name << "\n";

    send(oss.str());
}


/* === Algorithm Option String === */

static std::string algo_option_str(){
    const auto& table = get_algo_table();
    std::string s = "option name Algorithm type combo default " + default_algo_name();
    for(auto& entry : table){
        s += " var " + entry.name;
    }
    return s;
}


/* === Main Loop === */

void loop(){
    std::cout << std::unitbuf;

    g_algo = find_algo(default_algo_name());
    g_params = g_algo->default_params;

    std::string handshake_cmd;
    std::string line;

    while(std::getline(std::cin, line)){
        if(!line.empty() && line.back() == '\r'){
            line.pop_back();
        }
        if(line.empty()){
            continue;
        }

        std::istringstream iss(line);
        std::string cmd;
        iss >> cmd;

        if(cmd == "uci" || cmd == "ubgi"){
            handshake_cmd = cmd;
            State id_state;
            send(std::string("id name ") + id_state.game_name());
            send(std::string("id author ") + id_state.game_name() + " Team");
            send(std::string("option name GameName type string default ") + id_state.game_name());
            send("option name BoardWidth type spin default " + std::to_string(BOARD_W) + " min 1 max 26");
            send("option name BoardHeight type spin default " + std::to_string(BOARD_H) + " min 1 max 26");
            send(algo_option_str());
            for(auto& pd : g_algo->param_defs){
                if(pd.type == ParamDef::CHECK){
                    send("option name " + pd.name + " type check default " + pd.default_val);
                }else{
                    send(
                        "option name " + pd.name + " type spin default " + pd.default_val
                        + " min " + std::to_string(pd.min_val)
                        + " max " + std::to_string(pd.max_val)
                    );
                }
            }
            send("option name MultiPV type spin default 1 min 1 max 10");
            if(handshake_cmd == "ubgi"){
                send("ubgiok");
            }else{
                send("uciok");
            }
        }else if(cmd == "isready"){
            send("readyok");
        }else if(cmd == "setoption"){
            cmd_setoption(iss);
        }else if(cmd == "position"){
            cmd_position(iss);
        }else if(cmd == "go"){
            cmd_go(iss);
        }else if(cmd == "stop"){
            g_ctx.stop = true;
            if(g_search_thread.joinable()){
                g_search_thread.join();
            }
            /* If the search thread was interrupted before it could emit
               bestmove, send one now so the GUI/CLI never hangs. */
            if(!g_bestmove_sent.load()){
                g_bestmove_sent = true;
                send("bestmove " + move_to_str(g_best_move));
            }
        }else if(cmd == "ucinewgame" || cmd == "ubginewgame"){
            g_board = Board();
            g_player = 0;
            g_step = 0;
            g_history.clear();
        }else if(cmd == "d"){
            cmd_display();
        }else if(cmd == "quit"){
            g_ctx.stop = true;
            if(g_search_thread.joinable()){
                g_search_thread.join();
            }
            break;
        }
    }

    if(g_search_thread.joinable()){
        g_search_thread.detach();
    }
}

} // namespace ubgi


/* === Entry Point === */

int main(){
    ubgi::loop();
    return 0;
}