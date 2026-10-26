"""Flexure geometry reconstruction: sections, centrelines, member profiles.

Two extraction strategies, and the choice between them matters:

``extract_members``
    Sweeps cutting planes along a straight axis. Fast and simple, correct for a member
    that is single-valued along some axis -- a strap, a simple arch.

``trace_centerline``
    Marches along the member, correcting onto the centreline at each step. Needed for
    anything that doubles back, a serpentine meander above all. On a meander the axis
    sweep does not merely lose accuracy, it returns confident nonsense, so both now
    carry guards that refuse rather than report a wrong path.
"""

from .centerline import CenterlineError, CenterlineStation, Member, extract_members
from .section import CrossSection, SectionError, section_solid
from .tracing import TraceError, seed_from_extreme_point, trace_centerline

__all__ = [
    "CenterlineError",
    "CenterlineStation",
    "CrossSection",
    "Member",
    "SectionError",
    "TraceError",
    "extract_members",
    "section_solid",
    "seed_from_extreme_point",
    "trace_centerline",
]
