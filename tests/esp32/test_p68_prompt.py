import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "esp32/firmware/main"


def test_prompt_assets(tmp_path):
    subprocess.run(["python3", str(MAIN / "generate_prompts.py"),
                    str(ROOT / "homeassistant/prompt_assets"), str(tmp_path)], check=True)
    first = {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
             for p in tmp_path.glob("*.pcm")}
    assert {key: value[0] for key, value in first.items()} == {
        "ready_01.pcm": 47402, "ready_02.pcm": 47784,
        "ready_03.pcm": 53254, "followup_01.pcm": 30720}
    subprocess.run(["python3", str(MAIN / "generate_prompts.py"),
                    str(ROOT / "homeassistant/prompt_assets"), str(tmp_path)], check=True)
    assert first == {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
                     for p in tmp_path.glob("*.pcm")}
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["python3", str(MAIN / "generate_prompts.py"), str(empty), str(tmp_path)], check=True)
    assert all(p.stat().st_size == 0 for p in tmp_path.glob("*.pcm"))


def test_prompt_host(tmp_path):
    exe = tmp_path / "prompt"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(Path(__file__).with_name("p68_prompt_host.c")),
                    str(MAIN / "p68_prompt.c"), str(MAIN / "audio_output_manager.c"),
                    str(MAIN / "p68_afe_flow.c"), str(MAIN / "p68_local_turn.c"),
                    "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
