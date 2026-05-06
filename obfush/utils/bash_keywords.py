"""
Bash reserved words, special variables, and builtin commands.

These sets are used by layers (especially id_mangle) to know what
must NEVER be renamed or altered.
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────
# Reserved words — bash syntax keywords that cannot be used as identifiers
# ──────────────────────────────────────────────────────────────────────
RESERVED_WORDS: frozenset[str] = frozenset({
    "if", "then", "else", "elif", "fi",
    "case", "esac",
    "for", "while", "until", "do", "done",
    "in",
    "function",
    "select",
    "time",
    "coproc",
    "{", "}",
    "!", "[[", "]]",
})

# ──────────────────────────────────────────────────────────────────────
# Special variables — positional, automatic, and shell-managed
# These must NEVER be mangled.
# ──────────────────────────────────────────────────────────────────────
SPECIAL_VARIABLES: frozenset[str] = frozenset({
    # Positional parameters
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    # Special parameters
    "@", "*", "#", "?", "!", "$", "-", "_",
    # Common shell variables that should not be renamed
    "BASH", "BASH_VERSION", "BASH_VERSINFO",
    "BASHPID", "BASH_SOURCE", "BASH_LINENO", "BASH_COMMAND",
    "BASH_SUBSHELL", "BASH_EXECUTION_STRING",
    "GROUPS", "HOSTNAME", "HOSTTYPE", "MACHTYPE", "OSTYPE",
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM",
    "PWD", "OLDPWD", "IFS", "PS1", "PS2", "PS3", "PS4",
    "RANDOM", "SECONDS", "LINENO", "FUNCNAME", "FUNCNEST",
    "REPLY", "OPTARG", "OPTIND", "OPTERR",
    "PIPESTATUS", "COMP_WORDS", "COMP_CWORD", "COMP_LINE",
    "EUID", "UID", "PPID", "SHLVL",
    "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    "TMPDIR", "EDITOR", "VISUAL", "PAGER",
    "HISTFILE", "HISTSIZE", "HISTCONTROL", "HISTIGNORE",
    "CDPATH", "DIRSTACK", "GLOBIGNORE",
    "COLUMNS", "LINES",
    "SHELLOPTS", "BASHOPTS",
    "MAILCHECK", "MAIL", "MAILPATH",
    "TMOUT", "FCEDIT", "FIGNORE",
    "INPUTRC", "ENV", "BASH_ENV",
    "POSIXLY_CORRECT",
})

# ──────────────────────────────────────────────────────────────────────
# Builtin commands — these are names, not syntax, but should be
# recognised so layers don't try to substitute unknown builtins.
# ──────────────────────────────────────────────────────────────────────
BUILTIN_COMMANDS: frozenset[str] = frozenset({
    # I/O
    "echo", "printf", "read", "readarray", "mapfile",
    # Variable management
    "export", "local", "declare", "typeset", "unset", "readonly",
    # Execution control
    "eval", "exec", "source", ".", "command", "builtin", "enable",
    # Job control
    "bg", "fg", "jobs", "wait", "kill", "disown", "suspend",
    # Flow control
    "break", "continue", "return", "exit",
    # Argument handling
    "shift", "getopts",
    # Shell options
    "set", "shopt",
    # Directory
    "cd", "pushd", "popd", "dirs", "pwd",
    # Traps & signals
    "trap",
    # String/test
    "test", "[", "true", "false",
    # Misc
    "type", "hash", "help", "let", "logout",
    "alias", "unalias",
    "bind", "caller", "complete", "compgen", "compopt",
    "fc", "history",
    "ulimit", "umask", "times",
    # No-op
    ":",
})

# ──────────────────────────────────────────────────────────────────────
# Common external commands that layers may substitute between
# ──────────────────────────────────────────────────────────────────────
COMMON_EXTERNALS: frozenset[str] = frozenset({
    "cat", "grep", "awk", "sed", "cut", "sort", "uniq",
    "head", "tail", "wc", "tr", "tee", "xargs",
    "find", "ls", "cp", "mv", "rm", "mkdir", "rmdir", "chmod", "chown",
    "curl", "wget", "nc", "ncat", "socat",
    "ssh", "scp", "rsync",
    "base64", "xxd", "od", "hexdump",
    "openssl", "md5sum", "sha256sum",
    "ps", "kill", "pkill", "pgrep",
    "sleep", "date", "hostname", "whoami", "id", "uname",
    "mktemp", "mkfifo",
    "tar", "gzip", "gunzip", "bzip2", "xz", "zip", "unzip",
    "crontab", "at",
    "systemctl", "service",
    "iptables", "nft",
    "python", "python3", "perl", "ruby", "node",
    "bash", "sh", "zsh", "dash",
    "nohup", "screen", "tmux",
    "strace", "ltrace",
})

# ──────────────────────────────────────────────────────────────────────
# Deceptive identifier word pools for id_mangle
# These look like normal admin/operations variable names
# ──────────────────────────────────────────────────────────────────────
DECEPTIVE_WORDS: list[str] = [
    "_config", "_conf", "_cfg", "_settings", "_opts", "_options",
    "_tmp", "_temp", "_tmpdir", "_tmpfile", "_cache",
    "_data", "_dat", "_buf", "_buffer", "_payload",
    "_log", "_log_level", "_log_file", "_log_dir", "_verbose",
    "_output", "_out", "_result", "_ret", "_status", "_rc",
    "_input", "_in", "_src", "_source", "_target", "_dest",
    "_path", "_dir", "_file", "_fname", "_basename",
    "_host", "_hostname", "_addr", "_address", "_port",
    "_user", "_username", "_uid", "_gid", "_group",
    "_pid", "_ppid", "_proc", "_process",
    "_timeout", "_interval", "_delay", "_retry", "_count",
    "_flag", "_mode", "_type", "_kind", "_format",
    "_max", "_min", "_limit", "_threshold", "_size",
    "_key", "_value", "_pair", "_entry", "_item",
    "_prefix", "_suffix", "_sep", "_delim", "_pattern",
    "_err", "_error", "_warn", "_msg", "_message",
    "_init", "_setup", "_cleanup", "_teardown", "_reset",
    "_enabled", "_disabled", "_active", "_locked", "_ready",
    "_backup", "_archive", "_snapshot", "_checkpoint",
    "_worker", "_handler", "_callback", "_hook", "_trigger",
    "_queue", "_stack", "_list", "_array", "_map",
    "_version", "_revision", "_build", "_release",
    "_start", "_stop", "_pause", "_resume",
    "_read", "_write", "_append", "_truncate",
    "_lock", "_unlock", "_sync", "_async",
    "_local", "_remote", "_upstream", "_downstream",
    "_primary", "_secondary", "_fallback", "_default",
]
