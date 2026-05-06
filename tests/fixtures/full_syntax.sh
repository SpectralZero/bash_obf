#!/usr/bin/env bash
# Comprehensive Bash Syntax Test Fixture (full)
# Run: bash full_syntax.sh
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

if [ "$x" -eq 7 ]; then
    pass "if statement (test [ ])"
else
    fail "if statement (test [ ])"
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

# --- 8. For loop (C-style) ---
sum2=0
for (( i=1; i<=5; i++ )); do
    (( sum2 += i ))
done
echo "Sum 1..5 (C-style) = $sum2"
[[ $sum2 -eq 15 ]] && pass "for loop (C-style)" || fail "for loop (C-style)"

# --- 9. While loop ---
counter=3
while [[ $counter -gt 0 ]]; do
    echo "  countdown: $counter"
    (( counter-- ))
done
[[ $counter -eq 0 ]] && pass "while loop" || fail "while loop"

# --- 10. Until loop ---
counter=0
until [[ $counter -ge 3 ]]; do
    echo "  countup: $counter"
    (( counter++ ))
done
[[ $counter -eq 3 ]] && pass "until loop" || fail "until loop"

# --- 11. Functions (with arguments and return) ---
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

# --- 12. Variable scope (global vs local) ---
global_var="initial"
function modify_global() {
    global_var="modified inside"
    local local_var="only inside"
    echo "  Inside: global=$global_var, local=$local_var"
}
modify_global
echo "Outside: global=$global_var, local=${local_var:-undefined}"
[[ "$global_var" == "modified inside" ]] && pass "global variable mutation" || fail "global variable mutation"
[[ "${local_var:-undefined}" == "undefined" ]] && pass "local variable scope" || fail "local variable scope"

# --- 13. Arrays (indexed) ---
fruits=(apple banana cherry)
echo "Fruits: ${fruits[*]}"
echo "First fruit: ${fruits[0]}"
echo "All indices: ${!fruits[@]}"
[[ "${fruits[1]}" == "banana" ]] && pass "indexed array" || fail "indexed array"

# --- 14. Parameter expansion (subset bashlex can parse) ---
str="hello-world"
default_val="${undefined_var:-default}"
echo "Default value: $default_val"
[[ "$default_val" == "default" ]] && pass "parameter expansion (default)" || fail "parameter expansion (default)"

# --- 15. Here-string ---
uppercase=$(tr '[:lower:]' '[:upper:]' <<< "test")
echo "Uppercase: $uppercase"
[[ "$uppercase" == "TEST" ]] && pass "here-string" || fail "here-string"

# --- 16. File redirections ---
echo "temp content" > /tmp/test_redirect_$$.txt
read_line=$(</tmp/test_redirect_$$.txt)
echo "Read from file: $read_line"
[[ "$read_line" == "temp content" ]] && pass "file redirection" || fail "file redirection"
rm -f /tmp/test_redirect_$$.txt

# --- 17. Pipes ---
word_count=$(echo "one two three" | tr ' ' '\n' | grep -c .)
echo "Word count: $word_count"
[[ $word_count -eq 3 ]] && pass "pipes" || fail "pipes"

# --- 18. Logical operators (&&, ||) ---
true && pass "logical AND" || fail "logical AND"

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
