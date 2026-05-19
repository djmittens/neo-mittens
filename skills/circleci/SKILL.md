---
name: circleci
description: Fetch CircleCI build results, test failures, artifacts, and job logs to debug CI/CD issues on PRs
license: MIT
compatibility: Requires bash, curl, and a CircleCI API token in ~/.circleci/token
metadata:
  category: testing
  system: circleci-server
---

# CircleCI Build Debugging

Use this skill when debugging CI/CD failures, fetching test results, downloading build artifacts, or investigating failed jobs on CircleCI. This covers both CircleCI Server (on-prem) and CircleCI Cloud instances.

## Environment

| Setting | Value |
|---------|-------|
| CircleCI Server Base URL | `https://gcp-circleci.build.corp.creditkarma.com` |
| CircleCI App URL | `https://app.gcp-circleci.build.corp.creditkarma.com` |
| API Base | `https://gcp-circleci.build.corp.creditkarma.com/api/v2` |
| API v1.1 Base | `https://gcp-circleci.build.corp.creditkarma.com/api/v1.1` |
| Token Settings Page | `https://app.gcp-circleci.build.corp.creditkarma.com/settings/user/tokens` |
| VCS Slug | `gh` (GitHub) |
| Default Org | `ck-private` |
| Auth Header | `Circle-Token: <token>` |
| Token Location | `~/.circleci/token` (plain text file containing just the token) |

## Authentication

A CircleCI Personal API Token is required. The token should be stored in `~/.circleci/token`.

To create a token:
1. Open `https://app.gcp-circleci.build.corp.creditkarma.com/settings/user/tokens` in your browser (VPN required)
2. Click **Create New Token**, give it a name (e.g., `opencode`)
3. Copy the token (it is only shown once) and save it:

```bash
mkdir -p ~/.circleci && echo "YOUR_TOKEN" > ~/.circleci/token && chmod 600 ~/.circleci/token
```

```bash
# Verify token works
CIRCLE_TOKEN=$(cat ~/.circleci/token)
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "https://gcp-circleci.build.corp.creditkarma.com/api/v2/me" | jq .
```

If the token file does not exist, inform the user they need to create one and provide the instructions above.

## URL Parsing

CircleCI build URLs follow this pattern:
```
https://<host>/gh/<org>/<repo>/<build_number>
```

Example: `https://gcp-circleci.build.corp.creditkarma.com/gh/ck-private/daf_dataflow-templates/2247`

Extract from this:
- **host**: `gcp-circleci.build.corp.creditkarma.com`
- **project-slug**: `gh/ck-private/daf_dataflow-templates`
- **build_number** (also called job number): `2247`

For CircleCI Cloud URLs, the host is `app.circleci.com` and the API base is `https://circleci.com/api/v2`.

## Key API Endpoints

All examples use `$BASE=https://gcp-circleci.build.corp.creditkarma.com/api` and `$CIRCLE_TOKEN=$(cat ~/.circleci/token)`.

### 1. Get Job Details (by job number)

Returns job status, duration, executor, and related pipeline/workflow info.

```bash
# API v1.1 - Get build details by build number (most useful for single build URLs)
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v1.1/project/gh/<org>/<repo>/<build_number>" | jq .
```

The v1.1 endpoint returns rich data including:
- `status`: "success", "failed", "running", etc.
- `steps[].actions[]`: Each step with its name, status, output URL, and exit code
- `build_url`: Link back to the UI
- `branch`, `vcs_revision`: Git context
- `workflows`: Workflow name and job name

### 2. Get Test Metadata (failed tests)

Returns structured test results (requires `store_test_results` in the CircleCI config).

```bash
# API v2 - Get test metadata for a job (requires job number from project slug)
# First get the job number from the pipeline
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/project/gh/<org>/<repo>/<build_number>/tests" | jq .
```

Response contains:
- `items[].classname`: Test class
- `items[].name`: Test name
- `items[].result`: "success" or "failure"
- `items[].message`: Failure message/stack trace
- `items[].run_time`: Duration in seconds
- `items[].source`: Test framework

To get only failures:
```bash
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/project/gh/<org>/<repo>/<build_number>/tests" | \
  jq '.items[] | select(.result == "failure")'
```

### 3. Get Job Artifacts

Returns downloadable artifacts (logs, reports, binaries).

```bash
# API v2
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/project/gh/<org>/<repo>/<build_number>/artifacts" | jq .
```

Response contains:
- `items[].path`: Artifact file path
- `items[].url`: Direct download URL
- `items[].node_index`: For parallel jobs

To download an artifact:
```bash
curl -s -L -H "Circle-Token: $CIRCLE_TOKEN" "<artifact_url>" -o <local_filename>
```

### 4. Get Step Output / Build Logs

The v1.1 build details endpoint includes step output URLs. To get the full log for a failed step:

```bash
# First, get the build details
BUILD=$(curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v1.1/project/gh/<org>/<repo>/<build_number>")

# Find failed steps and their output URLs
echo "$BUILD" | jq -r '.steps[] | .actions[] | select(.status == "failed") | {name: .name, output_url: .output_url}'

# Download the log from the output_url
curl -s -H "Circle-Token: $CIRCLE_TOKEN" "<output_url>" | jq -r '.[].message'
```

### 5. Get Pipeline Details

When you need to see all jobs in a workflow (e.g., to find which job failed):

```bash
# Get the pipeline ID from v1.1 build details first, then:
# List workflows for a pipeline
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/pipeline/<pipeline_id>/workflow" | jq .

# List jobs in a workflow
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/workflow/<workflow_id>/job" | jq .
```

### 6. Get Recent Pipelines for a Project

```bash
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/project/gh/<org>/<repo>/pipeline?branch=<branch>" | jq .
```

## Common Workflows

### Workflow 1: Debug a Failed Build (given a URL)

This is the most common workflow. Given a CircleCI build URL:

1. **Parse the URL** to extract org, repo, and build number
2. **Read the token** from `~/.circleci/token`
3. **Get build details** via v1.1 API to understand what failed
4. **Get test results** via v2 API to find specific test failures
5. **Get artifacts** if test reports or logs were stored
6. **Get step logs** for failed steps to see the full error output
7. **Summarize** the failures with actionable information

```bash
#!/bin/bash
CIRCLE_TOKEN=$(cat ~/.circleci/token)
BASE="https://gcp-circleci.build.corp.creditkarma.com/api"
ORG="ck-private"
REPO="daf_dataflow-templates"
BUILD_NUM="2247"

# Step 1: Get build overview
echo "=== Build Details ==="
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v1.1/project/gh/$ORG/$REPO/$BUILD_NUM" | \
  jq '{status, branch, build_url, start_time, stop_time, 
       workflow: .workflows.workflow_name, job: .workflows.job_name}'

# Step 2: Get failed steps
echo "=== Failed Steps ==="
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v1.1/project/gh/$ORG/$REPO/$BUILD_NUM" | \
  jq '.steps[] | .actions[] | select(.status == "failed") | {name, status, exit_code}'

# Step 3: Get test failures
echo "=== Test Failures ==="
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/project/gh/$ORG/$REPO/$BUILD_NUM/tests" | \
  jq '.items[] | select(.result == "failure") | {classname, name, message}'

# Step 4: Get artifacts
echo "=== Artifacts ==="
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/project/gh/$ORG/$REPO/$BUILD_NUM/artifacts" | \
  jq '.items[] | {path, url}'
```

### Workflow 2: Find All Failed Jobs in a Pipeline

When a build URL shows one job but you need the full picture:

1. Get build details to find the `pipeline_id` and `workflow_id`
2. List all jobs in the workflow
3. Identify all failed jobs
4. Get details for each failed job

```bash
CIRCLE_TOKEN=$(cat ~/.circleci/token)
BASE="https://gcp-circleci.build.corp.creditkarma.com/api"

# Get workflow ID from build details
WORKFLOW_ID=$(curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v1.1/project/gh/$ORG/$REPO/$BUILD_NUM" | \
  jq -r '.workflows.workflow_id')

# List all jobs in workflow
curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/workflow/$WORKFLOW_ID/job" | \
  jq '.items[] | {name, status, job_number, type}'
```

### Workflow 3: Download and Read Test Report Artifacts

```bash
CIRCLE_TOKEN=$(cat ~/.circleci/token)
BASE="https://gcp-circleci.build.corp.creditkarma.com/api"

# List artifacts and find test reports
ARTIFACTS=$(curl -s -H "Circle-Token: $CIRCLE_TOKEN" \
  "$BASE/v2/project/gh/$ORG/$REPO/$BUILD_NUM/artifacts")

# Download XML test reports
echo "$ARTIFACTS" | jq -r '.items[] | select(.path | test("test.*\\.xml$")) | .url' | \
  while read url; do
    curl -s -L -H "Circle-Token: $CIRCLE_TOKEN" "$url"
  done
```

## Output Handling

CircleCI API responses can be very large. Follow these rules:

### ALWAYS Do This
- **Pipe through `jq`** to extract only relevant fields
- **Filter for failures first** -- don't dump all passing tests
- **Save large outputs to files** when they exceed ~100 lines
- **Summarize** results before showing raw data

### NEVER Do This
- Dump raw JSON responses into the conversation without filtering
- Download all artifacts without filtering by relevance
- Show full stack traces for every test failure (summarize, then offer details)

## Filtering Tips

```bash
# Only failed tests
jq '.items[] | select(.result == "failure")'

# Only failed steps  
jq '.steps[] | .actions[] | select(.status == "failed")'

# Count failures
jq '[.items[] | select(.result == "failure")] | length'

# Group test failures by class
jq '[.items[] | select(.result == "failure")] | group_by(.classname) | map({class: .[0].classname, count: length, tests: [.[].name]})'

# Get failure messages (truncated)
jq '.items[] | select(.result == "failure") | {classname, name, message: (.message // "no message" | .[0:500])}'
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `401 Unauthorized` | Token is invalid or expired. Regenerate at CircleCI User Settings > Personal API Tokens |
| `404 Not Found` | Check project slug format: `gh/<org>/<repo>`. Ensure you have access to the project |
| No test results returned | The CircleCI config must use `store_test_results` step. Check `.circleci/config.yml` |
| No artifacts returned | The CircleCI config must use `store_artifacts` step |
| Empty step output | Output URLs expire. Recent builds (< 30 days) should have logs available |
| API rate limited (`429`) | Wait and retry. CircleCI Server typically has higher limits than Cloud |
| Connection refused | Ensure VPN is active for corporate CircleCI Server access |

## Dependencies

- `curl` -- HTTP client for API calls
- `jq` -- JSON processing (required for filtering responses)
- VPN connection to access `gcp-circleci.build.corp.creditkarma.com`
- CircleCI Personal API Token stored at `~/.circleci/token`
