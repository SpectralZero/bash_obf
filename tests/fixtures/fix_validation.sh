#!/usr/bin/env bash
# fix_validation.sh -- exercises every construct that previously
# triggered opaque-blob fallback. Deterministic output for clean diffing.

set -o pipefail

# (1) Array assignment with name=(...)
servers=("alpha" "bravo" "charlie")
status_codes=(200 301 404 500)

# (2) Associative array
declare -A http_names=([200]="OK" [301]="Moved" [404]="NotFound" [500]="Error")

# (3) Function with local + complex parameter expansion
function classify() {
    local code="$1"
    local name="${http_names[$code]:-Unknown}"
    echo "$code $name"
}

# (4) Function returning multi-line and using ${var%%$'\n'*} parameter
#     expansion with ANSI-C quoting -- the exact pattern that broke before
function first_line_of() {
    local input="$1"
    # Take just the first line via complex parameter expansion + $'\n'
    local first="${input%%$'\n'*}"
    echo "$first"
}

# (5) Top-level (( )) arithmetic command
total=0
errors=0
(( total = ${#status_codes[@]} ))

# (6) for loop iterating over array, with nested (( )) and case
for code in "${status_codes[@]}"; do
    classification=$(classify "$code")
    echo "code: $classification"
    case "$code" in
        2*) (( total += 0 )) ;;
        3*) (( total += 1 )) ;;
        4*|5*) (( errors += 1 )) ;;
    esac
done

# (7) Multi-line string + complex param expansion to extract first line
multi=$'first line\nsecond line\nthird line'
header=$(first_line_of "$multi")
echo "header: $header"

# (8) Replace-all parameter expansion ${var//pat/replace}
greeting="hello world hello"
shouted="${greeting//hello/HOWDY}"
echo "shouted: $shouted"

# (9) [[ ... ]] double-bracket test with regex
version="v2.13.7"
if [[ "$version" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    echo "major: ${BASH_REMATCH[1]}"
    echo "minor: ${BASH_REMATCH[2]}"
    echo "patch: ${BASH_REMATCH[3]}"
fi

# (10) String length, substring, prefix/suffix removal
path="/usr/local/share/data.json"
echo "length: ${#path}"
echo "basename: ${path##*/}"
echo "dirname: ${path%/*}"
echo "extension: ${path##*.}"

# (11) Final summary using arithmetic
echo "summary: total=$total errors=$errors servers=${#servers[@]}"

if (( errors > 0 )); then
    exit 2
fi
exit 0
