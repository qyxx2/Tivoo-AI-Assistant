from array import array

import pytest

from tests.integration.qwen_realtime.probe import (
    FRAME_BYTES,
    add_background_noise,
    insert_pause,
    iter_pcm_frames,
    make_silence,
    resample_pcm,
    scale_pcm,
    trim_trailing_silence,
)


def pcm(samples: list[int]) -> bytes:
    return array("h", samples).tobytes()


def samples(raw: bytes) -> list[int]:
    result = array("h")
    result.frombytes(raw)
    return list(result)


def test_frames_match_esp32_twenty_ms_640_byte_ingress_contract():
    source = pcm([1] * 1000)

    frames = list(iter_pcm_frames(source))

    assert len(frames) == 4
    assert all(len(frame) == FRAME_BYTES for frame in frames)
    assert b"".join(frames)[: len(source)] == source
    assert set(samples(b"".join(frames)[len(source) :])) == {0}


def test_pcm_frames_reject_unaligned_input():
    with pytest.raises(ValueError, match="16-bit aligned"):
        list(iter_pcm_frames(b"\x00"))


def test_silence_tail_is_exact_multiple_of_twenty_ms_frames():
    tail = make_silence(240)

    assert len(tail) == 12 * FRAME_BYTES
    assert not any(tail)


@pytest.mark.parametrize("duration_ms", [-20, 10, 30])
def test_silence_tail_rejects_non_frame_durations(duration_ms):
    with pytest.raises(ValueError, match="multiple of 20"):
        make_silence(duration_ms)


def test_scale_pcm_applies_gain_without_changing_sample_count_or_clipping():
    source = pcm([-32768, -1000, 0, 1000, 32767])

    output = scale_pcm(source, 0.25)

    assert len(output) == len(source)
    assert samples(output) == [-8192, -250, 0, 250, 8192]


def test_pause_is_inserted_at_frame_boundary_and_preserves_source_order():
    source = pcm(list(range(1600)))

    output = insert_pause(source, 500, at_fraction=0.5)

    split = 640 * 2
    assert output[:split] == source[:split]
    assert output[split : split + 500 * 16 * 2] == bytes(500 * 16 * 2)
    assert output[split + 500 * 16 * 2 :] == source[split:]


def test_noise_mix_is_deterministic_and_non_clipping():
    source = pcm([1000] * 1600)

    first = add_background_noise(source, snr_db=18, seed=7)
    second = add_background_noise(source, snr_db=18, seed=7)

    assert first == second
    values = samples(first)
    assert len(values) == 1600
    assert max(values) <= 32767
    assert min(values) >= -32768
    assert first != source


def test_trim_trailing_silence_leaves_one_vad_boundary_frame():
    source = pcm([1200] * 1600) + make_silence(240)

    trimmed = trim_trailing_silence(source, threshold_rms=180, keep_ms=20)

    assert len(trimmed) == len(pcm([1200] * 1600)) + FRAME_BYTES
    assert trimmed[: len(pcm([1200] * 1600))] == pcm([1200] * 1600)


def test_trim_trailing_silence_does_not_trim_speech_frames():
    source = pcm([1200] * 1600)

    assert trim_trailing_silence(source, threshold_rms=180, keep_ms=20) == source


def test_resample_pcm_doubles_eight_kilohertz_sample_count():
    source = pcm([0, 1000])

    output = resample_pcm(source, source_rate=8000)

    assert len(output) == 2 * len(source)
    assert samples(output) == [0, 500, 1000, 1000]
