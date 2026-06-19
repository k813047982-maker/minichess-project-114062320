#pragma once
#include "config.hpp"
#include <cstdlib>
#include <string>
#include <map>
#include <vector>

/*============================================================
 * Search parameters — generic key-value map
 *
 * The external API (UCI, GUI) sets params as string key-value
 * pairs. Each algorithm parses the map into its own typed
 * struct for fast access during search.
 *============================================================*/

using ParamMap = std::map<std::string, std::string>;

/* === Param definition (for UCI option advertisement) === */
struct ParamDef {
    std::string name;
    enum Type { CHECK, SPIN } type;
    std::string default_val;
    int min_val = 0;
    int max_val = 0;
};

/* === Helpers to read typed values from ParamMap === */
inline bool param_bool(const ParamMap& m, const std::string& key, bool fallback = false){
    auto it = m.find(key);
    if(it == m.end()){
        return fallback;
    }
    return (it->second == "true" || it->second == "1");
}

inline int param_int(const ParamMap& m, const std::string& key, int fallback = 0){
    auto it = m.find(key);
    if(it == m.end()){
        return fallback;
    }
    return std::atoi(it->second.c_str());
}
