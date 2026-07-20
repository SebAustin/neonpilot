"""R4 (PLAN.md section 8): the project directory itself contains spaces
("Arm Create- AI Optimization Challenge"), so every shell script must quote its variable
expansions. This walks scripts/*.sh character-by-character (tracking single/double-quote
state) and flags any `$VAR`/`${VAR}` expansion that occurs outside of quotes.
"""

from __future__ import annotations

import re
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_VAR_START = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\{")


def _iter_shell_scripts():
    yield from _SCRIPTS_DIR.glob("*.sh")


def _find_unquoted_var_expansions(line: str) -> list[str]:
    """Return the `$...` substrings in `line` that expand outside single/double quotes."""
    violations: list[str] = []
    in_double = False
    in_single = False
    i = 0
    n = len(line)
    while i < n:
        char = line[i]
        if char == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if char == "$" and not in_single and not in_double and i + 1 < n:
            if line[i + 1] == "(":  # command substitution / arithmetic -- not a bare var
                i += 2
                continue
            match = _VAR_START.match(line, i + 1)
            if match:
                violations.append(line[i : i + 1 + match.end() - (i + 1)])
        i += 1
    return violations


def test_scripts_directory_has_at_least_one_script():
    assert list(_iter_shell_scripts()), "expected scripts/*.sh to exist"


def test_no_unquoted_variable_expansions_in_shell_scripts():
    violations = []
    for script in _iter_shell_scripts():
        for lineno, line in enumerate(script.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip().startswith("#"):
                continue
            for var in _find_unquoted_var_expansions(line):
                violations.append(f"{script.name}:{lineno}: unquoted {var!r} in: {line.strip()}")
    assert not violations, "unquoted $VAR usage found:\n" + "\n".join(violations)
