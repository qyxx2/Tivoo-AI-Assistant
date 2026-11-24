"""Physical HTTP playback acceptance must reject completed-but-stuttering audio."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "playback_verifier",
    Path(__file__).resolve().parents[2] / "scripts/verify-p68-playback.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def log(underruns=0, drained=1, missed=0):
    return (
        "audio_playback: generation=4 format=pcm frames=0\n"
        f"audio_output: generation=4 TX drained={drained} underruns={underruns} "
        f"queue_high_water=5120 missed_eofs={missed}\n"
        "audio_resource: playback=example state=completed error=-\n"
    )


def test_completed_but_stuttering_is_failure():
    assert not module.verify(log(underruns=2667))["passed"]


def test_continuous_drained_http_playback_passes():
    assert module.verify(log())["passed"]


def test_prompt_only_cannot_pass_http_acceptance():
    assert not module.verify(log().replace("audio_playback:", "local_prompt:"))[
        "passed"
    ]


def test_missing_output_result_is_failure():
    assert not module.verify("audio_playback: generation=4 format=pcm\n")["passed"]


def test_fault_and_incomplete_drain_are_failures():
    assert not module.verify(log(drained=0))["passed"]
    assert not module.verify(log(missed=1))["passed"]


def test_minimum_real_http_playback_count():
    assert not module.verify(log(), min_playbacks=2)["passed"]


def test_terminal_failure_cannot_pass_even_after_drain():
    assert not module.verify(log().replace("state=completed", "state=failed"))["passed"]


def test_later_unfinished_http_request_cannot_be_hidden_by_success():
    assert not module.verify(
        log() + "audio_resource: playback=next state=playing error=-\n"
    )["passed"]


def test_repeated_generation_cannot_overwrite_earlier_underrun():
    assert not module.verify(log(underruns=2667) + log())["passed"]
