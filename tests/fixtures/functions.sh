#!/bin/bash
# Fixture: Functions, conditionals, loops
setup_env() {
    local target_dir="/tmp/test_$$"
    mkdir -p "${target_dir}"
    echo "${target_dir}"
}

check_deps() {
    for cmd in curl wget base64; do
        if command -v "${cmd}" >/dev/null 2>&1; then
            echo "[+] Found: ${cmd}"
        else
            echo "[-] Missing: ${cmd}"
        fi
    done
}

process_items() {
    local items=("alpha" "bravo" "charlie" "delta")
    local count=0
    for item in "${items[@]}"; do
        count=$((count + 1))
        if [ "${item}" = "charlie" ]; then
            echo "Target found at position ${count}"
            return 0
        fi
    done
    return 1
}

main() {
    local workdir
    workdir="$(setup_env)"
    echo "Working directory: ${workdir}"
    check_deps
    if process_items; then
        echo "Success"
    else
        echo "Not found"
    fi
}

main "$@"
