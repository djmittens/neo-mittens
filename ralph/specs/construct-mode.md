# Construct Mode

## Overview

Construct mode is Ralph's autonomous execution mode for implementing specs. It runs a staged loop that progresses through investigation, building, and validation until the spec is fully implemented or a failure condition occurs.

## Architecture

```
                           +------------------+
                           |   CONSTRUCT      |
                           |   MODE ENTRY     |
                           +--------+---------+
                                    |
                                    v
    +----------------------------------------------------------------------+
    |                         ITERATION N                                   |
    |                                                                       |
    |  +---------------+     +---------------+     +-------------------+    |
    |  |  INVESTIGATE  |---->|    BUILD      |---->|     VALIDATE      |    |
    |  | (issues ->    |     | (execute      |     | (verify code vs   |    |
    |  |  tasks)       |     |  tasks)       |     |  spec)            |    |
    |  +-------+-------+     +-------+-------+     +---------+---------+    |
    |          |                     |                       |              |
    |          |                     |                       v              |
    |          |                     |              +--------+--------+     |
    |          |                     |              | For each task:  |     |
    |          |                     |              |  - ACCEPT or    |     |
    |          |                     |              |  - REJECT       |     |
    |          |                     |              |                 |     |
    |          |                     |              | For spec gaps:  |     |
    |          |                     |              |  - New TASKS    |     |
    |          |                     |              |  - New ISSUES   |     |
    |          |                     |              +---------+-------+     |
    |          |                     |                        |             |
    |          +---------------------+------------------------+             |
    |                                |                                      |
    |                    [Failure Condition?]                               |
    |                      /              \                                 |
    |                    NO               YES                               |
    |                     |                |                                |
    +----------------------------------------------------------------------+
                          |                |
                          v                v
                   [Pending work?]     DECOMPOSE
                    /          \           |
                  YES           NO         |
                   |             |         |
                   v             v         v
               ITERATE      TERMINATE   ITERATE
               NEXT                     NEXT
```

## Modes vs Stages

**Mode** = Top-level execution mode of Ralph (renamed from "build mode" to "construct mode")
- `plan` - Generate tasks from a spec
- `construct` - Execute the staged loop to implement a spec
- `status` - Query current state

**Stage** = Phase within construct mode's loop
- `investigate` - Turn issues/questions into tasks
- `build` - Execute tasks in priority order
- `validate` - Compare completed work against spec, create new work
- `decompose` - Handle failures by breaking down work

## Task Prioritization

Both PLAN and VALIDATE stages create new tasks/issues. They share the same prioritization logic, which runs **at the end of each stage** before transitioning.

### Prioritization Algorithm

```
PRIORITIZE(tasks):
  1. Build dependency graph
  2. For each task without explicit priority:
     - Estimate complexity (small/medium/large)
     - Check if blocking other tasks
     - Check if blocked by other tasks
  3. Assign priority:
     - HIGH: Small tasks that unblock many others
     - HIGH: Critical path items (most dependents)
     - MEDIUM: Standard implementation tasks
     - LOW: Nice-to-have, documentation, cleanup
  4. Sort tasks by: priority DESC, then dependency order
```

### When Prioritization Runs

| Stage | Creates Work? | Prioritizes? |
|-------|---------------|--------------|
| PLAN | Yes (initial tasks) | Yes, at end |
| INVESTIGATE | Yes (from issues) | No (inherits from issue) |
| BUILD | No | No |
| VALIDATE | Yes (gaps, new issues) | Yes, at end |
| DECOMPOSE | Yes (subtasks) | No (inherits from parent) |

### Shared Prioritization Logic

PLAN and VALIDATE both call the same prioritization function:

```
ralph task prioritize
```

This command:
1. Reads all pending tasks
2. Analyzes dependencies between tasks
3. Estimates complexity based on task description
4. Assigns/updates priority field
5. Commits the updated plan.jsonl

## Construct Mode Flow

### Entry

```bash
ralph construct [spec]
```

### Iteration Loop

Each iteration consists of three phases executed sequentially:

```
INVESTIGATE -> BUILD -> VALIDATE
```

#### Phase 1: INVESTIGATE

**Purpose**: Turn questions/issues into actionable tasks.

```
+-----------------+
|   INVESTIGATE   |
+-----------------+
        |
        v
  [Issues exist?]
   /          \
  YES          NO
   |            |
   v            v
 Process     Skip to
 Issues      BUILD
   |
   v
 Create tasks
 from issues
   |
   v
 Clear resolved
 issues
   |
   v
  BUILD
```

**Actions**:
1. Query all pending issues: `ralph query issues`
2. For each issue, spawn investigation subagent
3. Convert findings to tasks or mark out-of-scope
4. Clear processed issues

**Exit**: Proceed to BUILD

#### Phase 2: BUILD

**Purpose**: Execute tasks in priority/dependency order until none remain.

```
+---------------+
|     BUILD     |
+---------------+
        |
        v
  +------------+
  |  Get next  |
  |   task     |<-----------+
  +-----+------+            |
        |                   |
        v                   |
  [Tasks remain?]           |
   /          \             |
  NO          YES           |
   |            |           |
   v            v           |
VALIDATE   Execute task     |
           (highest priority|
            unblocked)      |
                |           |
                v           |
           Mark done        |
                |           |
                +-----------+
```

**Task Selection**:
1. Filter to unblocked tasks (all deps satisfied)
2. Sort by priority (high > medium > low)
3. Take first task

**Actions per task**:
1. Load task details
2. Execute implementation
3. Run acceptance criteria
4. Mark task done: `ralph task done`
5. Loop back for next task

**Exit**: When no pending tasks remain, proceed to VALIDATE

#### Phase 3: VALIDATE

**Purpose**: Compare completed work (tasks + code) against spec to identify gaps, create new work items, and accept/reject completed tasks.

```
+--------------------+
|      VALIDATE      |
+--------------------+
          |
          v
    Read spec requirements
          |
          v
    Compare done tasks + code
    against spec
          |
          v
    For each done task:
    +---[Meets acceptance?]---+
    |                         |
   YES                        NO
    |                         |
    v                         v
  ACCEPT                   REJECT
  (remove task)            (tombstone,
                            stays for retry)
          |
          v
    For each spec requirement:
    +---[Fully satisfied?]---+
    |                        |
   YES                       NO
    |                        |
    v                        v
  (nothing)              Create new
                         issue/task
          |
          v
    PRIORITIZE ALL
    PENDING TASKS
    (shared logic with PLAN)
          |
          v
    [Any pending work?]
     /              \
    NO              YES
     |                |
     v                v
  TERMINATE       ITERATE
                  NEXT
```

**Actions**:
1. Read spec: `ralph/specs/<spec>`
2. **Evaluate each done task** against its acceptance criteria:
   - **Accepted**: Remove from plan (task completed successfully)
   - **Rejected**: Add tombstone, task remains for retry or decomposition
3. **Evaluate spec requirements** against code + completed work:
   - Identify gaps (missing features, incomplete implementations)
   - Identify new issues (bugs found, edge cases missed)
   - Create tasks for missing work: `ralph task add '{"name": "...", "accept": "..."}'`
   - Create issues for problems found: `ralph issue add "description"`
4. **Prioritize all pending tasks**: `ralph task prioritize`
   - Uses shared prioritization logic (same as PLAN stage)
   - Considers dependencies, complexity, and critical path
   - Must complete before transitioning to next iteration
5. **Decision**:
   - If spec fully satisfied (no pending tasks/issues): TERMINATE
   - Otherwise: Continue to next iteration

**Gap Types**:
| Gap Type | Action |
|----------|--------|
| Missing feature | Create task |
| Incomplete implementation | Reject task + create follow-up task |
| Bug discovered | Create issue |
| Edge case not handled | Create task or issue |
| Test coverage gap | Create task |
| Spec ambiguity | Create issue (needs clarification)

## Failure Conditions

At any point during INVESTIGATE, BUILD, or VALIDATE:

```
+-------------------+
|  FAILURE MONITOR  |
+-------------------+
        |
        v
  Monitors for:
  - Timeout (stage exceeds time limit)
  - Context overrun (context window exceeded)
        |
        v
  [Failure detected?]
   /              \
  NO              YES
   |                |
   v                v
Continue        INTERRUPT
stage           current work
                    |
                    v
                Mark current
                work as REJECTED
                    |
                    v
                DECOMPOSE
```

### Timeout Failure

**Trigger**: A stage exceeds its configured time limit.

**Response**:
1. Interrupt current execution
2. Capture execution log
3. Mark current task/issue as rejected with `kill_reason: "timeout"`
4. Transition to DECOMPOSE

### Context Overrun Failure

**Trigger**: Context window exceeds threshold (e.g., 90% of max tokens).

**Response**:
1. Interrupt current execution
2. Capture execution log  
3. Mark current task/issue as rejected with `kill_reason: "context_limit"`
4. Transition to DECOMPOSE

## DECOMPOSE Stage

**Purpose**: Break down failed work into smaller units.

```
+----------------+
|   DECOMPOSE    |
+----------------+
        |
        v
  Read kill log
  (head/tail only!)
        |
        v
  Analyze failure:
  - What was attempted
  - Where it got stuck
  - What output flooded context
        |
        v
  Create 2-5 smaller tasks
  from failed work
        |
        v
  Delete original
  failed task
        |
        v
  ITERATE NEXT
  (immediately)
```

**Key Rules**:
1. NEVER read entire kill log (it caused the context explosion)
2. Use `head -50` and `tail -100` to sample log
3. Each subtask must be completable in one iteration
4. Include notes about verbose output to suppress
5. After decomposition, immediately start next iteration

## State Machine

```
+-------------------------------------------------------------------------+
|                          CONSTRUCT MODE                                  |
|                                                                          |
|  ITERATION N                                                             |
|  ===========                                                             |
|                                                                          |
|  +-------------+       +-----------+       +-------------+               |
|  | INVESTIGATE |------>|   BUILD   |------>|   VALIDATE  |               |
|  | (issues ->  |       | (execute  |       | (verify vs  |               |
|  |  tasks)     |       |  tasks)   |       |  spec)      |               |
|  +------+------+       +-----+-----+       +------+------+               |
|         |                    |                    |                      |
|         |                    |                    |                      |
|    [FAILURE]            [FAILURE]           [VALIDATION]                 |
|    (timeout/            (timeout/            RESULTS                     |
|     context)             context)               |                        |
|         |                    |          +-------+-------+                |
|         v                    v          |               |                |
|     +---+--------------------+---+   ACCEPT          GAPS                |
|     |       DECOMPOSE           |   tasks          FOUND                 |
|     | (break failed work into   |      |               |                 |
|     |  smaller tasks)           |      |               v                 |
|     +------------+--------------+      |    +----------+----------+      |
|                  |                     |    | - Reject bad tasks  |      |
|                  |                     |    | - Create new tasks  |      |
|                  |                     |    | - Create new issues |      |
|                  |                     |    | - Prioritize work   |      |
|                  |                     |    +----------+----------+      |
|                  |                     |               |                 |
|                  +----------+----------+---------------+                 |
|                             |                                            |
|                             v                                            |
|                    [PENDING WORK?]                                       |
|                      /         \                                         |
|                    YES          NO                                       |
|                     |            |                                       |
|                     v            v                                       |
|              ITERATION N+1   TERMINATE                                   |
|              (loop back)     (spec complete)                             |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Task States During Construct

```
                          TASK LIFECYCLE
                          
       +--------+         +--------+         +----------+
       | PENDING|-------->|  DONE  |-------->| ACCEPTED |
       +----+---+         +----+---+         | (removed |
            |                  |             | from plan)|
            |                  |             +----------+
            |                  |                 
            |             [VALIDATE]             
            |             checks task            
            |                  |                 
            |          [meets acceptance?]       
            |            /           \           
            |          YES            NO         
            |           |              |         
            |           v              v         
            |       ACCEPTED      +----+-----+   
            |                     | REJECTED |   
            |                     |(tombstone)|  
            |                     +----+-----+   
            |                          |         
            |   [execution failure]    |         
            |   (timeout/context)      |         
            |           |              |         
            +---------->+<-------------+         
                        |                        
                        v                        
                   DECOMPOSE                     
                   (split into                   
                    subtasks)                    

  VALIDATE may also CREATE NEW WORK:
  
    Spec Gap Found -----> New TASK (pending)
    Bug Discovered -----> New ISSUE (investigate)
    Edge Case Missed ---> New TASK or ISSUE
```

## CLI Commands

### Mode Commands

| Command | Description |
|---------|-------------|
| `ralph construct [spec]` | Enter construct mode for spec |
| `ralph construct --timeout <ms>` | Set stage timeout |
| `ralph construct --max-iterations <n>` | Limit iterations |

### Query Commands

| Command | Output | Description |
|---------|--------|-------------|
| `ralph query stage` | String | Current stage: INVESTIGATE, BUILD, VALIDATE, DECOMPOSE |
| `ralph query iteration` | Number | Current iteration number |
| `ralph query next` | JSON | Next action with item |

### Task Commands

| Command | Description |
|---------|-------------|
| `ralph task add <json>` | Add a new task |
| `ralph task done` | Mark current task as done |
| `ralph task accept` | Accept all done tasks (remove from plan) |
| `ralph task reject "reason"` | Reject done task (add tombstone) |
| `ralph task prioritize` | Re-prioritize all pending tasks |

### Prioritization Command

`ralph task prioritize` is called by both PLAN and VALIDATE stages:

```bash
ralph task prioritize [--spec <file>]
```

**Behavior**:
1. Load all pending tasks for the current (or specified) spec
2. Build dependency graph
3. For each task, compute priority based on:
   - Explicit priority (if set, preserved)
   - Number of tasks blocked by this task
   - Estimated complexity from task name/notes
   - Position in critical path
4. Update priority field for tasks without explicit priority
5. Commit updated plan.jsonl

**Output**:
```json
{
  "prioritized": 5,
  "high": 2,
  "medium": 2,
  "low": 1
}
```

### Stage Transitions

Stages are determined by state:

| State | Stage |
|-------|-------|
| Has issues | INVESTIGATE |
| Has pending tasks | BUILD |
| Has done tasks, no pending | VALIDATE |
| Has rejected task with kill_reason | DECOMPOSE |
| Empty (no tasks, no issues) | COMPLETE |

## Configuration

```jsonl
{"t": "config", "timeout_ms": 300000, "max_iterations": 10, "context_threshold": 0.9}
```

| Field | Default | Description |
|-------|---------|-------------|
| `timeout_ms` | 300000 (5 min) | Max time per stage |
| `max_iterations` | 10 | Max iterations before abort |
| `context_threshold` | 0.9 | Context usage % that triggers overrun |

## Logging

Each stage execution logs to:
```
build/ralph-logs/ralph-<timestamp>-<stage>.log
```

On failure, the log path is stored in the rejected task:
```jsonl
{"t": "task", "id": "t-abc", "name": "...", "s": "p", "kill_reason": "timeout", "kill_log": "build/ralph-logs/ralph-20260119-build.log"}
```

## Example Flow

```
Iteration 1:
  INVESTIGATE: 2 issues -> 3 tasks created
  BUILD: t-1 done, t-2 done, t-3 [TIMEOUT]
  -> DECOMPOSE: t-3 split into t-3a, t-3b

Iteration 2:
  INVESTIGATE: (no issues)
  BUILD: t-3a done, t-3b done
  VALIDATE: 
    - t-3a ACCEPTED (meets criteria)
    - t-3b REJECTED (incomplete edge case)
    - Gap found: missing error handling
    - NEW TASK: t-4 (error handling)
    - NEW ISSUE: i-1 (flaky test discovered)
    - PRIORITIZE: t-3b(high), t-4(medium)
  -> ITERATE NEXT

Iteration 3:
  INVESTIGATE: i-1 -> t-5 created
  BUILD: t-3b done, t-4 done, t-5 done
  VALIDATE: 
    - All tasks ACCEPTED
    - Spec requirements satisfied
    - PRIORITIZE: (no pending tasks)
  -> TERMINATE
```

## Acceptance Criteria

- [ ] Rename "build mode" to "construct mode" in CLI and code
- [ ] Implement three-phase iteration loop: INVESTIGATE -> BUILD -> VALIDATE
- [ ] BUILD stage processes tasks in priority/dependency order
- [ ] VALIDATE stage compares done tasks against spec requirements
- [ ] VALIDATE stage creates new tasks/issues for identified gaps
- [ ] VALIDATE can accept (clear) or reject (tombstone) individual tasks
- [ ] Implement `ralph task prioritize` command with shared logic
- [ ] PLAN stage calls prioritize at end before transitioning
- [ ] VALIDATE stage calls prioritize at end before transitioning
- [ ] Prioritization considers dependencies, complexity, and critical path
- [ ] Timeout failure detection interrupts stage and triggers DECOMPOSE
- [ ] Context overrun detection interrupts stage and triggers DECOMPOSE  
- [ ] DECOMPOSE stage reads failure log (head/tail only) and creates subtasks
- [ ] Failed tasks marked with `kill_reason` and `kill_log` fields
- [ ] DECOMPOSE immediately triggers next iteration (no manual intervention)
- [ ] Spec acceptance terminates construct mode
- [ ] Configuration supports timeout, max iterations, context threshold
- [ ] Stage logs written to build/ralph-logs/
