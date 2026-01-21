#!/usr/bin/env zsh

# Source the zsh completion script
source powerplant/ralph-completion.zsh

# Test completion function
autoload -Uz compinit
compinit

# Function to test completions
test_zsh_completion() {
    local input="$1"
    shift
    local expected=("$@")
    
    # Simulate tab completion
    local -a results
    results=($(ralph "$input" 2>/dev/null))
    
    # Print completions for debugging
    echo "Completions for input '$input': ${results[@]}"
    
    # Check if results match expected
    for exp in "${expected[@]}"; do
        found=0
        for reply in "${results[@]}"; do
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
test_zsh_completion "" init plan build status watch stream query task issue set-spec log help 1 5 10 20 50
test_zsh_completion "pl" plan
test_zsh_completion "-" --max-cost --max-failures --completion-promise --no-ui

echo "Zsh completions test passed successfully"