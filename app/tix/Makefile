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
	$(1)/test_new_fields
	$(1)/test_labels
	$(1)/test_tql
	$(1)/test_tql_features
	$(1)/test_resolved
	$(1)/test_assigned
	@echo "=== All tix tests passed ($(1)) ==="
endef

.PHONY: test
test: build
	$(call run_tests,build)

.ONESHELL:
.PHONY: test-asan
test-asan: build-asan
	set -e
	export ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:abort_on_error=1
	$(call run_tests,build-asan)

.PHONY: lint
lint: build/.cmake
	run-clang-tidy -p build -j $(JOBS) \
		-source-filter='.*/app/tix/src/.*\.c$$' \
		-header-filter='.*/app/tix/src/.*\.h$$'

# Man pages
MAN_DIR = doc/man
MAN_PAGES = $(wildcard $(MAN_DIR)/*.1 $(MAN_DIR)/*.5 $(MAN_DIR)/*.7)

.PHONY: man
man:
	@for f in $(MAN_PAGES); do \
		echo "Checking $$f ..."; \
		man -l $$f > /dev/null 2>&1 || echo "  warning: $$f has issues"; \
	done
	@echo "Man pages: $(words $(MAN_PAGES)) files in $(MAN_DIR)/"

.PHONY: install-man
install-man:
	@PREFIX=$${PREFIX:-/usr/local}; \
	for f in $(MAN_DIR)/*.1; do \
		install -Dm644 "$$f" "$$PREFIX/share/man/man1/$$(basename $$f)"; \
	done; \
	for f in $(MAN_DIR)/*.5; do \
		install -Dm644 "$$f" "$$PREFIX/share/man/man5/$$(basename $$f)"; \
	done; \
	for f in $(MAN_DIR)/*.7; do \
		install -Dm644 "$$f" "$$PREFIX/share/man/man7/$$(basename $$f)"; \
	done; \
	echo "Installed man pages to $$PREFIX/share/man/"

.PHONY: clean
clean:
	rm -rf build build-asan build-tsan

.PHONY: help
help:
	@echo "tix build targets:"
	@echo "  make build       - Default debug build"
	@echo "  make build-asan  - AddressSanitizer build"
	@echo "  make build-tsan  - ThreadSanitizer build"
	@echo "  make test        - Run all E2E tests"
	@echo "  make test-asan   - Tests with ASAN"
	@echo "  make lint        - Run clang-tidy"
	@echo "  make man         - Check man pages"
	@echo "  make install-man - Install man pages (PREFIX=/usr/local)"
	@echo "  make clean       - Remove build directories"
	@echo ""
	@echo "powerplant/tix is a wrapper script that auto-builds on first run."
	@echo "Just run 'tix' directly (or 'make build' to pre-build)."
