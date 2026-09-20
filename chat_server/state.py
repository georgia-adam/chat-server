"""Atomic JSON persistence for Hub snapshots."""

import json
import os


def load_state(path: str) -> dict:
    """Return the saved snapshot, or an empty dict if there is none."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)  # atomic on POSIX
