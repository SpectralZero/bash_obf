#!/bin/bash
# Fixture: opaque_blob_recovery
# Tests constructs that previously caused bashlex to fail and drop
# the entire script into opaque-blob mode:
#   - $'...' ANSI-C quoting
#   - (( )) arithmetic commands
#   - ${var%%pattern} complex parameter expansion
#   - ${#var} string length
#   - name=(...) array assignments
#   - ${arr[@]} array expansion

greeting="Hello World"
names=("Alice" "Bob" "Charlie")

greet_user() {
    local name="${1}"
    local output
    output=$(echo "${greeting}, ${name}!")
    line1="${output%%$'\n'*}"
    echo "${line1}"
}

total_chars=0
for name in "${names[@]}"; do
    result=$(greet_user "${name}")
    (( total_chars += ${#result} ))
    echo "${result} [${#result} chars]"
done
echo "Total characters: ${total_chars}"

# Assertions
[[ "${total_chars}" -gt 0 ]] || { echo "FAIL: total_chars is 0"; exit 1; }
[[ "${#names[@]}" -eq 3 ]] || { echo "FAIL: names array wrong size"; exit 1; }
echo "[PASS] opaque_blob_recovery"
