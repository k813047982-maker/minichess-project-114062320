CXX = g++
CXXFLAGS = --std=c++2a -Wall -Wextra -Wpedantic -g -O3

SOURCES_DIR = src
UNITTEST_DIR = unittest
BUILD_DIR = build

STATE_SOURCE = $(SOURCES_DIR)/games/minichess/state.cpp
POLICY_SRC = $(wildcard $(SOURCES_DIR)/policy/*.cpp)
UNITTESTS = $(wildcard $(UNITTEST_DIR)/*.cpp)
TARGET_UNITTEST = $(UNITTESTS:$(UNITTEST_DIR)/%_test.cpp=%)

MINICHESS_INC = -Isrc/games/minichess -Isrc/state -Isrc

.PHONY: all clean minichess benchmark test

all: minichess benchmark test

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(UNITTEST_DIR)/build:
	mkdir -p $(UNITTEST_DIR)/build

minichess: | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(MINICHESS_INC) -o $(BUILD_DIR)/minichess-ubgi $(STATE_SOURCE) $(POLICY_SRC) src/ubgi/ubgi.cpp

benchmark: | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(MINICHESS_INC) -o $(BUILD_DIR)/minichess-benchmark $(STATE_SOURCE) $(POLICY_SRC) src/benchmark.cpp

test: $(TARGET_UNITTEST)

$(TARGET_UNITTEST): %: $(UNITTEST_DIR)/%_test.cpp | $(UNITTEST_DIR)/build
	$(CXX) $(CXXFLAGS) $(MINICHESS_INC) -o $(UNITTEST_DIR)/build/$@_test $(STATE_SOURCE) $(POLICY_SRC) $<

clean:
	rm -f $(BUILD_DIR)/minichess-ubgi $(BUILD_DIR)/minichess-benchmark
	rm -f $(UNITTEST_DIR)/build/*_test
