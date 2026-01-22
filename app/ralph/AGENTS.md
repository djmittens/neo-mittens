# Ralph Development Rules

## Overview

Ralph is developed by Ralph. This file defines the SDLC for ralph development.

## Development Workflow

1. Changes to ralph code go through ralph's own construct mode
2. All changes require tests
3. Complexity limits are enforced

## Testing Requirements

- New functions require unit tests
- New commands require e2e tests
- Coverage must not decrease

## Code Style

- Type hints on all public functions
- Docstrings on all public functions
- No function > 50 lines
- No complexity > 10

## Self-Improvement Loop

Ralph can create specs for its own improvement in `ralph/specs/`.
Ralph runs `ralph construct` on its own specs.
