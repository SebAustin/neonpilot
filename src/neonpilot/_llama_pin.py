"""Single source of truth for the pinned llama.cpp commit.

The same SHA must also appear in ``scripts/fetch_llama.sh`` (``LLAMA_CPP_SHA``).
``tests/test_pin.py`` asserts the two values are identical so preset provenance can never go
stale silently (PLAN.md section 3.1).
"""

#: Release tag b10069.
LLAMA_CPP_TAG = "b10069"

#: Full commit SHA for LLAMA_CPP_TAG. Never silently re-pin -- see PLAN.md Revision log.
LLAMA_CPP_COMMIT = "178a6c44937154dc4c4eff0d166f4a044c4fceba"
