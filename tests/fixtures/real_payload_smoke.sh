#!/usr/bin/env bash
# real_payload_smoke.sh — sanitised real-world red-team patterns
# This fixture exercises the cross-product of bash features that
# actually appear together in operational scripts.  Synthetic fixtures
# cover individual features; this covers the patterns.
#
# Safe: all network/disk ops are simulated via echo/temp files.
# Deterministic: no timestamps, no PIDs, fixed paths.

set -o pipefail

PASS=0
FAIL=0
pass() { echo "[PASS] $*"; PASS=$((PASS+1)); }
fail() { echo "[FAIL] $*"; FAIL=$((FAIL+1)); }

# ============================================================================
# Pattern 1: Config file parser (read + IFS + arrays + functions)
# Real scripts parse /etc/foo.conf or ~/.toolrc — exercises the combination
# of read, IFS manipulation, associative arrays, and functions that individual
# fixtures test in isolation but never together.
# ============================================================================
echo "==== Pattern 1: Config Parser ===="

declare -A config
parse_config() {
    local input="$1"
    while IFS='=' read -r key value; do
        key=$(echo "$key" | tr -d '[:space:]')
        value=$(echo "$value" | tr -d '[:space:]')
        [[ -z "$key" || "$key" == \#* ]] && continue
        config["$key"]="$value"
    done <<< "$input"
}

config_data="host=10.0.0.1
port=443
# This is a comment
proto=https
timeout=30"

parse_config "$config_data"
[[ "${config[host]}" == "10.0.0.1" ]] && pass "config: host parsed" || fail "config: host"
[[ "${config[port]}" == "443" ]] && pass "config: port parsed" || fail "config: port"
[[ "${config[proto]}" == "https" ]] && pass "config: proto parsed" || fail "config: proto"
[[ -z "${config[comment]}" ]] && pass "config: comment skipped" || fail "config: comment"
echo

# ============================================================================
# Pattern 2: Retry loop with exponential backoff (arithmetic + functions + traps)
# Real implants and C2 callbacks use this exact pattern.
# ============================================================================
echo "==== Pattern 2: Retry with Backoff ===="

simulate_request() {
    local attempt=$1
    # Simulate: first 2 attempts fail, third succeeds
    if (( attempt >= 3 )); then
        echo "200"
        return 0
    fi
    echo "503"
    return 1
}

max_retries=5
delay=1
attempt=1
success=0

while (( attempt <= max_retries )); do
    status=$(simulate_request "$attempt")
    if [[ "$status" == "200" ]]; then
        success=1
        break
    fi
    delay=$((delay * 2))
    attempt=$((attempt + 1))
done

[[ $success -eq 1 ]] && pass "retry: succeeded on attempt $attempt" || fail "retry: all failed"
[[ $attempt -eq 3 ]] && pass "retry: correct attempt count" || fail "retry: attempt=$attempt expected 3"
[[ $delay -eq 4 ]] && pass "retry: backoff doubled correctly" || fail "retry: delay=$delay expected 4"
echo

# ============================================================================
# Pattern 3: Data exfil staging (base64 + temp files + heredocs + pipelines)
# Real payloads stage data to temp, encode, chunk, and "send" — exercises
# the exact feature combination that breaks when str-shred meets encode.
# ============================================================================
echo "==== Pattern 3: Data Staging ===="

staging_dir="/tmp/obf_smoke_staging"
mkdir -p "$staging_dir"

cat <<'PAYLOAD' > "$staging_dir/raw.txt"
hostname=targetbox
user=operator
data=sensitive_credentials_here
PAYLOAD

# Encode
encoded=$(base64 < "$staging_dir/raw.txt")
[[ -n "$encoded" ]] && pass "staging: base64 encoded" || fail "staging: encode"

# Decode and verify round-trip
decoded=$(echo "$encoded" | base64 -d)
original=$(cat "$staging_dir/raw.txt")
[[ "$decoded" == "$original" ]] && pass "staging: round-trip intact" || fail "staging: round-trip"

# Chunk into 20-byte pieces (simulates network chunking)
chunk_count=$(echo "$encoded" | fold -w 20 | wc -l)
(( chunk_count > 1 )) && pass "staging: chunked into $chunk_count pieces" || fail "staging: chunking"

rm -rf "$staging_dir"
echo

# ============================================================================
# Pattern 4: Dynamic dispatch table (assoc arrays + eval + function pointers)
# C2 frameworks dispatch commands via string lookup tables — this is the
# pattern most likely to break when id-mangle meets indirection meets encode.
# ============================================================================
echo "==== Pattern 4: Command Dispatch ===="

handler_scan() { echo "scan_result: 3 hosts found"; }
handler_exfil() { echo "exfil_result: 42 bytes sent"; }
handler_persist() { echo "persist_result: cron installed"; }

declare -A dispatch=(
    [scan]=handler_scan
    [exfil]=handler_exfil
    [persist]=handler_persist
)

for cmd_name in scan exfil persist; do
    fn="${dispatch[$cmd_name]}"
    output=$("$fn")
    case "$cmd_name" in
        scan)    [[ "$output" == "scan_result: 3 hosts found" ]]    && pass "dispatch: $cmd_name" || fail "dispatch: $cmd_name" ;;
        exfil)   [[ "$output" == "exfil_result: 42 bytes sent" ]]   && pass "dispatch: $cmd_name" || fail "dispatch: $cmd_name" ;;
        persist) [[ "$output" == "persist_result: cron installed" ]] && pass "dispatch: $cmd_name" || fail "dispatch: $cmd_name" ;;
    esac
done
echo

# ============================================================================
# Pattern 5: Privilege check + conditional execution path
# Real payloads check UID/capabilities before choosing a code path.
# Exercises nested conditionals + command substitution + string comparison.
# ============================================================================
echo "==== Pattern 5: Privilege Routing ===="

get_priv_level() {
    local uid
    uid=$(id -u 2>/dev/null || echo "1000")
    if (( uid == 0 )); then
        echo "root"
    elif (( uid < 1000 )); then
        echo "system"
    else
        echo "user"
    fi
}

priv=$(get_priv_level)
[[ "$priv" =~ ^(root|system|user)$ ]] && pass "priv: valid level ($priv)" || fail "priv: invalid"

# Conditional path based on privilege
case "$priv" in
    root)   method="direct"   ;;
    system) method="suid"     ;;
    user)   method="sudo"     ;;
    *)      method="unknown"  ;;
esac
[[ -n "$method" ]] && pass "priv: method selected ($method)" || fail "priv: no method"
echo

# ============================================================================
# Pattern 6: Log obfuscation (tr + sed pipeline + process substitution)
# Operational scripts often sanitize their own logs — exercises pipelines,
# process substitution, and tr/sed together.
# ============================================================================
echo "==== Pattern 6: Log Sanitization ===="

raw_log="2024-01-15 Connection from 192.168.1.100 user=admin pass=secret123"
sanitized=$(echo "$raw_log" | sed 's/pass=[^ ]*/pass=REDACTED/g' | sed 's/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/[REDACTED_IP]/g')

[[ "$sanitized" == *"REDACTED"* ]] && pass "log: password redacted" || fail "log: password"
[[ "$sanitized" != *"secret123"* ]] && pass "log: no plaintext leak" || fail "log: plaintext leak"
[[ "$sanitized" == *"REDACTED_IP"* ]] && pass "log: IP redacted" || fail "log: IP"
echo

# ============================================================================
# Pattern 7: Multi-stage payload assembly (eval + here-string + subshell)
# The canonical obfuscation pattern: assemble a command string, eval it
# inside a subshell, capture the output.
# ============================================================================
echo "==== Pattern 7: Payload Assembly ===="

part1="echo"
part2=" 'assembled"
part3=" payload'"
full_cmd="${part1}${part2}${part3}"

assembled_out=$(eval "$full_cmd")
[[ "$assembled_out" == "assembled payload" ]] && pass "assembly: eval concat" || fail "assembly: eval concat"

# Nested: eval inside subshell
nested_out=$(bash -c "echo nested_\$(echo payload)")
[[ "$nested_out" == "nested_payload" ]] && pass "assembly: nested subshell" || fail "assembly: nested"
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
