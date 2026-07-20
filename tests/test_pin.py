"""Assert the pinned llama.cpp SHA is identical in neonpilot/_llama_pin.py and
scripts/fetch_llama.sh (PLAN.md section 3.1: recorded in exactly two places, never drifts).
"""

from __future__ import annotations

import re
from pathlib import Path

from neonpilot._llama_pin import LLAMA_CPP_COMMIT, LLAMA_CPP_TAG

_REPO_ROOT = Path(__file__).parent.parent
_FETCH_SCRIPT = _REPO_ROOT / "scripts" / "fetch_llama.sh"


def test_commit_sha_is_full_length():
    assert len(LLAMA_CPP_COMMIT) == 40
    assert re.fullmatch(r"[0-9a-f]{40}", LLAMA_CPP_COMMIT)


def test_tag_matches_expected_release():
    assert LLAMA_CPP_TAG == "b10069"


def test_fetch_script_pins_the_same_sha():
    script_text = _FETCH_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'LLAMA_CPP_SHA="([0-9a-f]{40})"', script_text)
    assert match is not None, 'scripts/fetch_llama.sh must define LLAMA_CPP_SHA="<40-hex-sha>"'
    assert match.group(1) == LLAMA_CPP_COMMIT
