# Tivoo AI Assistant - Matcha Baker / MeloTTS CPU benchmark

## Test environment

- Device: ARM64 Android/Linux environment exposed as aarch64
- CPU: 8 logical CPUs, Qualcomm Kryo / Cortex-A77 class
- Memory: 10 GiB total; approximately 3.4 GiB available before the test
- Python: 3.14.4
- sherpa-onnx: 2.0.1
- Runtime: native Python process on the connected device, CPU provider
- Model downloads and pip installation used the device-local proxy http://127.0.0.1:7897
- Benchmark utterance is identical for the two models; two generations per process (first and warm)
- Threads tested: 1, 2, 4

## Results

RTF is generation time divided by generated audio duration. Lower is faster; RTF below 1 means synthesis completed faster than playback duration.

### Matcha Baker

Output: 22,050 Hz, one speaker.

| Threads | First generation | First RTF | Warm generation | Warm RTF | Model load | Peak RSS |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2.986 s / 12.019 s | 0.248 | 2.985 s / 11.985 s | 0.249 | 2.120 s | 248.5 MB |
| 2 | 1.934 s / 12.003 s | 0.161 | 1.864 s / 12.010 s | 0.155 | 2.119 s | 246.8 MB |
| 4 | 1.331 s / 11.997 s | 0.111 | 1.309 s / 11.979 s | 0.109 | 2.208 s | 248.3 MB |

### MeloTTS

Output: 44,100 Hz, one speaker. The test used model.onnx (full precision). The packaged model.int8.onnx is a 133-byte Git LFS pointer for a 53,517,430-byte object; the actual quantized model payload was not included in the downloaded archive, so these MeloTTS measurements are for the full-precision model.

| Threads | First generation | First RTF | Warm generation | Warm RTF | Model load | Peak RSS |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 22.199 s / 11.233 s | 1.976 | 22.221 s / 11.047 s | 2.012 | 3.605 s | 414.2 MB |
| 2 | 13.243 s / 11.401 s | 1.162 | 13.122 s / 11.214 s | 1.170 | 3.754 s | 414.9 MB |
| 4 | 8.107 s / 11.215 s | 0.723 | 8.988 s / 11.233 s | 0.800 | 3.765 s | 414.9 MB |

## Interpretation

- Matcha Baker is substantially faster on this device. At four threads it synthesized roughly 12 seconds of speech in 1.31 seconds.
- MeloTTS has a higher output sample rate, but the 44.1 kHz number alone does not establish better perceived voice quality. It was much slower and used more memory.
- Both models expose one built-in speaker in these model packages. Neither package gives a selectable multi-speaker catalog in this test.
- The results describe this ARM64 Cortex-A77-class device only. They must not be treated as NAS performance results.
- Listening quality was not scored automatically; use the WAV samples in results/ for subjective A/B listening.

## Re-run

Install dependencies into a virtual environment, then run:

    python3 -m venv .venv
    . .venv/bin/activate
    export HTTP_PROXY=http://127.0.0.1:7897
    export HTTPS_PROXY=http://127.0.0.1:7897
    export ALL_PROXY=http://127.0.0.1:7897
    pip install -r requirements.txt
    PYTHON=.venv/bin/python scripts/run-all.sh

The test script and all assets used by the test are retained in this directory.
