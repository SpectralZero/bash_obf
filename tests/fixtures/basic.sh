#!/bin/bash
# Fixture: Basic variable assignment and echo
msg="Hello World"
count=42
result="${msg} — iteration ${count}"
echo "${result}"
printf '%s\n' "Done: ${count} items processed"
exit 0
