#!/usr/bin/env bash
# ultimate_stress_test.sh -- exhaustive bash feature & obfuscation resilience test
# Safe. All potentially dangerous commands are simulated.
# Output is deterministic (no timestamps, no PIDs, fixed temp paths).

shopt -s extglob
set -o pipefail
# We do NOT enable set -e / set -u here because some tests rely on unset variables.

PASS=0
FAIL=0
function pass() { echo "[PASS] $*"; (( PASS += 1 )); }
function fail() { echo "[FAIL] $*"; (( FAIL += 1 )); }

cleanup() {
  rm -f /tmp/obf_stress_* 2>/dev/null
}
trap cleanup EXIT

# ============================================================================
# Section 1: Parameter Expansion -- all forms
# ============================================================================
echo "==== Section 1: Parameter Expansion ===="

str="hello-world"
( [[ ${#str} -eq 11 ]] ) && pass "length (${#str})" || fail "length"
[[ "${str:1:4}" == "ello" ]] && pass "substring :1:4" || fail "substring"
[[ "${str^^}" == "HELLO-WORLD" ]] && pass "upper ^^" || fail "upper"
[[ "${str,,}" == "hello-world" ]] && pass "lower ,," || fail "lower"
[[ "${str#h*o}" == "-world" ]] && pass "prefix #" || fail "prefix"
[[ "${str##h*o}" == "rld" ]] && pass "longest prefix ##" || fail "longest prefix"
[[ "${str%o*}" == "hello-w" ]] && pass "suffix %" || fail "suffix"
[[ "${str%%o*}" == "hell" ]] && pass "longest suffix %%" || fail "longest suffix"
[[ "${str/o/X}" == "hellX-world" ]] && pass "replace first /" || fail "replace first"
[[ "${str//o/X}" == "hellX-wXrld" ]] && pass "replace all //" || fail "replace all"
[[ "${str/#hello/HI}" == "HI-world" ]] && pass "replace prefix /#" || fail "replace prefix"
[[ "${str/%world/WORLD}" == "hello-WORLD" ]] && pass "replace suffix /%" || fail "replace suffix"

unset undefined_var
[[ "${undefined_var:-default}" == "default" ]] && pass "default (:-)" || fail "default"
[[ "${undefined_var:=assigned}" == "assigned" ]] && pass "assign default (:=-)" || fail "assign default (1)"
[[ "$undefined_var" == "assigned" ]] && pass "assign default effect" || fail "assign default effect"
unset undefined_var

undefined_var="set"
[[ "${undefined_var:+alt}" == "alt" ]] && pass "alternate (:+) set" || fail "alternate set"
unset undefined_var
[[ -z "${undefined_var:+alt}" ]] && pass "alternate (:+) unset" || fail "alternate unset"

( ret="$(echo "${mandatory:?bang}" 2>&1)"; true )
[[ $? -eq 0 ]] && pass "error if unset (:) ?)" || fail "error if unset"

base="value"
indirect="base"
[[ "${!indirect}" == "value" ]] && pass "indirect expansion" || fail "indirect expansion"

mixed="MiXeD"
[[ "${mixed,,}" == "mixed" ]] && pass "lower case ,," || fail "lower"
[[ "${mixed^^}" == "MIXED" ]] && pass "upper case ^^" || fail "upper"
[[ "${mixed~~}" == "mIxEd" ]] && pass "toggle case ~~" || fail "toggle case"

echo

# ============================================================================
# Section 2: Arithmetic
# ============================================================================
echo "==== Section 2: Arithmetic ===="
a=7
b=3
[[ $(( a + b )) -eq 10 ]] && pass "addition" || fail "addition"
[[ $(( a - b )) -eq 4 ]] && pass "subtraction" || fail "subtraction"
[[ $(( a * b )) -eq 21 ]] && pass "multiplication" || fail "multiplication"
[[ $(( a / b )) -eq 2 ]] && pass "integer division" || fail "division"
[[ $(( a % b )) -eq 1 ]] && pass "modulo" || fail "modulo"
[[ $(( a ** b )) -eq 343 ]] && pass "exponentiation" || fail "exponentiation"
(( a > b )) && pass "arithmetic comparison >" || fail "arithmetic >"
(( a <= 10 )) && pass "arithmetic <= " || fail "arithmetic <="
[[ $(( 5 & 3 )) -eq 1 ]] && pass "bitwise AND" || fail "bitwise AND"
[[ $(( 5 | 2 )) -eq 7 ]] && pass "bitwise OR" || fail "bitwise OR"
[[ $(( 5 ^ 3 )) -eq 6 ]] && pass "bitwise XOR" || fail "bitwise XOR"
[[ $(( ~5 )) -eq -6 ]] && pass "bitwise NOT" || fail "bitwise NOT"
[[ $(( 1 << 3 )) -eq 8 ]] && pass "left shift" || fail "left shift"
[[ $(( 16 >> 2 )) -eq 4 ]] && pass "right shift" || fail "right shift"

x=0
(( ++x ))
[[ $x -eq 1 ]] && pass "post-increment" || fail "post-increment"
(( ++x ))
[[ $x -eq 2 ]] && pass "pre-increment" || fail "pre-increment"

echo

# ============================================================================
# Section 3: Arrays
# ============================================================================
echo "==== Section 3: Arrays ===="
arr=( zero one two three )
[[ ${arr[1]} == "one" ]] && pass "indexed array access" || fail "indexed array"
[[ ${#arr[@]} -eq 4 ]] && pass "array length" || fail "array length"
arr+=("four")
[[ "${arr[-1]}" == "four" ]] && pass "array append" || fail "array append"
[[ "${!arr[@]}" == "0 1 2 3 4" ]] && pass "array keys" || fail "array keys"
sliced=("${arr[@]:1:2}")
[[ "${sliced[0]}" == "one" && "${sliced[1]}" == "two" ]] && pass "array slice" || fail "array slice"

declare -A map=([name]=Alice [age]=30)
[[ ${map[name]} == "Alice" ]] && pass "assoc array access" || fail "assoc array"
[[ ${#map[@]} -eq 2 ]] && pass "assoc length" || fail "assoc length"
map[city]="London"
[[ ${map[city]} == "London" ]] && pass "assoc add" || fail "assoc add"
keys="${!map[@]}"
[[ "$keys" == *"name"* ]] && pass "assoc keys contain name" || fail "assoc keys"

spaced=( "first item" "second item" )
[[ "${spaced[0]}" == "first item" ]] && pass "array element with spaces" || fail "array spaces"

echo

# ============================================================================
# Section 4: Loops & Control Flow
# ============================================================================
echo "==== Section 4: Loops ===="

sum=0
for i in 1 2 3 4; do (( sum += i )); done
[[ $sum -eq 10 ]] && pass "for loop (list)" || fail "for loop (list)"

sum2=0
for (( i=0; i<4; i++ )); do (( sum2 += i )); done
[[ $sum2 -eq 6 ]] && pass "for loop C-style" || fail "for loop C-style"

cnt=0
while (( cnt < 3 )); do (( cnt++ )); done
[[ $cnt -eq 3 ]] && pass "while loop" || fail "while loop"

cnt=0
until (( cnt >= 2 )); do (( cnt++ )); done
[[ $cnt -eq 2 ]] && pass "until loop" || fail "until loop"

sum3=0
for i in 1 2 3 4 5; do
  (( i == 3 )) && continue
  (( i == 5 )) && break
  (( sum3 += i ))
done
[[ $sum3 -eq 7 ]] && pass "break/continue" || fail "break/continue"

echo

# ============================================================================
# Section 5: Conditionals & Case
# ============================================================================
echo "==== Section 5: Conditionals ===="
if [[ 1 == 1 ]]; then
  pass "if [[ ]]"
else
  fail "if [[ ]]"
fi

if [ "a" = "a" ]; then
  pass "if [ ]"
else
  fail "if [ ]"
fi

var=2
if [[ $var -eq 1 ]]; then
  fail "elif (1)"
elif [[ $var -eq 2 ]]; then
  pass "elif"
else
  fail "elif (2)"
fi

animal="cat"
case $animal in
  dog) s="woof" ;;
  cat) s="meow" ;;
  *) s="unknown" ;;
esac
[[ "$s" == "meow" ]] && pass "case statement" || fail "case statement"

filename="script.sh"
case $filename in
  *.txt) ext="txt" ;;
  *.sh) ext="sh" ;;
  *) ext="other" ;;
esac
[[ "$ext" == "sh" ]] && pass "case pattern" || fail "case pattern"

echo

# ============================================================================
# Section 6: Functions
# ============================================================================
echo "==== Section 6: Functions ===="
function greet() {
  local name="$1"
  echo "Hi $name"
}
out=$(greet "Bob")
[[ "$out" == "Hi Bob" ]] && pass "function with arg" || fail "function arg"

function return_test() {
  return 42
}
return_test
[[ $? -eq 42 ]] && pass "function return code" || fail "return code"

outer="global"
function scoper() {
  local outer="local"
  echo "$outer"
}
inner=$(scoper)
[[ "$inner" == "local" && "$outer" == "global" ]] && pass "local variable" || fail "local variable"

function factorial() {
  if (( $1 <= 1 )); then echo 1; return; fi
  echo $(( $1 * $(factorial $(( $1 - 1 ))) ))
}
res=$(factorial 5)
[[ $res -eq 120 ]] && pass "recursive function" || fail "recursive"

function worker_a() { echo "A"; }
function worker_b() { echo "B"; }
f="worker_a"
[[ "$($f)" == "A" ]] && pass "function pointer" || fail "function pointer"

echo

# ============================================================================
# Section 7: I/O & Redirections
# ============================================================================
echo "==== Section 7: I/O & Redirections ===="
echo "line1" > /tmp/obf_stress_io.txt
echo "line2" >> /tmp/obf_stress_io.txt
lines=$(wc -l < /tmp/obf_stress_io.txt)
[[ $lines -eq 2 ]] && pass "redirections > >>" || fail "redirections"

exec 3</tmp/obf_stress_io.txt
read -u 3 first_line
exec 3<&-
[[ "$first_line" == "line1" ]] && pass "read from fd" || fail "read from fd"

cat <<EOF > /tmp/obf_stress_heredoc.txt
heredoc line1
heredoc line2
EOF
heredoc_content=$(cat /tmp/obf_stress_heredoc.txt)
[[ "$heredoc_content" == $'heredoc line1\nheredoc line2' ]] && pass "here-doc" || fail "here-doc"

cat <<'EOF' > /tmp/obf_stress_heredoc_literal.txt
$HOME keeps literal
EOF
content_literal=$(cat /tmp/obf_stress_heredoc_literal.txt)
[[ "$content_literal" == '$HOME keeps literal' ]] && pass "here-doc literal (no expand)" || fail "here-doc literal"

upper=$(tr '[:lower:]' '[:upper:]' <<< "test")
[[ "$upper" == "TEST" ]] && pass "here-string" || fail "here-string"

rm -f /tmp/obf_stress_io.txt /tmp/obf_stress_heredoc.txt /tmp/obf_stress_heredoc_literal.txt

echo

# ============================================================================
# Section 8: Pipes & Process Substitution
# ============================================================================
echo "==== Section 8: Pipes & Process Substitution ===="
pipe_res=$(echo "a b c" | tr ' ' '\n' | wc -l)
[[ $pipe_res -eq 3 ]] && pass "pipe" || fail "pipe"

diff <(echo "hello") <(echo "hello") >/dev/null
[[ $? -eq 0 ]] && pass "process substitution" || fail "process substitution"

echo

# ============================================================================
# Section 9: Command Substitution (nested, backticks)
# ============================================================================
echo "==== Section 9: Command Substitution ===="
host=$(hostname 2>/dev/null || echo "localhost")
[[ -n "$host" ]] && pass "command substitution (fallback)" || fail "command substitution"

nested=$(echo $(echo $(echo "deep")))
[[ "$nested" == "deep" ]] && pass "nested command sub" || fail "nested command sub"

bt=`echo "backtick"`
[[ "$bt" == "backtick" ]] && pass "backtick command sub" || fail "backtick"

echo

# ============================================================================
# Section 11: Traps
# ============================================================================
echo "==== Section 11: Traps ===="
trap_exit=0
function on_exit() { trap_exit=1; }
trap on_exit EXIT
( trap 'echo trapped' EXIT; true ) > /tmp/obf_stress_trap.out
trap_msg=$(cat /tmp/obf_stress_trap.out)
[[ "$trap_msg" == "trapped" ]] && pass "subshell EXIT trap" || fail "EXIT trap"
rm -f /tmp/obf_stress_trap.out

( set -e; trap 'echo caught error' ERR; false ) 2>/dev/null > /tmp/obf_stress_err.out
[[ "$(cat /tmp/obf_stress_err.out)" == "caught error" ]] && pass "ERR trap" || fail "ERR trap"
rm -f /tmp/obf_stress_err.out

echo

# ============================================================================
# Section 12: eval & dynamic dispatch
# ============================================================================
echo "==== Section 12: eval & dynamic dispatch ===="
var_name="myvar"
myvar="secret"
eval_res=$(eval "echo \${$var_name}")
[[ "$eval_res" == "secret" ]] && pass "eval indirect expansion" || fail "eval indirect"

cmd="echo"
"$cmd" "dynamic dispatch" >/dev/null
[[ $? -eq 0 ]] && pass "variable as command" || fail "variable as command"

declare -A cmds=([test]="echo OK")
eval "${cmds[test]}" > /tmp/obf_stress_cmd.txt
[[ "$(cat /tmp/obf_stress_cmd.txt)" == "OK" ]] && pass "assoc eval dispatch" || fail "assoc dispatch"
rm -f /tmp/obf_stress_cmd.txt

echo

# ============================================================================
# Section 13: Extended Globs & Regex
# ============================================================================
echo "==== Section 13: Extglob & Regex ===="
if [[ "file123.txt" == file+([0-9]).txt ]]; then
  pass "extglob +([0-9])"
else
  fail "extglob +([0-9])"
fi

if [[ "abc" == @(a|b)* ]]; then
  pass "extglob @(pattern)"
else
  fail "extglob @(pattern)"
fi

if [[ "hello123" =~ ^h.*3$ ]]; then
  pass "regex match"
else
  fail "regex match"
fi

echo

# ============================================================================
# Section 14: Here-documents with quoting & special characters
# ============================================================================
echo "==== Section 14: Heredocs & Special Characters ===="
cat <<'EOF' > /tmp/obf_stress_special.txt
line with backtick: `echo dont`
dollar: $HOME
backslash: \
EOF
special_content=$(cat /tmp/obf_stress_special.txt)
expected=$'line with backtick: `echo dont`\ndollar: $HOME\nbackslash: \\'
[[ "$special_content" == "$expected" ]] && pass "heredoc with special chars (literal)" || fail "heredoc special chars"
rm -f /tmp/obf_stress_special.txt

echo

# ============================================================================
# Section 15: Arithmetic Expressions with multiple operations
# ============================================================================
echo "==== Section 15: Complex Arithmetic ===="
res=$(( (5+3)*2 + 4/2 ))
[[ $res -eq 18 ]] && pass "complex arithmetic" || fail "complex arithmetic"
val=10
(( val > 5 ? (val=1) : (val=0) ))
[[ $val -eq 1 ]] && pass "arithmetic ternary" || fail "arithmetic ternary"

echo

# ============================================================================
# Section 16: Variable Attributes (declare, readonly, export)
# ============================================================================
echo "==== Section 16: Variable Attributes ===="
export EXPORTED_VAR="exported"
bash -c '[[ "$EXPORTED_VAR" == "exported" ]]' && pass "export variable" || fail "export variable"

declare -i int_var=5
int_var+=5
[[ $int_var -eq 10 ]] && pass "integer variable (declare -i)" || fail "integer variable"

declare -r readonly_var="ro"
( unset readonly_var 2>/dev/null )
[[ $? -ne 0 ]] && pass "readonly variable" || fail "readonly variable"

declare -l lower_var="HeLLo"
[[ "$lower_var" == "hello" ]] && pass "lowercase attribute (-l)" || fail "lowercase attribute"

declare -u upper_var="HeLLo"
[[ "$upper_var" == "HELLO" ]] && pass "uppercase attribute (-u)" || fail "uppercase attribute"

echo

# ============================================================================
# Section 17: Brace Expansion
# ============================================================================
echo "==== Section 17: Brace Expansion ===="
res=$(echo {a,b,c}{1,2})
[[ "$res" == "a1 a2 b1 b2 c1 c2" ]] && pass "brace expansion" || fail "brace expansion"

echo

# ============================================================================
# Section 18: Subshells & Grouping
# ============================================================================
echo "==== Section 18: Subshells & Grouping ===="
var_outer="original"
( var_outer="changed" )
[[ "$var_outer" == "original" ]] && pass "subshell isolation" || fail "subshell isolation"

{
  var_outer="changed by curly"
}
[[ "$var_outer" == "changed by curly" ]] && pass "curly braces grouping" || fail "curly braces"

echo

# ============================================================================
# Section 19: Advanced Parameter Expansion Nesting
# ============================================================================
echo "==== Section 19: Expansion Torture ===="
a="abc.def.ghi"
[[ "${a#*.}" == "def.ghi" ]] && pass "#*. removal" || fail "#*."
[[ "${a##*.}" == "ghi" ]] && pass "##*. removal" || fail "##*."
[[ "${a%.*}" == "abc.def" ]] && pass "%.* removal" || fail "%.*"
[[ "${a%%.*}" == "abc" ]] && pass "%%.* removal" || fail "%%.*"

echo

# ============================================================================
# Section 20: Red Team Patterns (Safe)
# ============================================================================
echo "==== Section 20: Red Team Patterns ===="

b64_original="redteam payload"
b64_encoded=$(echo -n "$b64_original" | base64)
decoded=$(echo "$b64_encoded" | base64 -d)
[[ "$decoded" == "$b64_original" ]] && pass "base64 encode/decode" || fail "base64"

encoded_rot13=$(echo "secret" | tr 'a-z' 'n-za-m')
decoded_rot13=$(echo "$encoded_rot13" | tr 'a-z' 'n-za-m')
[[ "$decoded_rot13" == "secret" ]] && pass "ROT13 (tr)" || fail "ROT13"

cron_file="/tmp/obf_stress_cron_test"
echo "@reboot /bin/echo persistence" > "$cron_file"
if [[ -f "$cron_file" ]]; then
  pass "persistence file creation"
else
  fail "persistence file creation"
fi
rm -f "$cron_file"

beacon_res=$(echo "beacon to C2" 2>/dev/null)
[[ "$beacon_res" == "beacon to C2" ]] && pass "beacon simulation" || fail "beacon"

stage1="stage2"
stage2="echo 'stage3 executed'"
stage3_cmd=$(eval "echo \${$stage1}")
stage3_out=$(eval "$stage3_cmd")
[[ "$stage3_out" == "stage3 executed" ]] && pass "multi-stage eval chain" || fail "multi-stage eval"

echo

# ============================================================================
# Section 21: Here-strings with special characters
# ============================================================================
echo "==== Section 21: Here-strings Special ===="
var_here="planet"
output=$(cat <<< "hello $var_here")
[[ "$output" == "hello planet" ]] && pass "here-string variable" || fail "here-string variable"

echo

# ============================================================================
# Section 22: read with IFS
# ============================================================================
echo "==== Section 22: read with IFS ===="
IFS=':' read -r user pass uid gid gecos home shell <<< "root:x:0:0:root:/root:/bin/bash"
[[ "$user" == "root" ]] && pass "read with IFS" || fail "read with IFS"

echo

# ============================================================================
# Section 23: declare -n (nameref)
# ============================================================================
echo "==== Section 23: nameref (declare -n) ===="
declare -n ref=original_var
original_var="nameref works"
[[ "$ref" == "nameref works" ]] && pass "nameref variable" || fail "nameref variable"
unset ref original_var

echo

# ============================================================================
# Section 24: Indirect expansion with arrays
# ============================================================================
echo "==== Section 24: Indirect array expansion ===="
arr_var="fruits"
fruits=("apple" "banana")
eval "keys=(\"\${$arr_var[@]}\")"
[[ "${keys[1]}" == "banana" ]] && pass "eval indirect array" || fail "indirect array eval"

echo

# ============================================================================
# Section 25: printf
# ============================================================================
echo "==== Section 25: printf ===="
printf_val=$(printf '%d %s' 255 "bytes")
[[ "$printf_val" == "255 bytes" ]] && pass "printf decimal and string" || fail "printf"

printf_val2=$(printf '%04d' 7)
[[ "$printf_val2" == "0007" ]] && pass "printf zero padding" || fail "printf zero pad"

echo

# ============================================================================
# Summary
# ============================================================================
echo "==== SUMMARY ===="
echo "Passed: $PASS"
echo "Failed: $FAIL"
if (( FAIL > 0 )); then
  echo "SOME TESTS FAILED"
  exit 1
else
  echo "ALL TESTS PASSED"
  exit 0
fi
