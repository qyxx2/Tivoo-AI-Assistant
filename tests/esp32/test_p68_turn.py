import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "esp32/firmware/main"


def test_local_turn_host(tmp_path):
    exe = tmp_path / "turn"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(Path(__file__).with_name("p68_turn_host.c")),
                    str(MAIN / "p68_local_turn.c"), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


def test_local_lifecycle_adapter(tmp_path):
    """Compile the real S3 turn adapter with explicit fake SDK/audio boundaries."""
    headers = {
        "esp_err.h": "#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_ERR_NO_MEM -1\n",
        "esp_log.h": "#pragma once\ntypedef int esp_log_level_t;\nvoid tivoo_test_log(const char *,const char *,...);\n#define ESP_LOGI(tag, ...) tivoo_test_log(tag,__VA_ARGS__)\n",
        "esp_heap_caps.h": "#include <stddef.h>\n#define MALLOC_CAP_SPIRAM 1\n#define MALLOC_CAP_8BIT 2\nvoid *heap_caps_calloc(size_t,size_t,unsigned);\n",
        "esp_random.h": "#include <stdint.h>\n#include <stddef.h>\nvoid esp_fill_random(void *,size_t);\nuint32_t esp_random(void);\n",
        "esp_timer.h": "#include <stdint.h>\nint64_t esp_timer_get_time(void);\n",
        "freertos/FreeRTOS.h": "typedef int portMUX_TYPE;\n#define portMUX_INITIALIZER_UNLOCKED 0\n#define portENTER_CRITICAL(lock) ((void)(lock))\n#define portEXIT_CRITICAL(lock) ((void)(lock))\n",
    }
    for name, content in headers.items():
        p = tmp_path / name
        p.parent.mkdir(exist_ok=True, parents=True)
        p.write_text(content)
    cjson = MAIN.parent / "managed_components/espressif__cjson/cJSON"
    exe = tmp_path / "lifecycle"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-DESP_PLATFORM",
                    "-I", str(tmp_path), "-I", str(MAIN), "-I", str(cjson),
                    str(Path(__file__).with_name("p68_lifecycle_host.c")),
                    str(MAIN / "s3_local_turn.c"), str(MAIN / "p68_local_turn.c"),
                    str(MAIN / "p68_prompt.c"), str(cjson / "cJSON.c"),
                    "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
    subprocess.run([str(exe), "prompt_fault"], check=True)
    subprocess.run([str(exe), "stale_fault"], check=True)

    metrics = subprocess.run([str(exe), "metrics"], check=True, text=True, capture_output=True)
    lines = [line for line in metrics.stdout.splitlines() if line.startswith("turn_metrics ")]
    assert len(lines) == 3
    records = [dict(field.split("=", 1) for field in line.split()[1:]) for line in lines]
    assert len({r["session"] for r in records}) == 3
    assert records[0]["outcome"] == "input_complete"
    assert records[0]["ready_latency_ms"] == "100"
    assert records[0]["peak_pending_samples"] == "320"
    assert records[0]["send_failures"] == "0"
    assert int(records[0]["send_attempts"]) == 5
    assert [r["outcome"] for r in records[1:]] == ["ready_timeout", "ready_timeout"]
    assert records[1]["start_sent"] == "0" and records[1]["send_failures"] == "1"
    assert records[2]["start_sent"] == "1" and records[2]["ready_latency_ms"] == "-1"
