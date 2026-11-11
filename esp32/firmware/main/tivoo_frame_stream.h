/*
 * Frame stream parser adapted from esp32-divoom/components/divoom/util.h.
 * Copyright (c) 2024 Dirk Sarodnick. SPDX-License-Identifier: MIT.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_FRAME_BUFFER_SIZE 4608

typedef struct {
    uint8_t data[TIVOO_FRAME_BUFFER_SIZE];
    size_t size;
} tivoo_frame_stream_t;

typedef void (*tivoo_frame_handler_t)(const uint8_t *buffer, size_t size);

size_t tivoo_frame_get_size(const uint8_t *buffer, size_t size);
bool tivoo_frame_is_pending(const uint8_t *buffer, size_t size);
void tivoo_frame_append(
    tivoo_frame_stream_t *stream,
    const uint8_t *buffer,
    size_t size,
    tivoo_frame_handler_t handler);
