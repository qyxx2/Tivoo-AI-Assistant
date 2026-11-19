import hashlib
import shutil
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


def test_prompt_source_tamper_rejected(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "homeassistant/prompt_assets", source)
    output = tmp_path / "out"
    command = ["python3", str(MAIN / "generate_prompts.py"), str(source), str(output)]
    subprocess.run(command, check=True)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    asset = source / "ready_01.mp3"
    asset.write_bytes(asset.read_bytes() + b"x")
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert "source differs from the frozen contract" in result.stderr
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    # CMake must abort configuration rather than consuming the prior output.
    assert '"${_prompt_src}" "${_prompt_out}" COMMAND_ERROR_IS_FATAL ANY)' in (MAIN / "CMakeLists.txt").read_text()


def test_prompt_real_adapter_dma_and_owner(tmp_path):
    """Actual S3 turn/AFE gates/resource owner/output ISR, fake electrical/vendor boundaries."""
    from test_p68_audio import dma_headers
    from test_p68_afe import afe_headers
    import struct

    dma, afe = dma_headers(), afe_headers()
    headers = {**dma, **afe}
    headers["esp_err.h"] = dma["esp_err.h"] + """
#define ESP_ERR_HTTP_EAGAIN 99
static inline const char *esp_err_to_name(int v) {(void)v;return "stub";}
"""
    headers["esp_heap_caps.h"] = afe["esp_heap_caps.h"] + """
#define heap_caps_calloc(n,s,c) calloc(n,s)
"""
    headers["freertos/FreeRTOS.h"] = dma["freertos/FreeRTOS.h"] + """
typedef unsigned TickType_t;
typedef void *TaskHandle_t;
#define portMAX_DELAY UINT32_MAX
#define tskIDLE_PRIORITY 0
"""
    headers["freertos/task.h"] = dma["freertos/task.h"] + """
static inline unsigned ulTaskNotifyTake(int a,TickType_t b) {(void)a;(void)b;return 0;}
static inline void xTaskNotifyGive(TaskHandle_t t) {(void)t;}
"""
    headers["freertos/queue.h"] = dma["freertos/queue.h"] + """
#include <stdlib.h>
static inline QueueHandle_t xQueueCreate(size_t n,size_t s) {(void)n;(void)s;return NULL;}
static inline int xQueueSend(QueueHandle_t q,const void *p,TickType_t t) {(void)q;(void)p;(void)t;return pdTRUE;}
#define vQueueDelete free
"""
    headers["freertos/semphr.h"] = """#pragma once
#include "freertos/FreeRTOS.h"
#include <assert.h>
typedef int *SemaphoreHandle_t;
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void) {static int lock;return &lock;}
static inline int xSemaphoreTake(SemaphoreHandle_t s,unsigned t) {(void)t;assert(!*s);*s=1;return pdTRUE;}
static inline void xSemaphoreGive(SemaphoreHandle_t s) {assert(*s);*s=0;}
"""
    headers["sdkconfig.h"] = dma["sdkconfig.h"]
    headers["esp_random.h"] = """
#include <stddef.h>
#include <stdint.h>
void esp_fill_random(void *,size_t);
uint32_t esp_random(void);
"""
    headers["lwip/sockets.h"] = "#include <sys/socket.h>\n"
    headers["esp_crt_bundle.h"] = "int esp_crt_bundle_attach(void *);\n"
    headers["esp_http_client.h"] = """#pragma once
#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>
typedef void *esp_http_client_handle_t;
typedef struct {void *user_data;int event_id;char *header_key,*header_value;} esp_http_client_event_t;
typedef struct {const char *url;int method,timeout_ms,buffer_size,buffer_size_tx;
    esp_err_t (*event_handler)(esp_http_client_event_t *);void *user_data;
    bool disable_auto_redirect;int (*crt_bundle_attach)(void *);} esp_http_client_config_t;
#define HTTP_EVENT_ON_HEADER 1
#define HTTP_METHOD_GET 1
int esp_http_client_open(esp_http_client_handle_t,int);
int esp_http_client_get_socket(esp_http_client_handle_t);
int esp_http_client_set_timeout_ms(esp_http_client_handle_t,int);
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t);
bool esp_http_client_is_chunked_response(esp_http_client_handle_t);
int esp_http_client_get_status_code(esp_http_client_handle_t);
int esp_http_client_read(esp_http_client_handle_t,char *,int);
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t);
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *);
int esp_http_client_cleanup(esp_http_client_handle_t);
"""
    for name, content in headers.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    # Nonzero signed marker samples, at exactly all four frozen asset lengths.
    asm = ['.section .rodata']
    for name, n in zip(("ready_01", "ready_02", "ready_03", "followup_01"),
                       (23701, 23892, 26627, 15360)):
        path = tmp_path / (name + ".pcm")
        path.write_bytes(struct.pack(f"<{n}h", *(i+1 if i % 2 == 0 else -(i+1) for i in range(n))))
        asm += [".balign 4", f".global {name}_start,{name}_end", f"{name}_start:",
                f'.incbin "{path}"', f"{name}_end:"]
    asm.append('.section .note.GNU-stack,"",%progbits')
    assets = tmp_path / "assets.S"
    assets.write_text("\n".join(asm) + "\n")
    sr = MAIN.parent / "managed_components/espressif__esp-sr"
    cjson = MAIN.parent / "managed_components/espressif__cjson/cJSON"
    exe = tmp_path / "adapter"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable", "-Wno-sign-compare",
                    "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                    "-DESP_PLATFORM", "-DTIVOO_P68_B5_LOCAL", "-DTIVOO_P68_B3_AUDIO",
                    '-DTIVOO_AFE_MODEL_ID="wn9_hilexin"',
                    "-I", str(tmp_path), "-I", str(MAIN),
                    "-I", str(sr / "include/esp32s3"), "-I", str(sr / "src/include"),
                    "-I", str(cjson), str(Path(__file__).with_name("p68_prompt_adapter_host.c")),
                    str(assets), *(str(MAIN / name) for name in (
                        "audio_capture.c", "audio_output_manager.c", "audio_resource.c",
                        "p68_afe_flow.c", "p68_prompt.c", "p68_local_turn.c", "s3_local_turn.c")),
                    str(cjson / "cJSON.c"), "-lm", "-o", str(exe)], check=True)
    results = {case: subprocess.run([str(exe), case], capture_output=True, text=True)
               for case in ("ready1", "ready2", "ready3", "followup", "negative",
                            "late", "fault", "timeout", "stop", "epoch")}
    assert all(r.returncode == 0 for r in results.values()), {
        case: r.stderr for case, r in results.items() if r.returncode
    }
