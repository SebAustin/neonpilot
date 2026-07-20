"""Cooldown guard between benchmark trials: adaptive when a temperature signal exists,
fixed-delay fallback otherwise (PLAN.md section 4.4, ASSUMPTIONS.md #8).

`probe_temp_c` and `sleep_fn` are dependency-injected so this module is unit-testable without
sudo, without a real sensor, and without actually sleeping in tests.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable

from neonpilot.models import CooldownPolicy, ThermalSnapshot

#: Polling step (seconds) while waiting for temperature to drop below target.
_POLL_STEP_S = 1.0

#: Best-effort, non-interactive powermetrics sample. Deliberately short and non-blocking;
#: any failure (missing binary, no sudo, timeout) means "no sensor available".
_POWERMETRICS_ARGV = [
    "powermetrics",
    "--samplers",
    "smc",
    "-n",
    "1",
    "-i",
    "200",
]


def default_probe_temp_c() -> float | None:
    """Best-effort CPU temperature read via `powermetrics`. Returns None if unavailable.

    macOS `powermetrics` typically requires elevated privileges; per ASSUMPTIONS.md #8 we never
    prompt for sudo interactively -- any failure here degrades to the elapsed-time fallback.
    """
    try:
        result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, short timeout
            _POWERMETRICS_ARGV,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if "CPU die temperature" in line:
            try:
                return float(line.split(":")[1].strip().rstrip("C").strip())
            except (IndexError, ValueError):
                return None
    return None


def cooldown(
    policy: CooldownPolicy,
    *,
    probe_temp_c: Callable[[], float | None] = default_probe_temp_c,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ThermalSnapshot:
    """Wait between benchmark trials, adaptively when a temperature signal is available.

    Behavior (PLAN.md section 4.4):
    - If a temperature reading is available and already at/below `target_temp_c`: skip
      immediately (`source="idle-skip"`, `cooldown_s=0`).
    - If a temperature reading is available but above target: poll every ~1s, sleeping, until
      below target or `max_cooldown_s` elapses (`source="powermetrics"`).
    - If no temperature reading is available at all: sleep a fixed `fixed_delay_s` (capped at
      `max_cooldown_s`) and report `source="elapsed-fallback"`.
    """
    if policy.target_temp_c is not None:
        temp = probe_temp_c()
        if temp is not None:
            return _adaptive_cooldown(policy, temp, probe_temp_c, sleep_fn)

    delay = min(policy.fixed_delay_s, policy.max_cooldown_s)
    if delay > 0:
        sleep_fn(delay)
    return ThermalSnapshot(
        source="elapsed-fallback", cpu_temp_c=None, throttled=None, cooldown_s=delay
    )


def _adaptive_cooldown(
    policy: CooldownPolicy,
    initial_temp: float,
    probe_temp_c: Callable[[], float | None],
    sleep_fn: Callable[[float], None],
) -> ThermalSnapshot:
    target = policy.target_temp_c
    assert target is not None  # guarded by caller
    if initial_temp <= target:
        return ThermalSnapshot(
            source="idle-skip", cpu_temp_c=initial_temp, throttled=False, cooldown_s=0.0
        )

    temp: float | None = initial_temp
    waited = 0.0
    while temp is not None and temp > target and waited < policy.max_cooldown_s:
        sleep_fn(_POLL_STEP_S)
        waited += _POLL_STEP_S
        temp = probe_temp_c()
    return ThermalSnapshot(
        source="powermetrics", cpu_temp_c=temp, throttled=None, cooldown_s=waited
    )
