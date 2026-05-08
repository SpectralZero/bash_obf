#!/usr/bin/env bash
# demo_test.sh — medium complexity, deterministic output, no external deps
# Safe; all potentially dangerous operations are simulated.

set -o pipefail
shopt -s extglob

PASS=0
FAIL=0
function pass() { echo "[PASS] $*"; (( PASS += 1 )); }
function fail() { echo "[FAIL] $*"; (( FAIL += 1 )); }

# --- Basic variables ---
name="world"
[[ "$name" == "world" ]] && pass "basic variable" || fail "basic variable"

# --- Parameter expansion ---
str="hello-world"
[[ ${#str} -eq 11 ]] && pass "length" || fail "length"
[[ "${str:0:5}" == "hello" ]] && pass "substring" || fail "substring"
[[ "${str#*-}" == "world" ]] && pass "prefix strip" || fail "prefix strip"
[[ "${str%-*}" == "hello" ]] && pass "suffix strip" || fail "suffix strip"

# default value
unset unknown
[[ "${unknown:-default}" == "default" ]] && pass "default value" || fail "default value"

# --- Arithmetic ---
a=5; b=3
(( a > b )) && pass "arithmetic comparison" || fail "arithmetic comparison"
sum=$(( a + b ))
[[ $sum -eq 8 ]] && pass "addition" || fail "addition"

# pre/post increment
x=0
(( x++ ))
[[ $x -eq 1 ]] && pass "post-increment" || fail "post-increment"

# --- Arrays ---
fruits=("apple" "banana" "cherry")
[[ ${#fruits[@]} -eq 3 ]] && pass "array length" || fail "array length"
[[ "${fruits[1]}" == "banana" ]] && pass "array index" || fail "array index"

fruits+=("date")
[[ ${#fruits[@]} -eq 4 ]] && pass "array append" || fail "array append"

# --- Associative array ---
declare -A colors
colors[red]="#FF0000"
colors[green]="#00FF00"
[[ ${colors[red]} == "#FF0000" ]] && pass "associative array" || fail "associative array"

# --- Conditional / case ---
animal="cat"
case $animal in
    dog) sound="woof" ;;
    cat) sound="meow" ;;
    *)   sound="??" ;;
esac
[[ "$sound" == "meow" ]] && pass "case statement" || fail "case statement"

# --- Loops ---
sumloop=0
for i in 1 2 3; do (( sumloop += i )); done
[[ $sumloop -eq 6 ]] && pass "for loop" || fail "for loop"

cnt=3
while (( cnt > 0 )); do (( cnt-- )); done
[[ $cnt -eq 0 ]] && pass "while loop" || fail "while loop"

# --- Functions ---
function greet() {
    local name="$1"
    echo "Hello, $name"
}
msg=$(greet "Alice")
[[ "$msg" == "Hello, Alice" ]] && pass "function with arg" || fail "function with arg"

# function pointer via variable
function worker_a() { echo "A"; }
func="worker_a"
[[ "$($func)" == "A" ]] && pass "function pointer" || fail "function pointer"

# --- Here-document ---
cat <<EOF > /tmp/demo_test_$$.txt
line1
line2
EOF
content=$(cat /tmp/demo_test_$$.txt)
[[ "$content" == $'line1\nline2' ]] && pass "here-doc" || fail "here-doc"
rm -f /tmp/demo_test_$$.txt

# --- Here-string ---
upper=$(tr '[:lower:]' '[:upper:]' <<< "test")
[[ "$upper" == "TEST" ]] && pass "here-string" || fail "here-string"

# --- Process substitution ---
diff <(echo "same") <(echo "same") >/dev/null
[[ $? -eq 0 ]] && pass "process substitution" || fail "process substitution"

# --- Base64 encode/decode ---
original="payload"
encoded=$(echo -n "$original" | base64)
decoded=$(echo "$encoded" | base64 -d)
[[ "$decoded" == "$original" ]] && pass "base64 decode" || fail "base64 decode"

# --- eval ---
var_name="myvar"
myvar="secret"
eval_res=$(eval "echo \${$var_name}")
[[ "$eval_res" == "secret" ]] && pass "eval indirect" || fail "eval indirect"

# --- Multi-stage eval (simulated) ---
stage1="stage2"
stage2="echo 'stage3 executed'"
stage3_out=$(eval "echo \${$stage1}" && eval "$stage2")
# Capture only the second line (the actual execution)
second_line=$(echo "$stage3_out" | tail -1)
[[ "$second_line" == "stage3 executed" ]] && pass "multi-stage eval" || fail "multi-stage eval"

# --- Simulated red team pattern (downloader selection) ---
downloader="curl"  # pretend
echo "Using $downloader" >/dev/null
[[ $? -eq 0 ]] && pass "downloader simulation" || fail "downloader simulation"

# --- Exit code preservation test ---
( exit 5 )
[[ $? -eq 5 ]] && pass "exit code preservation" || fail "exit code preservation"

# Summary
echo "====================================="
echo "Passed: $PASS"
echo "Failed: $FAIL"
if (( FAIL > 0 )); then
    echo "SOME TESTS FAILED"
    exit 1
else
    echo "ALL TESTS PASSED"
    exit 0
fi
