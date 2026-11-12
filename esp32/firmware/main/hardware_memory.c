#include "hardware_memory.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>

#include "diagnostics.h"
#include "esp_err.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_psram.h"
#include "esp32/himem.h"

static const char *TAG = "tivoo_memory";

static esp_err_t probe_himem(
    size_t *allocated_bytes,
    size_t *tested_bytes,
    size_t *tested_blocks)
{
    const size_t physical_bytes = esp_himem_get_phys_size();
    const size_t allocation_bytes =
        physical_bytes - physical_bytes % ESP_HIMEM_BLKSZ;
    if (allocation_bytes < ESP_HIMEM_BLKSZ) {
        return ESP_ERR_NO_MEM;
    }

    esp_himem_handle_t memory = NULL;
    esp_himem_rangehandle_t range = NULL;
    esp_err_t result = esp_himem_alloc(allocation_bytes, &memory);
    if (result != ESP_OK) {
        return result;
    }
    *allocated_bytes = allocation_bytes;

    result = esp_himem_alloc_map_range(ESP_HIMEM_BLKSZ, &range);
    if (result != ESP_OK) {
        (void)esp_himem_free(memory);
        return result;
    }

    bool mapping_active = false;
    const size_t words_per_block = ESP_HIMEM_BLKSZ / sizeof(uint32_t);
    for (unsigned int pass = 0; pass < 2 && result == ESP_OK; ++pass) {
        for (size_t offset = 0; offset < allocation_bytes;
             offset += ESP_HIMEM_BLKSZ) {
            void *mapped = NULL;
            result = esp_himem_map(
                memory, range, offset, 0, ESP_HIMEM_BLKSZ, 0, &mapped);
            if (result != ESP_OK) {
                break;
            }
            mapping_active = true;

            volatile uint32_t *words = mapped;
            const uint32_t seed = 0xA55A5AA5U ^
                (uint32_t)(offset / ESP_HIMEM_BLKSZ);
            bool block_matches = true;
            for (size_t index = 0; index < words_per_block; ++index) {
                const uint32_t expected = seed ^
                    ((uint32_t)index * 0x9E3779B1U);
                if (pass == 0) {
                    words[index] = expected;
                } else if (words[index] != expected) {
                    block_matches = false;
                    TIVOO_LOGE(
                        TAG,
                        "himem_probe_mismatch offset=%zu word=%zu",
                        offset, index);
                    break;
                }
            }

            const esp_err_t unmap_result =
                esp_himem_unmap(range, mapped, ESP_HIMEM_BLKSZ);
            if (unmap_result == ESP_OK) {
                mapping_active = false;
            } else {
                result = unmap_result;
                break;
            }
            if (!block_matches) {
                result = ESP_FAIL;
                break;
            }
        }
    }

    if (result == ESP_OK) {
        *tested_bytes = allocation_bytes;
        *tested_blocks = allocation_bytes / ESP_HIMEM_BLKSZ;
    }

    if (!mapping_active) {
        const esp_err_t free_memory_result = esp_himem_free(memory);
        const esp_err_t free_range_result = esp_himem_free_map_range(range);
        if (result == ESP_OK && free_memory_result != ESP_OK) {
            result = free_memory_result;
        }
        if (result == ESP_OK && free_range_result != ESP_OK) {
            result = free_range_result;
        }
    }
    return result;
}

void tivoo_hardware_memory_report(void)
{
    uint32_t flash_bytes = 0;
    const esp_err_t flash_result = esp_flash_get_size(NULL, &flash_bytes);
    const bool psram_initialized = esp_psram_is_initialized();
    const size_t psram_bytes = psram_initialized ? esp_psram_get_size() : 0;
    const size_t linear_total = heap_caps_get_total_size(MALLOC_CAP_SPIRAM);
    const size_t linear_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    const size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);

    TIVOO_LOGI(
        TAG,
        "memory_flash result=%s bytes=%" PRIu32,
        esp_err_to_name(flash_result), flash_bytes);
    TIVOO_LOGI(
        TAG,
        "memory_psram initialized=%u bytes=%zu linear_heap_total=%zu linear_heap_free=%zu internal_heap_free=%zu",
        psram_initialized ? 1U : 0U,
        psram_bytes, linear_total, linear_free, internal_free);

    if (!psram_initialized) {
        TIVOO_LOGE(TAG, "himem_probe_ok=0 reason=psram_not_initialized");
        return;
    }

    const size_t himem_physical = esp_himem_get_phys_size();
    const size_t himem_free = esp_himem_get_free_size();
    const size_t himem_window = esp_himem_reserved_area_size();
    TIVOO_LOGI(
        TAG,
        "memory_himem physical=%zu free=%zu map_window=%zu block=%u",
        himem_physical, himem_free, himem_window,
        (unsigned int)ESP_HIMEM_BLKSZ);

    size_t allocated_bytes = 0;
    size_t tested_bytes = 0;
    size_t tested_blocks = 0;
    const esp_err_t probe_result = probe_himem(
        &allocated_bytes, &tested_bytes, &tested_blocks);
    TIVOO_LOGI(
        TAG,
        "himem_probe_ok=%u result=%s allocated=%zu tested=%zu blocks=%zu free_after=%zu",
        probe_result == ESP_OK ? 1U : 0U,
        esp_err_to_name(probe_result), allocated_bytes, tested_bytes,
        tested_blocks, esp_himem_get_free_size());
}
