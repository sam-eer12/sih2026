"""Decision layer — traversability, tracking, planning, explanation.

IMPLEMENTATION_PLAN.md §6.8–§6.10.  PRD §7.5.

Ownership
---------
Sameer  : traversability.py, tracker.py          (Days 7–8, drop-in ready)
Anuj    : costmap.py, planner.py, explain.py     (Days 7–8)

All five modules share the same CellGrid / RingGrid / Track types defined in
core/ and server/protocol.py.  Sameer's modules are written against the §6.2
cell schema and can be dropped in the moment this package exists.

This __init__ imports nothing by default so that a missing optional dependency
(e.g. onnxruntime) does not break ``import avr25d.decision``.
"""
