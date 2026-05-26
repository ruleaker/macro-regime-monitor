"""Production module for the macro regime dashboard.

The research/ directory tested 14 signal-zone combinations across 4 decades.
This module exposes only what passed the stability test, plus one
narrative-only signal (MCAP_M2) kept for reference with an explicit
'failed stability' tombstone.

See research/findings.md for the full audit trail.
"""

__all__ = ["signals", "conditional", "plots", "render"]
