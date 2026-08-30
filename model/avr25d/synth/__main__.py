"""``python -m avr25d.synth`` — regenerate every synthetic scene.

The entry point lives here rather than under ``if __name__ == "__main__"`` in
``scenegen`` because ``synth/__init__`` imports that module: running it as
``-m avr25d.synth.scenegen`` would import it twice under two names, which
Python warns about and which would give the module two copies of its state.
"""

from avr25d.synth.scenegen import _main

raise SystemExit(_main())
