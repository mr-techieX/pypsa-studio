"""Distinguish uncomputed native placeholders from real, possibly zero results."""

import json
import re

import pandas as pd
from .run_layout import metadata_path


PIECEWISE_COST_INPUT = {
    "capital_cost_piecewise_opt": "capital_cost",
    "marginal_cost_piecewise_opt": "marginal_cost",
}
_HIGHS_MIP = re.compile(rb"(?m)^MIP [^\r\n]+ has \d+ rows; \d+ cols; \d+ nonzeros; [1-9]\d* integer variables\b")


def has_nondefault_values(frame, default):
    """Ignore blanks and default placeholders; do not round real results."""
    for name in frame:
        numeric = pd.to_numeric(frame[name], errors="coerce")
        if (numeric.notna() & numeric.ne(default)).any():
            return True
    return False


def highs_integer_run(directory):
    """Positive evidence only: every window was solved as an integer HiGHS model."""
    try:
        with metadata_path(directory, "run_config.json").open("rb") as stream:
            config = json.loads(stream.read(4 * 1024**2))
        if not isinstance(config, dict) or config.get("solver") != "highs":
            return False
        if "horizon" in config and config.get("execution") == "sequential; no look-ahead":
            count = config.get("total_steps")
            if type(count) is not int or not 1 <= count <= 10000 or config.get("completed_steps") != count:
                return False
            logs = (directory / "steps" / f"step-{number:04d}" / "highs.log" for number in range(1, count + 1))
        else:
            logs = (directory / "highs.log",)
        for path in logs:
            if not path.resolve().is_relative_to(directory):
                return False
            with path.open("rb") as stream:
                if not _HIGHS_MIP.search(stream.read(4096)):
                    return False
        return True
    except (OSError, ValueError):
        return False
