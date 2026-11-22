"""Run production playback/queue; only proprietary DSP/decoder and ESP APIs are doubles.

Catches absent raw SRC, per-chunk resets, dropped EOF remainder, wrong sizing,
32 kHz corruption and writes from a retired generation. DSP quality needs hardware.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'esp32/firmware/main'


@pytest.fixture(scope='module')
def pcm_host(tmp_path_factory):
    p = tmp_path_factory.mktemp('pcm-src')
    headers = {
        'esp_err.h': '''#pragma once
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 1
#define ESP_ERR_INVALID_SIZE 2
#define ESP_ERR_INVALID_STATE 3
#define ESP_ERR_INVALID_ARG 4
typedef int esp_err_t;
''',
        'esp_heap_caps.h': '''#include <stdlib.h>
#define MALLOC_CAP_SPIRAM 0
#define MALLOC_CAP_8BIT 0
#define heap_caps_calloc(n,s,c) calloc(n,s)
#define heap_caps_malloc(n,c) malloc(n)
''',
        'esp_log.h': '#define ESP_LOGI(...) ((void)0)\n#define ESP_LOGW(...) ((void)0)\n',
        'esp_timer.h': '#include <stdint.h>\nstatic inline int64_t esp_timer_get_time(void) {return 0;}\n',
        'esp_audio_simple_dec.h': '''#pragma once
#include <stdint.h>
#define ESP_AUDIO_ERR_OK 0
#define ESP_AUDIO_SIMPLE_DEC_TYPE_MP3 1
typedef int esp_audio_err_t;
typedef void *esp_audio_simple_dec_handle_t;
typedef struct {int dec_type;} esp_audio_simple_dec_cfg_t;
typedef struct {uint8_t *buffer; unsigned len,consumed; int eos;} esp_audio_simple_dec_raw_t;
typedef struct {uint8_t *buffer; unsigned len,decoded_size;} esp_audio_simple_dec_out_t;
typedef struct {unsigned bits_per_sample,channel,sample_rate;} esp_audio_simple_dec_info_t;
int esp_audio_simple_dec_open(void *,void **);
int esp_audio_simple_dec_get_info(void *,esp_audio_simple_dec_info_t *);
int esp_audio_simple_dec_process(void *,esp_audio_simple_dec_raw_t *,esp_audio_simple_dec_out_t *);
void esp_audio_simple_dec_close(void *);
''',
        'esp_mp3_dec.h': 'static inline int esp_mp3_dec_register(void) {return 0;}\n',
        'boundary.h': '''#include "esp_err.h"
#include <stdint.h>
#include <stddef.h>
esp_err_t tivoo_audio_output_write(uint32_t,const int16_t *,size_t);
''',
    }
    for name, content in headers.items():
        (p / name).write_text(content)
    exe = p / 'pcm-host'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I', str(p), '-I', str(MAIN), '-I', str(MAIN.parent / 'managed_components/espressif__esp_audio_effects/include'),
                    '-include', str(p / 'boundary.h'),
                    str(Path(__file__).with_name('p68_pcm_src_host.c')),
                    str(MAIN / 'audio_playback.c'), str(MAIN / 'audio_output_manager.c'),
                    '-lm', '-o', str(exe)], check=True)
    return exe


@pytest.mark.parametrize('case', ['passthrough', 'silence', 'constant', 'impulse', 'sweep', 'tail', 'unaligned', 'unsupported', 'cancel', 'src_error'])
def test_raw_pcm_src(pcm_host, case):
    subprocess.run([str(pcm_host), case], check=True)
