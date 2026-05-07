#!/usr/bin/env bash
# stress_indirection.sh — exercise dynamic dispatch & indirection
# Run: bash stress_indirection.sh
# All output should be deterministic (no timestamps/PIDs),
# so diffing original vs obfuscated is clean.

set -o pipefail

PASS=0
FAIL=0
pass() { echo "[PASS] $*"; ((PASS++)); }
fail() { echo "[FAIL] $*"; ((FAIL++)); }

# --- 1. Simple variable name used in a string ---
tool="hammer"
echo "My favourite tool is the $tool."
[[ "$tool" == "hammer" ]] && pass "variable in string" || fail "variable in string"

# --- 2. Array with symbolic command names ---
declare -A COMMANDS=(
  [get]="echo 'fake-download'"
  [list]="echo 'list-files'"
)
# choose command by a variable
action="get"
eval "${COMMANDS[$action]}" > /dev/null
if [[ $? -eq 0 ]]; then
    pass "associative array dispatch"
else
    fail "associative array dispatch"
fi

# --- 3. Variable holding a command name (indirect execution) ---
real_cmd="echo"
"$real_cmd" "Indirect execution works."
[[ $? -eq 0 ]] && pass "indirect command via variable" || fail "indirect command via variable"

# --- 4. Function pointer via variable ---
function worker_a() { echo "Worker A reporting"; }
function worker_b() { echo "Worker B reporting"; }
selected="worker_b"
"$selected"
[[ $? -eq 0 ]] && pass "function pointer via variable" || fail "function pointer via variable"

# --- 5. Command substitution that contains a variable reference ---
prefix="Config"
echo "${prefix} downloaded successfully"
# The string includes a variable expansion + literal text " downloaded successfully"
# This must not be mangled incorrectly.
line="${prefix} downloaded successfully"
[[ "$line" == "Config downloaded successfully" ]] && pass "variable in command sub string" || fail "variable in command sub string"

# --- 6. Nested indirect reference (${!var}) ---
base_var="nested_value"
ref_var="base_var"
echo "Indirect expand: ${!ref_var}"
[[ "${!ref_var}" == "nested_value" ]] && pass "indirect expansion \${!var}" || fail "indirect expansion \${!var}"

# --- 7. Array index from a variable ---
index_name="1"
packages=("alpha" "beta" "gamma")
echo "Selected package: ${packages[$index_name]}"
[[ "${packages[$index_name]}" == "beta" ]] && pass "array index from variable" || fail "array index from variable"

# --- 8. Function that uses its argument to build a command string ---
function run_tool() {
    local tool_name="$1"
    echo "Running $tool_name ..."
}
run_tool "scanner"
[[ $? -eq 0 ]] && pass "function with arg in string" || fail "function with arg in string"

# --- 9. Variable that echoes another variable’s name (the curl pattern in operational.sh) ---
# Simulates a downloader selection:
downloader="curl"
# real downloader logic would do: $downloader http://...
# Here we just echo what we would run.
echo "Selected downloader: $downloader"
[[ "$downloader" == "curl" ]] && pass "downloader variable preserved" || fail "downloader variable preserved"

# --- 10. Command substitution with embedded variable inside backticks (if eval_mode ok) ---
# Just see if it produces the correct string.
out2=$(echo "Static prefix: $downloader")
echo "$out2"
[[ "$out2" == "Static prefix: curl" ]] && pass "command sub with variable" || fail "command sub with variable"

echo "========================================="
echo "Indirection tests completed: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1 || exit 0
