import time, resource
from pathlib import Path
import sherpa_onnx
import soundfile as sf

ROOT = Path("/data")
TEXT = "你好，我是你的智能助手。你可以直接告诉我想做什么，我会帮你处理。今天我也可以帮你打开客厅的灯、播放音乐，或者设置一个十分钟的倒计时。"

def report(name, tts, sid, out):
    start = time.perf_counter()
    audio = tts.generate(TEXT, sid=sid, speed=1.0)
    elapsed = time.perf_counter() - start
    duration = len(audio.samples) / audio.sample_rate
    sf.write(str(ROOT / out), audio.samples, audio.sample_rate, subtype="PCM_16")
    print(f"{name}: sid={sid}, sr={audio.sample_rate}, duration={duration:.3f}s, synth={elapsed:.3f}s, RTF={elapsed/duration:.3f}, file={out}", flush=True)

print("sherpa_onnx", getattr(sherpa_onnx, "__version__", "unknown"), flush=True)
print("KOKORO: loading", flush=True)
t0=time.perf_counter()
kc = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(ROOT/"kokoro-int8-multi-lang-v1_1/model.int8.onnx"),
            voices=str(ROOT/"kokoro-int8-multi-lang-v1_1/voices.bin"),
            tokens=str(ROOT/"kokoro-int8-multi-lang-v1_1/tokens.txt"),
            data_dir=str(ROOT/"kokoro-int8-multi-lang-v1_1/espeak-ng-data"),
            lexicon=str(ROOT/"kokoro-int8-multi-lang-v1_1/lexicon-zh.txt"),
        ),
        num_threads=1,
        provider="cpu",
    ),
    rule_fsts=",".join(str(ROOT/"kokoro-int8-multi-lang-v1_1"/x) for x in ["phone-zh.fst","date-zh.fst","number-zh.fst"]),
)
if not kc.validate(): raise RuntimeError("Kokoro config invalid")
kt=sherpa_onnx.OfflineTts(kc)
print(f"KOKORO loaded in {time.perf_counter()-t0:.3f}s; sample_rate={kt.sample_rate}; speakers={kt.num_speakers}", flush=True)
report("Kokoro female zf_001", kt, 3, "kokoro_zf001_t1.wav")
report("Kokoro male zm_009", kt, 58, "kokoro_zm009_t1.wav")
print("KOKORO peak RSS MB", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024, flush=True)

print("MATCHA: loading", flush=True)
t0=time.perf_counter()
mc = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
            acoustic_model=str(ROOT/"matcha-icefall-zh-baker/model-steps-3.onnx"),
            vocoder=str(ROOT/"vocos-22khz-univ.onnx"),
            tokens=str(ROOT/"matcha-icefall-zh-baker/tokens.txt"),
            lexicon=str(ROOT/"matcha-icefall-zh-baker/lexicon.txt"),
        ),
        num_threads=1,
        provider="cpu",
    ),
    max_num_sentences=1,
    rule_fsts=",".join(str(ROOT/"matcha-icefall-zh-baker"/x) for x in ["phone.fst","date.fst","number.fst"]),
)
if not mc.validate(): raise RuntimeError("Matcha config invalid")
mt=sherpa_onnx.OfflineTts(mc)
print(f"MATCHA loaded in {time.perf_counter()-t0:.3f}s; sample_rate={mt.sample_rate}; speakers={mt.num_speakers}", flush=True)
report("Matcha Baker", mt, 0, "matcha_baker_t1.wav")
print("FINAL peak RSS MB", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024, flush=True)
