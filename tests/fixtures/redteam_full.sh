#!/usr/bin/env bash
# Comprehensive Bash Test Fixture — Red Team & General
# Safe; all harmful actions are simulated/echoed.
# Run: bash redteam_full.sh

set -o pipefail
shopt -s extglob

PASS=0
FAIL=0
function pass() { echo "[PASS] $*"; ((PASS++)); }
function fail() { echo "[FAIL] $*"; ((FAIL++)); }
function cleanup() {
	rm -f /tmp/obf_test_* 2>/dev/null
	rm -f /tmp/test_output_* 2>/dev/null
}
trap cleanup EXIT

echo "===== SECTION 1: Basic Variables & Quoting ====="
x=42
y="hello world"
z='single quotes'
escaped="He said \"hello\""
multi_line="line1
line2"
[[ $x -eq 42 ]] && pass "integer variable" || fail "integer variable"
[[ "$y" == "hello world" ]] && pass "double-quoted variable" || fail "double-quoted variable"
[[ "$z" == "single quotes" ]] && pass "single-quoted assignment" || fail "single-quoted assignment"
[[ "$escaped" == 'He said "hello"' ]] && pass "escaped double quotes" || fail "escaped double quotes"
[[ "$multi_line" == $'line1\nline2' ]] && pass "multiline variable" || fail "multiline variable"

echo "===== SECTION 2: Parameter Expansion ====="
unset empty_var
var="abcdefgh"
[[ ${#var} -eq 8 ]] && pass "\${#var} length" || fail "\${#var} length"
[[ "${var:2:3}" == "cde" ]] && pass "substring" || fail "substring"
[[ "${var#ab}" == "cdefgh" ]] && pass "prefix remove #" || fail "prefix remove #"
[[ "${var##a*e}" == "fgh" ]] && pass "longest prefix remove ##" || fail "longest prefix remove ##"
[[ "${var%gh}" == "abcdef" ]] && pass "suffix remove %" || fail "suffix remove %"
[[ "${var%%d*}" == "abc" ]] && pass "longest suffix remove %%" || fail "longest suffix remove %%"
[[ "${var/def/XYZ}" == "abcXYZgh" ]] && pass "replace first" || fail "replace first"
[[ "${var//d/DD}" == "abcDDDDDDgh" ]] && pass "replace all" || fail "replace all"
default="${empty_var:-DEFAULT}"
[[ "$default" == "DEFAULT" ]] && pass "default value (:-)" || fail "default value (:-)"
assigned="${empty_var:=ASSIGNED}"
[[ "$assigned" == "ASSIGNED" ]] && pass "assign default (:=)" || fail "assign default (:=)"
[[ "${empty_var}" == "ASSIGNED" ]] && pass "assign default actually assigned" || fail "assign default actually assigned"
unset empty_var
alt="${empty_var:+ALTERNATE}"
[[ -z "$alt" ]] && pass "alternate value (:+)" || fail "alternate value (:+)"
empty_var="something"
alt="${empty_var:+ALTERNATE}"
[[ "$alt" == "ALTERNATE" ]] && pass "alternate value (:+ with set)" || fail "alternate value (:+ with set)"
unset mandatory
(out=$(echo "${mandatory:?unset error}" 2>&1); true)
[[ $? -eq 0 ]] && pass "error if unset (subshell)" || fail "error if unset"
mandatory="ok"
[[ "${mandatory:?unset error}" == "ok" ]] && pass "error if unset (set)" || fail "error if unset (set)"
unset mandatory

src="destination"
ref="src"
[[ "${!ref}" == "destination" ]] && pass "indirect expansion \${!ref}" || fail "indirect expansion \${!ref}"

upper_var="foo BAR"
[[ "${upper_var^^}" == "FOO BAR" ]] && pass "upper case \${var^^}" || fail "upper case \${var^^}"
[[ "${upper_var,,}" == "foo bar" ]] && pass "lower case \${var,,}" || fail "lower case \${var,,}"

echo "===== SECTION 3: Arrays ====="
fruits=("apple" "banana" "cherry")
[[ ${#fruits[@]} -eq 3 ]] && pass "array length" || fail "array length"
[[ "${fruits[1]}" == "banana" ]] && pass "array index" || fail "array index"
all="${fruits[*]}"
[[ "$all" == "apple banana cherry" ]] && pass "array expand [*]" || fail "array expand [*]"
fruits+=("date")
[[ ${#fruits[@]} -eq 4 ]] && pass "array append" || fail "array append"
declare -A services
services[web]="nginx"
services[db]="postgres"
[[ ${services[web]} == "nginx" ]] && pass "associative array" || fail "associative array"
[[ ${!services[@]} == *"web"* ]] && pass "assoc keys" || fail "assoc keys"
[[ ${services[@]} == *"postgres"* ]] && pass "assoc values" || fail "assoc values"

echo "===== SECTION 4: Arithmetic Operations ====="
a=5; b=3
sum=$((a + b))
[[ $sum -eq 8 ]] && pass "addition" || fail "addition"
diff=$((a - b))
[[ $diff -eq 2 ]] && pass "subtraction" || fail "subtraction"
prod=$((a * b))
[[ $prod -eq 15 ]] && pass "multiplication" || fail "multiplication"
div=$((a / b))
[[ $div -eq 1 ]] && pass "integer division" || fail "integer division"
mod=$((a % b))
[[ $mod -eq 2 ]] && pass "modulo" || fail "modulo"
pow=$((2**4))
[[ $pow -eq 16 ]] && pass "exponentiation" || fail "exponentiation"
inc=0
(( ++inc ))
[[ $inc -eq 1 ]] && pass "post-increment" || fail "post-increment"
(( --inc ))
[[ $inc -eq 0 ]] && pass "pre-decrement" || fail "pre-decrement"
(( inc+=5 ))
[[ $inc -eq 5 ]] && pass "assignment operator" || fail "assignment operator"
bit_and=$((3 & 2))
[[ $bit_and -eq 2 ]] && pass "bitwise AND" || fail "bitwise AND"
bit_or=$((1 | 2))
[[ $bit_or -eq 3 ]] && pass "bitwise OR" || fail "bitwise OR"
bit_xor=$((3 ^ 1))
[[ $bit_xor -eq 2 ]] && pass "bitwise XOR" || fail "bitwise XOR"
shift_left=$((1 << 3))
[[ $shift_left -eq 8 ]] && pass "left shift" || fail "left shift"
shift_right=$((16 >> 2))
[[ $shift_right -eq 4 ]] && pass "right shift" || fail "right shift"
neg=$((-5))
[[ $neg -eq -5 ]] && pass "unary minus" || fail "unary minus"

if (( 5 > 3 && 2 < 4 )); then
	pass "arithmetic condition (( ))"
else
	fail "arithmetic condition (( ))"
fi

echo "===== SECTION 5: Conditionals ====="
if [ "a" = "a" ]; then
	pass "[ ] string equality"
else
	fail "[ ] string equality"
fi
if [[ "a" == "a" ]]; then
	pass "[[ ]] string equality"
else
	fail "[[ ]] string equality"
fi
if test "a" = "a"; then
	pass "test command"
else
	fail "test command"
fi

num=10
if [[ $num -gt 5 ]]; then
	if [[ $num -lt 20 ]]; then
		pass "nested if"
	else
		fail "nested if"
	fi
fi

val=2
if [[ $val -eq 1 ]]; then
	fail "elif (1)"
elif [[ $val -eq 2 ]]; then
	pass "elif"
else
	fail "elif (3)"
fi

animal="dog"
case $animal in
	cat) res="meow" ;;
	dog) res="woof" ;;
	*) res="??" ;;
esac
[[ "$res" == "woof" ]] && pass "case statement" || fail "case statement"

echo "===== SECTION 6: Loops ====="
sum=0
for i in 1 2 3 4 5; do
	(( sum += i ))
done
[[ $sum -eq 15 ]] && pass "for loop (list)" || fail "for loop (list)"

sum2=0
for (( i=1; i<=5; i++ )); do
	(( sum2 += i ))
done
[[ $sum2 -eq 15 ]] && pass "for loop C-style" || fail "for loop C-style"

while_loop_count=3
while [[ $while_loop_count -gt 0 ]]; do
	(( while_loop_count-- ))
done
[[ $while_loop_count -eq 0 ]] && pass "while loop" || fail "while loop"

until_loop_count=0
until [[ $until_loop_count -ge 3 ]]; do
	(( until_loop_count++ ))
done
[[ $until_loop_count -eq 3 ]] && pass "until loop" || fail "until loop"

sum_loop=0
for i in 1 2 3 4 5; do
	if [[ $i -eq 3 ]]; then
		continue
	fi
	if [[ $i -eq 5 ]]; then
		break
	fi
	sum_loop=$(( sum_loop + i ))
done
[[ $sum_loop -eq 7 ]] && pass "loop break/continue" || fail "loop break/continue"

echo "===== SECTION 7: Functions ====="
function greet() {
	local name="$1"
	echo "Hello, $name"
	return 42
}
msg=$(greet "Alice")
ret=$?
[[ "$msg" == "Hello, Alice" ]] && pass "function with argument" || fail "function with argument"
[[ $ret -eq 42 ]] && pass "function return code" || fail "function return code"

global_var="initial"
function modify_global() {
	global_var="inside"
	local local_var="only_inside"
	echo "local: $local_var"
}
modify_global > /dev/null
[[ "$global_var" == "inside" ]] && pass "global variable modified in function" || fail "global modified"
[[ -z "${local_var:-}" ]] && pass "local variable scoped" || fail "local scoped"

function factorial() {
	if [[ $1 -le 1 ]]; then
		echo 1
	else
		local prev=$(factorial $(( $1 - 1 )))
		echo $(( $1 * prev ))
	fi
}
fact5=$(factorial 5)
[[ $fact5 -eq 120 ]] && pass "recursive function" || fail "recursive function"

function worker_a() { echo "A"; }
function worker_b() { echo "B"; }
selector="worker_a"
result=$("$selector")
[[ "$result" == "A" ]] && pass "function pointer via variable" || fail "function pointer via variable"

echo "===== SECTION 8: File I/O and Redirections ====="
echo "test data" > /tmp/obf_test_file.txt
content=$(< /tmp/obf_test_file.txt)
[[ "$content" == "test data" ]] && pass "input redirection <" || fail "input redirection"
echo "append line" >> /tmp/obf_test_file.txt
lines=$(wc -l < /tmp/obf_test_file.txt)
[[ $lines -eq 2 ]] && pass "append redirection >>" || fail "append redirection"
cat <<EOF > /tmp/obf_test_heredoc.txt
line 1
line 2
EOF
heredoc_content=$(cat /tmp/obf_test_heredoc.txt)
[[ "$heredoc_content" == $'line 1\nline 2' ]] && pass "here-document" || fail "here-document"
tr '[:lower:]' '[:upper:]' <<< "test" > /tmp/obf_test_herestr.txt
result=$(cat /tmp/obf_test_herestr.txt)
[[ "$result" == "TEST" ]] && pass "here-string" || fail "here-string"
exec 3<> /tmp/obf_test_fd.txt
echo "fd write" >&3
exec 3<&-
read fd_line < /tmp/obf_test_fd.txt
[[ "$fd_line" == "fd write" ]] && pass "file descriptor" || fail "file descriptor"
rm -f /tmp/obf_test_fd.txt /tmp/obf_test_file.txt /tmp/obf_test_heredoc.txt /tmp/obf_test_herestr.txt

echo "===== SECTION 9: Pipes and Process Substitution ====="
pipe_output=$(echo "one two three" | tr ' ' '\n' | wc -l)
[[ $pipe_output -eq 3 ]] && pass "simple pipe" || fail "simple pipe"
diff <(echo "hello") <(echo "hello") >/dev/null
[[ $? -eq 0 ]] && pass "process substitution" || fail "process substitution"

echo "===== SECTION 10: Command Substitution ====="
now=$(date +%s)
[[ $now =~ ^[0-9]+$ ]] && pass "command substitution \$()" || fail "command substitution \$()"
host=$(hostname 2>/dev/null || echo "localhost")
[[ -n "$host" ]] && pass "backtick command sub" || fail "backtick command sub"
nested=$(echo $(echo inner))
[[ "$nested" == "inner" ]] && pass "nested command substitution" || fail "nested command substitution"

echo "===== SECTION 11: Dynamic Commands & Indirection ====="
cmd="echo"
"$cmd" "dynamic command test" >/dev/null
[[ $? -eq 0 ]] && pass "variable as command" || fail "variable as command"

declare -A cmds=( ["a"]="echo A" ["b"]="echo B" )
eval "${cmds[a]}" > /tmp/obf_test_cmda.txt
content=$(cat /tmp/obf_test_cmda.txt)
[[ "$content" == "A" ]] && pass "indirect eval via associative array" || fail "indirect eval via associative array"
rm -f /tmp/obf_test_cmda.txt

var_name="my_var"
my_var="secret_value"
eval_res=$(eval "echo \${$var_name}")
[[ "$eval_res" == "secret_value" ]] && pass "eval indirect expansion" || fail "eval indirect expansion"

echo "===== SECTION 14: Extended Globs & Regex ====="
shopt -s extglob
if [[ "photo123.jpg" == photo+([0-9]).jpg ]]; then
	pass "extglob pattern +([0-9])"
else
	fail "extglob pattern +([0-9])"
fi
if [[ "abc" == @(a|b)* ]]; then
	pass "extglob @(pattern)"
else
	fail "extglob @(pattern)"
fi
re="^ab+c$"
if [[ "abbbc" =~ $re ]]; then
	pass "regex match in [[ ]]"
else
	fail "regex match in [[ ]]"
fi
if [[ "xyz" =~ $re ]]; then
	fail "regex non-match positive"
else
	pass "regex non-match"
fi

echo "===== SECTION 15: Red Team Patterns ====="
b64_payload=$(echo -n "echo 'payload executed'" | base64)
decoded_cmd=$(echo "$b64_payload" | base64 -d 2>/dev/null)
eval_result=$(eval "$decoded_cmd")
[[ "$eval_result" == "payload executed" ]] && pass "base64 decode + eval" || fail "base64 decode + eval"

c2_server="http://127.0.0.1"
user_agent="Mozilla/5.0"
function beacon() {
	echo "Beacon to $c2_server with UA $user_agent" > /tmp/obf_test_beacon.txt
}
beacon
[[ -s /tmp/obf_test_beacon.txt ]] && pass "beacon simulation" || fail "beacon simulation"
rm -f /tmp/obf_test_beacon.txt

cron_file="/tmp/obf_test_cron"
echo "* * * * * /bin/echo 'fake persistence'" > "$cron_file"
if [[ -f "$cron_file" ]]; then
	pass "persistence file creation"
else
	fail "persistence file creation"
fi
rm -f "$cron_file"

stage1="stage2_var"
stage2_var="echo 'stage3 executed'"
stage3_exec=$(eval "echo \${$stage1}")
stage_result=$(eval "$stage3_exec")
[[ "$stage_result" == "stage3 executed" ]] && pass "multistage eval chain" || fail "multistage eval chain"

echo "===== SECTION 17: Variable Mangling Stress Test ====="
var_test="VAR_VALUE"
literal_check=$(echo "Literal text containing var_test: $var_test")
if [[ "$literal_check" == *"var_test"* ]]; then
	pass "literal string 'var_test' preserved"
else
	fail "literal string 'var_test' preserved"
fi

if echo "This script uses \${undefined_var} as placeholder." | grep -F '${undefined_var}' >/dev/null; then
	pass "undefined var in literal preserved"
else
	fail "undefined var in literal preserved"
fi

echo "===== FINAL SUMMARY ====="
echo "Tests passed: $PASS"
echo "Tests failed: $FAIL"
if [[ $FAIL -gt 0 ]]; then
	echo "SOME TESTS FAILED"
	exit 1
else
	echo "ALL TESTS PASSED"
	exit 0
fi
