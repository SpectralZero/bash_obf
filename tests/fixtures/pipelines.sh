#!/bin/bash
# Fixture: Pipelines, redirections, here-docs
data="line1
line2
line3
special: chars & symbols | pipes"

echo "${data}" | grep -c "line"
echo "${data}" | sort | uniq | wc -l

cat <<EOF
This is a here-document.
It contains multiple lines.
Variable expansion: ${USER:-unknown}
EOF

cat <<'NOEXPAND'
This heredoc has no expansion.
$USER stays literal.
NOEXPAND

echo "redirect test" > /dev/null 2>&1
true && echo "chain success" || echo "chain fail"
