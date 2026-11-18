import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "esp32/firmware/main"


def test_local_afe_flow(tmp_path):
    exe = tmp_path / "afe"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(Path(__file__).with_name("p68_afe_host.c")),
                    str(MAIN / "p68_afe_flow.c"), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


def test_s3_runs_real_afe_not_legacy_or_smoke():
    cmake = (MAIN / "CMakeLists.txt").read_text()
    main = (MAIN / "s3_main.c").read_text()
    afe = (MAIN / "s3_afe.c").read_text()
    assert '"s3_afe.c"' in cmake and '"p68_afe_flow.c"' in cmake
    assert '"audio_frontend.c"' not in cmake
    assert "tivoo_s3_afe_start(" in main
    assert main.index("tivoo_s3_afe_start(") < main.index("tivoo_audio_capture_monitor_start()")
    for token in ('"MMNR"', 'AFE_TYPE_FD', 'AFE_MODE_HIGH_PERF',
                  'get_feed_chunksize', 'get_fetch_chunksize',
                  'fetch_with_delay', 'print_pipeline', 'afe_config_check'):
        assert token in afe
