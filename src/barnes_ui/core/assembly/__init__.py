"""Assembly import, joint definition and interference checking.

Phase 4. A single part tells you about a flexure; an assembly tells you where the
flexure has to fit and what it has to avoid while it moves. The important thing this
package does *not* do is infer kinematics: STEP carries placed geometry, never mates,
so a joint axis is a user decision that the software may suggest and must never assume.
See risk R4 in ``docs/07-risk-register.md``.
"""

from __future__ import annotations

__all__: list[str] = []
