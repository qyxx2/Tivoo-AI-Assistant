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


def dma_headers():
    return {
        "esp_err.h": """#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_INVALID_STATE -1
#define ESP_ERR_INVALID_ARG -2
#define ESP_ERR_NO_MEM -3
#define ESP_ERR_TIMEOUT -4
""",
        "esp_attr.h": "#define IRAM_ATTR\n",
        "esp_log.h": "#include <stdio.h>\n#define ESP_LOGI(tag,...) do { (void)(tag); if(0) printf(__VA_ARGS__); } while(0)\n#define ESP_LOGW ESP_LOGI\n#define ESP_LOGE ESP_LOGI\n",
        "esp_heap_caps.h": "#include <stddef.h>\n#define MALLOC_CAP_INTERNAL 1\n#define MALLOC_CAP_DMA 2\nsize_t heap_caps_get_minimum_free_size(unsigned);\nsize_t heap_caps_get_free_size(unsigned);\n",
        "esp_timer.h": "#include <stdint.h>\nint64_t esp_timer_get_time(void);\n",
        "sdkconfig.h": "#define CONFIG_TIVOO_I2S_BCLK_GPIO 4\n#define CONFIG_TIVOO_I2S_WS_GPIO 5\n#define CONFIG_TIVOO_I2S_DOUT_GPIO 6\n#define CONFIG_TIVOO_I2S_DIN_GPIO 7\n#define CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES 0\n",
        "freertos/FreeRTOS.h": """#pragma once
#include <stddef.h>
#include <stdint.h>
typedef int BaseType_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(l) ((void)(l))
#define portEXIT_CRITICAL(l) ((void)(l))
#define portENTER_CRITICAL_ISR portENTER_CRITICAL
#define portEXIT_CRITICAL_ISR portEXIT_CRITICAL
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
""",
        "freertos/queue.h": """#pragma once
#include "freertos/FreeRTOS.h"
typedef struct {uint8_t *buf;size_t n,size,head,count;} StaticQueue_t;
typedef StaticQueue_t *QueueHandle_t;
QueueHandle_t xQueueCreateStatic(size_t,size_t,uint8_t *,StaticQueue_t *);
BaseType_t xQueueSendFromISR(QueueHandle_t,const void *,BaseType_t *);
BaseType_t xQueueReceive(QueueHandle_t,void *,unsigned);
unsigned uxQueueMessagesWaiting(QueueHandle_t);
BaseType_t xQueueReset(QueueHandle_t);
""",
        "freertos/task.h": """#pragma once
#include "freertos/FreeRTOS.h"
void vTaskDelay(unsigned);
int xPortGetCoreID(void);
void vTaskDelete(void *);
unsigned uxTaskGetStackHighWaterMark(void *);
BaseType_t xTaskCreatePinnedToCore(void (*)(void *),const char *,unsigned,void *,unsigned,void *,int);
""",
        "driver/i2s_std.h": """#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef struct channel *i2s_chan_handle_t;
typedef struct {void *dma_buf;size_t size;} i2s_event_data_t;
typedef bool (*cb_t)(i2s_chan_handle_t,i2s_event_data_t *,void *);
typedef struct {cb_t on_recv,on_sent;} i2s_event_callbacks_t;
typedef struct {unsigned dma_desc_num,dma_frame_num;bool auto_clear_before_cb,auto_clear_after_cb;} i2s_chan_config_t;
typedef struct {int clk_cfg,slot_cfg;struct {int mclk,bclk,ws,dout,din;} gpio_cfg;} i2s_std_config_t;
#define I2S_CHANNEL_DEFAULT_CONFIG(a,b) ((i2s_chan_config_t){0})
#define I2S_STD_CLK_DEFAULT_CONFIG(a) (a)
#define I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(a,b) 0
#define I2S_GPIO_UNUSED -1
esp_err_t i2s_new_channel(const i2s_chan_config_t *,i2s_chan_handle_t *,i2s_chan_handle_t *);
esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t,const i2s_std_config_t *);
esp_err_t i2s_channel_register_event_callback(i2s_chan_handle_t,const i2s_event_callbacks_t *,void *);
esp_err_t i2s_channel_enable(i2s_chan_handle_t);
esp_err_t i2s_channel_disable(i2s_chan_handle_t);
esp_err_t i2s_del_channel(i2s_chan_handle_t);
esp_err_t i2s_channel_read(i2s_chan_handle_t,void *,size_t,size_t *,unsigned);
""",
    }


def test_dma_runtime_recovery(tmp_path):
    """Run the real ISR/capture/queue functions; only I2S/RTOS boundary is fake."""
    headers = dma_headers()
    for name, content in headers.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    exe = tmp_path / "dma"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-Wno-unused-variable", "-DESP_PLATFORM", "-I", str(tmp_path), "-I", str(MAIN),
                    str(Path(__file__).with_name("p68_dma_host.c")), str(MAIN / "audio_capture.c"),
                    str(MAIN / "audio_output_manager.c"), "-o", str(exe)], check=True)
    results = {case: subprocess.run([str(exe), case], capture_output=True, text=True)
               for case in ("startup", "tx", "failure", "normal", "early_release", "repeat", "stalled_tx")}
    assert all(r.returncode == 0 for r in results.values()), {
        case: r.stderr for case, r in results.items() if r.returncode
    }
