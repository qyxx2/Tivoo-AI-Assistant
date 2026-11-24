#!/usr/bin/env python3
"""Fail when an HTTP audio generation underruns or fails physical DMA drain."""

import argparse
import json
import re
from pathlib import Path


def verify(text: str, min_playbacks: int = 1) -> dict:
    generations = set(re.findall(r"audio_playback: generation=(\d+) format=", text))
    stats = {}
    errors = []
    for match in re.finditer(
        r"audio_output: generation=(\d+) TX drained=(\d+) underruns=(\d+) "
        r"queue_high_water=(\d+) missed_eofs=(\d+)",
        text,
    ):
        generation, drained, underruns, high_water, missed = map(int, match.groups())
        if str(generation) in stats:
            errors.append(
                f"generation {generation}: repeated result; use a single-boot log"
            )
        stats[str(generation)] = {
            "generation": generation,
            "drained": bool(drained),
            "underruns": underruns,
            "queue_high_water": high_water,
            "missed_eofs": missed,
        }
    if len(generations) < min_playbacks:
        errors.append(
            f"need {min_playbacks} HTTP playbacks, observed {len(generations)}"
        )
    playbacks = []
    for generation in sorted(generations, key=int):
        state = stats.get(generation)
        if state is None:
            errors.append(f"generation {generation}: missing physical output result")
            continue
        playbacks.append(state)
        if not state["drained"] or state["underruns"] or state["missed_eofs"]:
            errors.append(
                f"generation {generation}: output discontinuity or incomplete drain"
            )
    if re.search(r"audio_resource: playback=\S+ state=(?:error|failed|stopped)", text):
        errors.append("HTTP playback failed or was stopped")
    requests = {}
    for playback_id, state in re.findall(
        r"audio_resource: playback=(\S+) state=(\S+)", text
    ):
        requests[playback_id] = state
    for playback_id, state in requests.items():
        if state != "completed":
            errors.append(
                f"playback {playback_id}: terminal completion missing ({state})"
            )
    if sum(state == "completed" for state in requests.values()) < min_playbacks:
        errors.append("not enough completed HTTP requests")
    return {"passed": not errors, "playbacks": playbacks, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--min-playbacks", type=int, default=1)
    args = parser.parse_args()
    if args.min_playbacks < 1:
        parser.error("--min-playbacks must be positive")
    result = verify(args.log.read_text(errors="replace"), args.min_playbacks)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
