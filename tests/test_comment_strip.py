"""Comment stripping regressions."""

import pytest

from obfush.engine.comment_strip import strip_comments


@pytest.mark.parametrize(("source", "expected"), [
    ("x=1 # comment", "x=1"),
    ("# full line", ""),
    ("#!/bin/bash\necho ok # comment", "#!/bin/bash\necho ok"),
    ("echo '# literal' # comment", "echo '# literal'"),
    ('echo "# literal" # comment', 'echo "# literal"'),
    (r"echo \#literal # comment", r"echo \#literal"),
    ("echo ${#value} # comment", "echo ${#value}"),
    ("echo ${value#prefix} # comment", "echo ${value#prefix}"),
    ("echo ${value##prefix} # comment", "echo ${value##prefix}"),
    (r"echo $'#\n' # comment", r"echo $'#\n'"),
])
def test_strip_comments_preserves_bash_hash_contexts(source, expected):
    assert strip_comments(source) == expected


def test_preserves_heredoc_body_comments():
    source = "cat <<'EOF'\n# payload\nvalue # still data\nEOF\necho ok # remove\n"
    expected = "cat <<'EOF'\n# payload\nvalue # still data\nEOF\necho ok\n"
    assert strip_comments(source) == expected


def test_tracks_multiline_quotes():
    source = 'printf "%s\\n" "line one\n# literal line\nline three" # remove\n'
    expected = 'printf "%s\\n" "line one\n# literal line\nline three"\n'
    assert strip_comments(source) == expected


def test_empty_and_trailing_newline_are_preserved():
    assert strip_comments("") == ""
    assert strip_comments("echo ok\n") == "echo ok\n"
