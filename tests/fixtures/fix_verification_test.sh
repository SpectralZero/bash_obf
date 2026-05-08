#!/usr/bin/env bash
# fix_verification_test.sh — validate opaque-blob fixes
# Covers: bare declare, indirect assignment, eval indirect, function pointer,
#          associative array, here-docs, process substitution, arithmetic, etc.

set -o pipefail

PASS=0
FAIL=0
function pass() { echo "[PASS] $*"; (( PASS += 1 )); }
function fail() { echo "[FAIL] $*"; (( FAIL += 1 )); }

# --------------------------------------------------
# 1. Bare declare -A (no inline assignment)
# --------------------------------------------------
declare -A colors
colors[red]="#FF0000"
colors[green]="#00FF00"
[[ "${colors[red]}" == "#FF0000" ]] && pass "associative array (bare declare)" || fail "associative array (bare declare)"

# --------------------------------------------------
# 2. Indirect assignment – function pointer via string
# --------------------------------------------------
function worker_a() { echo "A"; }
function worker_b() { echo "B"; }
func="worker_a"          # indirect reference
[[ "$($func)" == "A" ]] && pass "function pointer via string" || fail "function pointer via string"

# --------------------------------------------------
# 3. Indirect assignment – variable name via string
# --------------------------------------------------
myvar="secret_value"
var_name="myvar"         # indirect reference
eval_res=$(eval "echo \${$var_name}")
[[ "$eval_res" == "secret_value" ]] && pass "eval indirect via string" || fail "eval indirect via string"

# --------------------------------------------------
# 4. Bare `declare -i` (integer attribute)
# --------------------------------------------------
declare -i int_var
int_var=5
int_var+=5
[[ $int_var -eq 10 ]] && pass "declare -i integer attribute" || fail "declare -i"

# --------------------------------------------------
# 5. Bare `declare -l` (lowercase attribute)
# --------------------------------------------------
declare -l lower_var
lower_var="HeLLo"
[[ "$lower_var" == "hello" ]] && pass "declare -l lowercase" || fail "declare -l"

# --------------------------------------------------
# 6. Bare `declare -u` (uppercase attribute)
# --------------------------------------------------
declare -u upper_var
upper_var="HeLLo"
[[ "$upper_var" == "HELLO" ]] && pass "declare -u uppercase" || fail "declare -u"

# --------------------------------------------------
# 7. Bare `declare -r` (readonly) – test in subshell
# --------------------------------------------------
declare -r readonly_var="ro"
( unset readonly_var 2>/dev/null )
[[ $? -ne 0 ]] && pass "declare -r readonly" || fail "declare -r"

# --------------------------------------------------
# 8. Standard stuff: parameter expansion, loops, etc.
# --------------------------------------------------
str="hello-world"
[[ "${str#*-}" == "world" ]] && pass "parameter expansion" || fail "parameter expansion"

sum=0
for i in 1 2 3; do (( sum += i )); done
[[ $sum -eq 6 ]] && pass "for loop" || fail "for loop"

# Here-document
cat <<'EOF' > /tmp/fix_test_here.txt
$HOME is literal
EOF
content=$(cat /tmp/fix_test_here.txt)
[[ "$content" == '$HOME is literal' ]] && pass "here-doc literal" || fail "here-doc literal"
rm -f /tmp/fix_test_here.txt

# Process substitution
diff <(echo "same") <(echo "same") >/dev/null && pass "process substitution" || fail "process substitution"

# --------------------------------------------------
# Summary
# --------------------------------------------------
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
