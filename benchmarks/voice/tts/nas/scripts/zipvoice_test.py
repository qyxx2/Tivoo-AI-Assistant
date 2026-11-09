import time, resource
from pathlib import Path
import sherpa_onnx
import soundfile as sf

ROOT=Path("/data")
reference_file=ROOT/"kokoro_zf001_t1.wav"
reference_audio, reference_sr=sf.read(reference_file, dtype="float32")
if reference_audio.ndim > 1:
    reference_audio=reference_audio[:,0]
reference_text="你好，我是你的智能助手。你可以直接告诉我想做什么，我会帮你处理。今天我也可以帮你打开客厅的灯、播放音乐，或者设置一个十分钟的倒计时。"
target_text="好的，我已经准备好了。你可以随时让我查询天气、调节灯光、播放音乐，也可以直接和我聊聊今天发生的事情。"

print("sherpa_onnx", getattr(sherpa_onnx, "__version__", "unknown"), flush=True)
print("reference", len(reference_audio)/reference_sr, "sec", reference_sr, "Hz", flush=True)
t0=time.perf_counter()
cfg=sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        zipvoice=sherpa_onnx.OfflineTtsZipvoiceModelConfig(
            tokens=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/tokens.txt"),
            encoder=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/encoder.int8.onnx"),
            decoder=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/decoder.int8.onnx"),
            data_dir=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/espeak-ng-data"),
            lexicon=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/lexicon.txt"),
            vocoder=str(ROOT/"vocos_24khz.onnx"),
        ),
        num_threads=1,
        provider="cpu",
        debug=False,
    )
)
if not cfg.validate():
    raise ValueError("ZipVoice config invalid")
tts=sherpa_onnx.OfflineTts(cfg)
print(f"loaded in {time.perf_counter()-t0:.3f}s, sample_rate={tts.sample_rate}, speakers={tts.num_speakers}", flush=True)
gen=sherpa_onnx.GenerationConfig()
gen.reference_audio=reference_audio
gen.reference_sample_rate=reference_sr
gen.reference_text=reference_text
gen.num_steps=4
gen.extra["min_char_in_sentence"]="30"
t0=time.perf_counter()
audio=tts.generate(target_text, gen)
elapsed=time.perf_counter()-t0
duration=len(audio.samples)/audio.sample_rate
out=ROOT/"zipvoice_distill_4steps_t1.wav"
sf.write(str(out), audio.samples, audio.sample_rate, subtype="PCM_16")
print(f"ZipVoice Distill: sample_rate={audio.sample_rate}, duration={duration:.3f}s, synth={elapsed:.3f}s, RTF={elapsed/duration:.3f}, file={out.name}", flush=True)
print("peak RSS MB",resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
