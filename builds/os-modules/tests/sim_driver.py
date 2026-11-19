"""tests/sim_driver.py — subprocess driver for simulator tests.

The pytest interpreter (feed-dash venv) has no sympy; the system python3
(/usr/bin/python3, sympy 1.12) does. Simulator tests therefore drive the
module through this script under the system python and assert on JSON.
Run: /usr/bin/python3 tests/sim_driver.py deltas|items
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "06_DECISION" / "simulator"))

import simulator  # noqa: E402


def main():
    mode = sys.argv[1]
    if mode == "deltas":
        print(json.dumps([simulator.simulate(s) for s in simulator._load_samples()]))
    elif mode == "items":
        print(json.dumps(simulator.items()))
    else:
        raise SystemExit("unknown mode %r" % mode)


if __name__ == "__main__":
    main()
