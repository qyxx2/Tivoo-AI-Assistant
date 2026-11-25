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
    for token in ('"MMNR"', 'AFE_TYPE_SR', 'AFE_MODE_HIGH_PERF',
                  'get_feed_chunksize', 'get_fetch_chunksize',
                  'fetch_with_delay', 'print_pipeline', 'afe_config_check'):
        assert token in afe
    assert (
        "input=heap_caps_malloc(feed_size*4*sizeof(int16_t),"
        "MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);"
    ) in afe


def test_realtime_tasks_are_split_away_from_wifi_contention():
    afe = (MAIN / "s3_afe.c").read_text()
    resource = (MAIN / "audio_resource.c").read_text()
    defaults = (MAIN.parent / "sdkconfig.defaults").read_text()
    assert 'capture_task,"afe_capture",4096,NULL,9,&capture_handle,0' in afe
    assert 'feed_task,"afe_feed",4096,NULL,7,&feed_handle,1' in afe
    assert 'fetch_task,"afe_fetch",4096,NULL,8,&fetch_handle,0' in afe
    assert '&rx, tskIDLE_PRIORITY + 6, NULL, 1' in resource
    assert 'request, tskIDLE_PRIORITY + 6, NULL, 0' in resource
    assert "CONFIG_LWIP_TCP_WND_DEFAULT=14360" in defaults
    assert "CONFIG_LWIP_TCP_RECVMBOX_SIZE=12" in defaults


def afe_headers():
    return {
        "esp_err.h": """#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_INVALID_STATE -1
#define ESP_ERR_NO_MEM -2
#define ESP_ERR_TIMEOUT -3
static inline const char *esp_err_to_name(int v) {(void)v;return "stub";}
""",
        "esp_partition.h": "typedef struct esp_partition_t esp_partition_t;\n",
        "esp_system.h": "#pragma once\n",
        "sdkconfig.h": "#pragma once\n",
        "esp_log.h": """#pragma once
#include <stdio.h>
typedef enum {ESP_LOG_NONE,ESP_LOG_ERROR,ESP_LOG_WARN,ESP_LOG_INFO,ESP_LOG_DEBUG,ESP_LOG_VERBOSE} esp_log_level_t;
#define ESP_LOGI(tag,...) do { (void)(tag); if(0) printf(__VA_ARGS__); } while(0)
#define ESP_LOGW ESP_LOGI
#define ESP_LOGE ESP_LOGI
""",
        "esp_heap_caps.h": """#include <stddef.h>
#include <stdlib.h>
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_DMA 2
#define MALLOC_CAP_SPIRAM 4
#define MALLOC_CAP_8BIT 8
#define heap_caps_malloc(n,c) malloc(n)
size_t heap_caps_get_minimum_free_size(unsigned);
size_t heap_caps_get_largest_free_block(unsigned);
size_t heap_caps_get_free_size(unsigned);
""",
        "esp_timer.h": "#include <stdint.h>\nint64_t esp_timer_get_time(void);\n",
        "freertos/FreeRTOS.h": """#pragma once
#include <stdint.h>
typedef unsigned TickType_t;
typedef void *TaskHandle_t;
typedef int BaseType_t;
#define pdTRUE 1
#define pdPASS 1
#define portMAX_DELAY UINT32_MAX
#define pdMS_TO_TICKS(n) (n)
""",
        "freertos/task.h": """#pragma once
#include "freertos/FreeRTOS.h"
void vTaskDelay(TickType_t);
void vTaskDelete(TaskHandle_t);
unsigned uxTaskGetStackHighWaterMark(void *);
static inline unsigned ulTaskNotifyTake(int a,TickType_t b) {(void)a;(void)b;return 0;}
static inline int xTaskCreatePinnedToCore(void (*f)(void *),const char *n,unsigned s,void *a,unsigned p,TaskHandle_t *h,int c) {(void)f;(void)n;(void)s;(void)a;(void)p;(void)h;(void)c;return pdPASS;}
static inline void xTaskNotifyGive(TaskHandle_t t) {(void)t;}
""",
        "freertos/queue.h": """#pragma once
#include "freertos/task.h"
#include <stdlib.h>
#include <stddef.h>
typedef void *QueueHandle_t;
static inline QueueHandle_t xQueueCreate(size_t n,size_t s) {return calloc(n,s);}
static inline int xQueueSend(QueueHandle_t q,const void *p,TickType_t t) {(void)q;(void)p;(void)t;return pdTRUE;}
static inline int xQueueReceive(QueueHandle_t q,void *p,TickType_t t) {(void)q;(void)p;(void)t;return 0;}
static inline void xQueueReset(QueueHandle_t q) {(void)q;}
#define vQueueDelete free
""",
    }


def test_afe_runtime_availability(tmp_path):
    """Actual vendor call sites, capture failures and recovery; RTOS is scripted."""
    headers = afe_headers()
    headers["freertos/queue.h"] = """#pragma once
#include "freertos/task.h"
#include <stdlib.h>
#include <stddef.h>
typedef struct { unsigned char *data; size_t n,size,head,count; } TestQueue;
typedef TestQueue *QueueHandle_t;
typedef TestQueue StaticQueue_t;
QueueHandle_t xQueueCreate(size_t,size_t);
QueueHandle_t xQueueCreateStatic(size_t,size_t,unsigned char *,StaticQueue_t *);
int xQueueSend(QueueHandle_t,const void *,TickType_t);
int xQueueReceive(QueueHandle_t,void *,TickType_t);
void xQueueReset(QueueHandle_t);
void vQueueDelete(QueueHandle_t);
"""
    for name, content in headers.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    sr = MAIN.parent / "managed_components/espressif__esp-sr"
    exe = tmp_path / "afe_runtime"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                    "-DESP_PLATFORM", "-DCONFIG_TIVOO_P68_CALIBRATION_TRACE=1", '-DTIVOO_AFE_MODEL_ID="wn9_hiwalle_tts2"',
                    "-I", str(tmp_path), "-I", str(MAIN),
                    "-I", str(sr / "include/esp32s3"), "-I", str(sr / "src/include"),
                    "-I", str(MAIN.parent / "managed_components/espressif__cjson/cJSON"),
                    str(Path(__file__).with_name("p68_afe_runtime_host.c")),
                    str(MAIN / "p68_afe_flow.c"), "-lm", "-o", str(exe)], check=True)
    results = {case: subprocess.run([str(exe), case], check=False, capture_output=True, text=True)
               for case in ("recover", "buffer_fail", "vad_fail", "gate", "gate_cross", "capture_stall", "sr_config")}
    assert all(r.returncode == 0 for r in results.values()), {
        case: r.stderr for case, r in results.items() if r.returncode
    }
