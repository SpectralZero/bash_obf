#!/usr/bin/env bash
# Comprehensive Bash Syntax Test Fixture
# Run: bash comprehensive.sh
# Expected: prints a series of [PASS] markers and returns 0.

set -o pipefail

PASS_COUNT=0
FAIL_COUNT=0
function pass() { echo "[PASS] $*"; ((PASS_COUNT++)); }
function fail() { echo "[FAIL] $*"; ((FAIL_COUNT++)); }

# --- 1. Simple echo & strings ---
echo "=== Basic Output ==="
out="Hello World"
echo "$out"
[[ "$out" == "Hello World" ]] && pass "string equality" || fail "string equality"

# --- 2. Variables & quoting ---
var1="value1"
var2='value2'
var3=123
echo "$var1 $var2 $var3"
[[ -n "$var1" ]] && pass "variable expansion" || fail "variable expansion"

# --- 3. Arithmetic expansion ---
sum=$(( 10 + 5 * 3 ))
echo "Arithmetic: 10 + 5*3 = $sum"
[[ $sum -eq 25 ]] && pass "arithmetic expansion" || fail "arithmetic expansion"

# --- 4. Command substitution ---
host=$(hostname 2>/dev/null || echo "localhost")
echo "Hostname: $host"
[[ -n "$host" ]] && pass "command substitution with fallback" || fail "command substitution with fallback"

# --- 5. Conditionals (if / elif / else) ---
x=7
if [[ $x -gt 5 ]]; then
    echo "x ($x) > 5"
    pass "if statement ([[ ]])"
else
    fail "if statement ([[ ]])"
fi

# --- 6. Case statement ---
animal="cat"
case $animal in
    dog)   sound="woof" ;;
    cat)   sound="meow" ;;
    *)     sound="unknown" ;;
esac
echo "The $animal says $sound"
[[ "$sound" == "meow" ]] && pass "case statement" || fail "case statement"

# --- 7. For loop (explicit list) ---
sum=0
for i in 1 2 3 4 5; do
    (( sum += i ))
done
echo "Sum 1..5 = $sum"
[[ $sum -eq 15 ]] && pass "for loop (list)" || fail "for loop (list)"

# --- 8. Functions (with arguments and return) ---
function greet() {
    local name="$1"
    echo "Hello, $name"
    return 42
}
msg=$(greet "Alice")
ret=$?
echo "Function returned: $ret, message: $msg"
[[ "$msg" == "Hello, Alice" ]] && pass "function with args/return" || fail "function with args/return"
[[ $ret -eq 42 ]] && pass "function return code" || fail "function return code"

# --- 9. Heredoc & file content ---
echo "temp content" > /tmp/test_redirect_$$.txt
read_line=$(</tmp/test_redirect_$$.txt)
echo "Read from file: $read_line"
[[ "$read_line" == "temp content" ]] && pass "file redirection" || fail "file redirection"
rm -f /tmp/test_redirect_$$.txt

# --- Summary ---
echo "========================================="
echo "Tests completed: $PASS_COUNT passed, $FAIL_COUNT failed"
if [[ $FAIL_COUNT -gt 0 ]]; then
    echo "SOME TESTS FAILED"
    exit 1
else
    echo "ALL TESTS PASSED"
    exit 0
fi
