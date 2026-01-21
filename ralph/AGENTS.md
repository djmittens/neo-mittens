# Ralph Agent Development Lifecycle (SDLC)

## Development Workflow

### Stages of Change
1. All changes to Ralph go through the `construct` stage
2. Each change requires comprehensive testing
3. Code must pass strict quality checks before acceptance

### Migration Phases
1. **Structure:** Establish core architectural layout
2. **Extract Modules:** Break monolithic code into modular components
3. **Extract Commands:** Separate command-line interface logic
4. **Extract Stages:** Modularize stage-specific behaviors
5. **Extract TUI:** Separate terminal user interface components
6. **Tests:** Comprehensive test suite implementation
7. **Cleanup:** Refine, optimize, and remove technical debt

## Testing Requirements

### Unit Tests
- All new functions require unit tests
- Use mocking for external dependencies
- Tests must:
  - Run without network access
  - Complete in < 30 seconds
  - Use minimal fixtures
- Coverage must not decrease

### End-to-End (E2E) Tests
- New commands require E2E tests
- Tests must:
  - Use temporary directories for isolation
  - Mock opencode calls
  - Clean up after execution
  - Complete in < 60 seconds

## Code Style Guidelines

### Function and Module Constraints
- Type hints required on all public functions
- Docstrings mandatory for public functions
- Max function length: ≤ 50 lines
- Max function complexity: ≤ 10
- Max module length: ≤ 500 lines
- Max class methods: ≤ 15

### Complexity Targets
- Use `radon cc` to verify complexity
- No function should have complexity ≥ 11
- Aim for clear, concise, and readable code

## Self-Improvement Loop

### Specification Generation
- Ralph can create and improve its own specs
- Use `ralph construct` on specs in `ralph/specs/`
- Continuous, incremental self-refinement

## Local Development

### Development Mode
- Changes take effect immediately
- Bootstrap ensures seamless package installation
- Maintain existing functionality during refactoring

## Principles

1. Incremental Refactoring
2. Maintain Existing Behavior
3. Strict Quality Enforcement
4. Automated Testing and Validation
5. Continuous Self-Improvement