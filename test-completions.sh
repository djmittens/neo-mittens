#!/bin/bash

# Source the completion script
source powerplant/ralph-completion.bash

# Verify completion function is defined
type _ralph_completions > /dev/null 2>&1 || { echo "_ralph_completions function not defined"; exit 1; }

# Simulate tab completion
test_completion() {
    local input="$1"
    shift
    local expected=("$@")
    
    # Simulate tab completion context
    COMP_WORDS=(ralph "$input")
    COMP_CWORD=1
    unset COMPREPLY
    _ralph_completions
    
    # Print completions for debugging
    echo "Completions for input '$input': ${COMPREPLY[@]}"
    
    # Check if results match expected
    for exp in "${expected[@]}"; do
        found=0
        for reply in "${COMPREPLY[@]}"; do
            if [[ "$reply" == "$exp" ]]; then
                found=1
                break
            fi
        done
        if [[ $found -eq 0 ]]; then
            echo "Expected '$exp' not found in completions"
            exit 1
        fi
    done
}

# Test main command completions
test_completion "" init plan build status watch stream query task issue set-spec log help 1 5 10 20 50
test_completion "pl" plan
test_completion "-" --max-cost --max-failures --completion-promise --no-ui

echo "Bash completions test passed successfully"