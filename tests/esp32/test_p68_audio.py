import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "esp32/firmware/main"

def test_stereo_timeline_reference_and_output(tmp_path):
    exe = tmp_path / "audio"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(Path(__file__).with_name("p68_audio_host.c")),
                    str(MAIN / "audio_capture.c"), str(MAIN / "audio_output_manager.c"),
                    "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

def test_s3_uses_physical_audio_without_legacy_afe():
    cmake = (MAIN / "CMakeLists.txt").read_text()
    for name in ("audio_capture", "audio_output_manager", "audio_resource", "audio_playback"):
        assert f'"{name}.c"' in cmake
    assert '"audio_frontend.c"' not in cmake
    main = (MAIN / "s3_main.c").read_text()
    assert "tivoo_audio_capture_start()" in main
    assert "tivoo_audio_resource_handle_message" in main
