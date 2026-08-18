#!/usr/bin/env bash
set -euo pipefail

main() {
    local out="${1:-/tmp/out.txt}"
    shift || true
    local -a dirs=("$@")
    [[ ${#dirs[@]} -eq 0 ]] && dirs=("$HOME" "/tmp")

    mkdir -p "$(dirname "$out")"

    {
        echo "Args: $#"
        for d in "${dirs[@]}"; do
            if [[ -d "$d" ]]; then
                printf '%-20s %s\n' "$d" "$(du -sh "$d" | cut -f1)"
            else
                echo "Missing: $d" >&2
            fi
        done
        printf 'Total processed: %d\n' "${#dirs[@]}"
    } > "$out"

    cat <<EOF > "$out.README"
Generated at $(date)
By $(id -un)
EOF

    echo "Done: $out"
}

main "$@"
