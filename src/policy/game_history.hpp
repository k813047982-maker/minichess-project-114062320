#pragma once
#include <cstdint>
#include <unordered_map>

/* Game-agnostic position history tracking.
 * Recording is game-agnostic (push/pop hash counts).
 * Utilization is game-specific (state reads history for eval/repetition). */
struct GameHistory {
    std::unordered_map<uint64_t, int> counts;

    void push(uint64_t hash) { counts[hash]++; }

    void pop(uint64_t hash) {
        auto it = counts.find(hash);
        if (it != counts.end()) {
            it->second--;
            if (it->second <= 0) counts.erase(it);
        }
    }

    int count(uint64_t hash) const {
        auto it = counts.find(hash);
        return (it != counts.end()) ? it->second : 0;
    }

    bool is_repetition(uint64_t hash, int limit = 4) const {
        return count(hash) >= limit;
    }

    void clear() { counts.clear(); }
};
