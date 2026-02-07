UNAME := $(shell uname -s)
CMAKE_BASE = cmake -G Ninja -DCMAKE_BUILD_TYPE=Debug
JOBS := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

define cmake_configure
	$(CMAKE_BASE) -DASAN=$(2) -DTSAN=$(3) -S . -B $(1)
	touch $(1)/.cmake
endef

define do_build
	touch $(1)/.cmake
	cmake --build $(1)
endef

# Default build
.ONESHELL:
.PHONY: cmake
cmake build/.cmake: CMakeLists.txt Makefile
	$(call cmake_configure,build,0,0)

.ONESHELL:
.PHONY: build
build: build/.cmake
	$(call do_build,build)

# ASAN build
.ONESHELL:
.PHONY: cmake-asan
cmake-asan build-asan/.cmake: CMakeLists.txt Makefile
	$(call cmake_configure,build-asan,1,0)

.ONESHELL:
.PHONY: build-asan
build-asan: build-asan/.cmake
	$(call do_build,build-asan)

# TSAN build
.ONESHELL:
.PHONY: cmake-tsan
cmake-tsan build-tsan/.cmake: CMakeLists.txt Makefile
	$(call cmake_configure,build-tsan,0,1)

.ONESHELL:
.PHONY: build-tsan
build-tsan: build-tsan/.cmake
	$(call do_build,build-tsan)

define run_tests
	@echo "=== Running tix E2E tests from $(1) ==="
	$(1)/test_task_lifecycle
	$(1)/test_git_integration
	$(1)/test_config
	$(1)/test_search
	$(1)/test_tree
	$(1)/test_batch
	$(1)/test_validate
	$(1)/test_report
	$(1)/test_json
	$(1)/test_error_paths
	$(1)/test_sync
	@echo "=== All tix tests passed ($(1)) ==="
endef

.PHONY: test
test: build
	$(call run_tests,build)

.ONESHELL:
.PHONY: test-asan
test-asan: build-asan
	set -e
	export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:abort_on_error=1
	$(call run_tests,build-asan)

.PHONY: lint
lint: build/.cmake
	run-clang-tidy -p build -j $(JOBS) \
		-source-filter='.*/app/tix/src/.*\.c$$' \
		-header-filter='.*/app/tix/src/.*\.h$$'

.PHONY: clean
clean:
	rm -rf build build-asan build-tsan

.PHONY: install
install: build
	cp build/tix ../../powerplant/tix

.PHONY: help
help:
	@echo "tix build targets:"
	@echo "  make build       - Default debug build"
	@echo "  make build-asan  - AddressSanitizer build"
	@echo "  make build-tsan  - ThreadSanitizer build"
	@echo "  make test        - Run all E2E tests"
	@echo "  make test-asan   - Tests with ASAN"
	@echo "  make lint        - Run clang-tidy"
	@echo "  make clean       - Remove build directories"
	@echo "  make install     - Copy binary to powerplant/"
