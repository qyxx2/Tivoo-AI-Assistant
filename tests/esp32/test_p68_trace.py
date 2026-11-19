import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "esp32/firmware/main"


def test_trace_copies_bounded_indexed_records(tmp_path):
    exe = tmp_path / "trace"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(Path(__file__).with_name("p68_trace_host.c")),
                    str(MAIN / "p68_trace.c"), "-o", str(exe)], check=True)
    blob = subprocess.check_output([str(exe)])
    spec = importlib.util.spec_from_file_location("trace_reader", ROOT / "scripts/read-p68-trace.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    raw, fetched, gap = list(reader.records(blob))
    assert raw["index"] == 4160 and raw["aux"] == 4082 and raw["epoch"] == 0
    assert raw["left"] == tuple(i << 16 for i in range(1, 161))
    assert raw["right"] == tuple((-i << 16) for i in range(1, 161))
    assert raw["tx"] == tuple(range(1000, 1160))
    assert fetched["index"] == 2080 and fetched["aux"] == 2117
    assert fetched["pcm"] == tuple(range(2000, 2160))
    assert fetched["cache"] == tuple(range(-1000, -1032, -1))
    assert gap["flags"] == 1 and gap["index"] == 4320
    # Serial chunks must be complete and in order; no silent truncation.
    capture = ["P68TRACE BEGIN raw 0 " + str(len(blob))]
    for i in range(0, len(blob), 128):
        capture.append(f"P68TRACE DATA raw {i} {blob[i:i+128].hex()}")
    capture.append("P68TRACE END raw")
    assert reader.read_serial(capture)["raw"][0] == blob
    import pytest
    with pytest.raises(ValueError):
        reader.read_serial(capture[:2] + capture[3:])


def test_enabled_trace_task_exports_once_and_stops(tmp_path):
    headers = {
        "sdkconfig.h": "#define CONFIG_TIVOO_P68_CALIBRATION_TRACE 1\n#define CONFIG_TIVOO_P68_TRACE_DELAY_SECONDS 15\n",
        "esp_heap_caps.h": "#include <stdlib.h>\n#define MALLOC_CAP_SPIRAM 1\n#define MALLOC_CAP_8BIT 2\n#define heap_caps_malloc(n,c) malloc(n)\n",
        "esp_timer.h": "#include <stdint.h>\nint64_t esp_timer_get_time(void);\n",
        "freertos/FreeRTOS.h": "#include <stdint.h>\n#define portMAX_DELAY UINT32_MAX\n#define pdMS_TO_TICKS(n) (n)\n#define pdPASS 1\n",
        "freertos/semphr.h": """#include <assert.h>
typedef int *SemaphoreHandle_t;
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void) {static int l;return &l;}
static inline void xSemaphoreTake(SemaphoreHandle_t l,unsigned t) {(void)t;assert(!*l);*l=1;}
static inline void xSemaphoreGive(SemaphoreHandle_t l) {assert(*l);*l=0;}
static inline void vSemaphoreDelete(SemaphoreHandle_t l) {(void)l;}
""",
        "freertos/task.h": """void vTaskDelay(unsigned);
void vTaskDelete(void *);
int xTaskCreatePinnedToCore(void (*)(void *),const char *,unsigned,void *,unsigned,void *,int);
""",
    }
    for name, content in headers.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    exe = tmp_path / "runtime"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-DESP_PLATFORM", "-I", str(tmp_path), "-I", str(MAIN),
                    str(Path(__file__).with_name("p68_trace_runtime_host.c")),
                    str(MAIN / "p68_trace.c"), "-o", str(exe)], check=True)
    serial = subprocess.check_output([str(exe)], text=True)
    spec = importlib.util.spec_from_file_location("trace_reader", ROOT / "scripts/read-p68-trace.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    streams = reader.read_serial(serial.splitlines())
    raw, dropped = streams["raw"]
    assert len(raw) == (1400000 // 1640) * 1640
    assert dropped == 901 - 1400000 // 1640
    first, *rest = reader.records(raw)
    assert first["index"] == 3200 and first["tx"] == tuple(range(1, 161))
    assert first["left"][0] == 65536 and first["right"][0] == 131072
    assert all(rec["index"] == 3200 + 160 * i for i, rec in enumerate(rest, 1))
    afe, dropped = streams["afe"]
    assert not dropped
    rec, = reader.records(afe)
    assert rec["index"] == 1600 and rec["aux"] == 1637
    assert rec["pcm"] == tuple(range(500, 660)) and rec["cache"][0] == -321
    # Keep the actual serial protocol output as a reproducible host test artifact.
    (tmp_path / "trace-serial.log").write_text(serial)
