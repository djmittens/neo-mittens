# TSAN Output Handling

## Problem

ThreadSanitizer (TSAN) can produce enormous output that floods the context window, causing:
- Context overrun failures in Ralph's construct mode
- Difficulty identifying the actual issues among noise
- Repeated reports for the same race condition

## Solution

Create an OpenCode skill that provides strategies for handling TSAN output when running tests.

## TSAN Output Characteristics

A single data race report looks like:
```
==================
WARNING: ThreadSanitizer: data race (pid=26327)
  Write of size 4 at 0x7f89554701d0 by thread T1:
    #0 Thread1(void*) simple_race.cc:8 (exe+0x000000006e66)
    #1 ... (10-20 more stack frames)

  Previous write of size 4 at 0x7f89554701d0 by thread T2:
    #0 Thread2(void*) simple_race.cc:13 (exe+0x000000006ed6)
    #1 ... (10-20 more stack frames)

  Thread T1 (tid=26328, running) created at:
    #0 pthread_create ...
    #1 ... (5-10 more stack frames)

  Thread T2 (tid=26329, running) created at:
    #0 pthread_create ...
    #1 ... (5-10 more stack frames)
==================
```

Each report can be 50-100+ lines. With multiple races, output can exceed 10,000 lines.

## Strategies

### 1. Redirect Output to File

```bash
TSAN_OPTIONS="log_path=tsan.log" ./test_binary
```

Then read only summary:
```bash
grep -c "WARNING: ThreadSanitizer" tsan.log  # Count total races
grep "WARNING: ThreadSanitizer" tsan.log | head -20  # First 20 types
```

### 2. Stop After First Error

```bash
TSAN_OPTIONS="halt_on_error=1" ./test_binary
```

Useful for fixing one race at a time.

### 3. Use Suppressions File

Create `tsan_suppressions.txt`:
```
# Known race in third-party library
race:thirdparty::SomeClass

# Race we're not fixing yet (Bug #123)
race:MyClass::racyMethod

# Entire library to ignore
called_from_lib:libfoo.so
```

Run with:
```bash
TSAN_OPTIONS="suppressions=tsan_suppressions.txt" ./test_binary
```

### 4. Reduce Stack Trace Depth

```bash
TSAN_OPTIONS="history_size=0" ./test_binary
```

Values 0-7, where 0 = 32K memory accesses remembered (smallest).
Reduces report verbosity but may show "failed to restore the stack".

### 5. Combine Options

```bash
TSAN_OPTIONS="log_path=tsan.log:halt_on_error=0:history_size=2:suppressions=tsan_suppressions.txt" ./test_binary
```

### 6. Post-Process Output

Script to deduplicate and summarize:
```bash
# Extract unique race locations
grep -A2 "WARNING: ThreadSanitizer: data race" tsan.log | \
  grep "#0" | \
  sort -u | \
  head -20
```

## Skill: Parse TSAN Output

When encountering TSAN output, the skill should:

1. **Detect TSAN output** - Look for `WARNING: ThreadSanitizer:`
2. **Count unique races** - Deduplicate by location
3. **Summarize** - Report count and top locations
4. **Suggest suppressions** - For known/accepted races

### Output Format for LLM

Instead of raw TSAN output, produce:
```
TSAN Summary:
- Total reports: 47
- Unique races: 3

Race 1 (35 occurrences):
  Location: src/worker.cc:123 Worker::process
  Type: data race (write/write)
  
Race 2 (10 occurrences):
  Location: src/cache.cc:456 Cache::get
  Type: data race (read/write)

Race 3 (2 occurrences):
  Location: third_party/lib.cc:789
  Type: data race
  Suggestion: Add to suppressions (third-party code)
```

## Integration with Ralph

### In PROMPT_build.md

When running tests with TSAN:
1. Always redirect output: `TSAN_OPTIONS="log_path=build/tsan.log"`
2. After test run, use skill to summarize
3. Create issues for unique races found
4. Never paste raw TSAN output into context

### In Construct Mode

Add to compaction strategy:
- TSAN output -> Summarize to "N races found at locations X, Y, Z"
- Full output preserved in log file for later analysis

## CLI Helper

```bash
# Proposed: ralph tsan-summary <logfile>
# Outputs structured summary suitable for LLM context
```

## Acceptance Criteria

- [ ] Create `.opencode/skills/tsan.md` skill file
- [ ] Skill detects TSAN output patterns
- [ ] Skill provides deduplication strategy
- [ ] Skill suggests appropriate TSAN_OPTIONS for different scenarios
- [ ] Integration guidance for PROMPT_build.md
- [ ] Example suppressions file template
