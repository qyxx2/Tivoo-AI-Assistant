#include "audio_capture.h"

#include <limits.h>

/* 32 kHz low-pass, 6.72 kHz cutoff, Blackman-windowed sinc in Q15.
 * Coefficients sum to 32768 so that DC gain is unity. */
static const int16_t lowpass[TIVOO_DECIMATOR_TAPS] = {
    0, -1, -13, -4, 68, 80, -148, -341, 110, 884, 406, -1643, -2152,
    2337, 9922, 13758, 9922, 2337, -2152, -1643, 406, 884, 110, -341,
    -148, 80, 68, -4, -13, -1, 0,
};

int32_t tivoo_inmp441_sample(uint32_t left_slot)
{
    const int32_t sample = (int32_t)(left_slot >> 8);
    return sample >= 0x800000 ? sample - 0x1000000 : sample;
}

size_t tivoo_audio_decimate(
    tivoo_decimator_t *filter, const uint32_t *stereo, size_t frames, int16_t *mono)
{
    size_t produced = 0;
    for (size_t i = 0; i < frames; ++i) {
        filter->history[filter->next] = tivoo_inmp441_sample(stereo[2 * i]);
        if (++filter->next == TIVOO_DECIMATOR_TAPS) {
            filter->next = 0;
        }
        filter->phase ^= 1U;
        if (filter->phase) {
            continue;
        }

        int64_t sum = 0;
        size_t slot = filter->next;
        for (size_t tap = 0; tap < TIVOO_DECIMATOR_TAPS; ++tap) {
            sum += (int64_t)filter->history[slot] * lowpass[tap];
            if (++slot == TIVOO_DECIMATOR_TAPS) {
                slot = 0;
            }
        }
        /* Q15 gain and 24 -> 16 bits, rounded to nearest, then saturated. */
        const int32_t pcm = (int32_t)((sum + (sum < 0 ? -4194304 : 4194304)) / 8388608);
        mono[produced++] = pcm > INT16_MAX ? INT16_MAX : pcm < INT16_MIN ? INT16_MIN : pcm;
    }
    return produced;
}

#ifdef ESP_PLATFORM
#include <stdatomic.h>

#include "driver/i2s_std.h"
#include "esp_attr.h"
#include "sdkconfig.h"

static i2s_chan_handle_t s_rx;
static i2s_chan_handle_t s_tx;
static bool s_tx_enabled;
static bool s_rx_enabled;
static atomic_uint s_rx_overruns;

static bool IRAM_ATTR rx_overrun(i2s_chan_handle_t handle, i2s_event_data_t *event, void *context)
{
    (void)handle;
    (void)event;
    (void)context;
    atomic_fetch_add_explicit(&s_rx_overruns, 1, memory_order_relaxed);
    return false;
}

void tivoo_audio_capture_close(void)
{
    if (s_rx != NULL) {
        if (s_rx_enabled) {
            i2s_channel_disable(s_rx);
        }
        i2s_del_channel(s_rx);
        s_rx = NULL;
        s_rx_enabled = false;
    }
    if (s_tx != NULL) {
        if (s_tx_enabled) {
            i2s_channel_disable(s_tx);
        }
        i2s_del_channel(s_tx);
        s_tx = NULL;
        s_tx_enabled = false;
    }
}

esp_err_t tivoo_audio_capture_start(void)
{
    i2s_chan_config_t channels = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channels.dma_desc_num = 12;
    channels.dma_frame_num = 160;
    channels.auto_clear_after_cb = true;
    const i2s_std_config_t format = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(32000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = CONFIG_TIVOO_I2S_BCLK_GPIO,
            .ws = CONFIG_TIVOO_I2S_WS_GPIO,
            .dout = CONFIG_TIVOO_I2S_DOUT_GPIO,
            .din = CONFIG_TIVOO_I2S_DIN_GPIO,
        },
    };
    const i2s_event_callbacks_t callbacks = {.on_recv_q_ovf = rx_overrun};

    esp_err_t err = i2s_new_channel(&channels, &s_tx, &s_rx);
    if (err == ESP_OK) {
        err = i2s_channel_init_std_mode(s_tx, &format);
    }
    if (err == ESP_OK) {
        err = i2s_channel_init_std_mode(s_rx, &format);
    }
    if (err == ESP_OK) {
        err = i2s_channel_register_event_callback(s_rx, &callbacks, NULL);
    }
    if (err == ESP_OK) {
        err = i2s_channel_enable(s_tx);
        s_tx_enabled = err == ESP_OK;
    }
    if (err == ESP_OK) {
        err = i2s_channel_enable(s_rx);
        s_rx_enabled = err == ESP_OK;
    }
    if (err != ESP_OK) {
        tivoo_audio_capture_close();
    }
    return err;
}

esp_err_t tivoo_audio_capture_read(uint32_t *stereo, size_t bytes, size_t *read)
{
    return i2s_channel_read(s_rx, stereo, bytes, read, 100);
}

uint32_t tivoo_audio_capture_overruns(void)
{
    return atomic_load_explicit(&s_rx_overruns, memory_order_relaxed);
}
#endif
