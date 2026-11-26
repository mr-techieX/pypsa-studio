"""A separate Python process owns optimization; stdout carries progress events."""

import argparse
import contextlib
import json
import os
import sys
import traceback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    # Preserve an event-only pipe, then redirect FD 1 as well as Python stdout.
    # Python-level redirect alone cannot capture a native library's console text.
    event_stream = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    def progress(stage, message):
        event_stream.write(json.dumps({"stage": stage, "message": message}) + "\n")
        event_stream.flush()

    try:
        # Keep third-party console output out of the JSON event protocol.
        with contextlib.redirect_stdout(sys.stderr):
            from .engine import execute_run
            execute_run(args.run, progress)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
