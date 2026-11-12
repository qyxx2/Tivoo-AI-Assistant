/*
 * Frame stream parser adapted from esp32-divoom/components/divoom/util.cpp.
 * Copyright (c) 2024 Dirk Sarodnick. SPDX-License-Identifier: MIT.
 */
#include "tivoo_frame_stream.h"

#include <string.h>

static bool frame_valid(const uint8_t *payload, size_t size)
{
    if (size < 5) {
        return false;
    }

    const size_t length = (size_t)payload[0] | ((size_t)payload[1] << 8);
    if (length + 2 != size && length + 4 != size) {
        return false;
    }

    uint32_t sum = 0;
    uint32_t checksum = 0;
    for (size_t i = 0; i < length; i++) {
        sum += payload[i];
    }
    for (size_t i = length; i < size; i++) {
        checksum |= (uint32_t)payload[i] << ((i - length) * 8);
    }
    return sum == checksum;
}

static bool escaped_frame_valid(const uint8_t *payload, size_t size)
{
    size_t index = 0;
    size_t length = 0;
    uint32_t sum = 0;
    uint32_t checksum = 0;

    for (size_t i = 0; i < size; i++) {
        uint8_t value = payload[i];
        if (value == 0x03) {
            if (++i >= size) {
                return false;
            }
            value = (uint8_t)(payload[i] - 0x03);
        }

        if (index == 0) {
            length = value;
        } else if (index == 1) {
            length |= (size_t)value << 8;
        }
        if (index < length) {
            sum += value;
        } else if (index < length + 4) {
            checksum |= (uint32_t)value << ((index - length) * 8);
        }
        index++;
    }

    if (index < 5 || (index != length + 2 && index != length + 4)) {
        return false;
    }
    return sum == checksum;
}

size_t tivoo_frame_get_size(const uint8_t *buffer, size_t size)
{
    if (size < 6 || buffer[0] != 0x01) {
        return 0;
    }

    const size_t length = (size_t)buffer[1] | ((size_t)buffer[2] << 8);
    for (size_t checksum_size = 2; checksum_size <= 4; checksum_size += 2) {
        const size_t frame_size = length + checksum_size + 2;
        if (frame_size > size || buffer[frame_size - 1] != 0x02) {
            continue;
        }
        if (frame_valid(buffer + 1, length + checksum_size)) {
            return frame_size;
        }
    }

    for (size_t i = 1; i < size; i++) {
        if (buffer[i] != 0x02) {
            continue;
        }
        return escaped_frame_valid(buffer + 1, i - 1) ? i + 1 : 0;
    }
    return 0;
}

bool tivoo_frame_is_pending(const uint8_t *buffer, size_t size)
{
    if (size == 0 || buffer[0] != 0x01) {
        return false;
    }
    if (size < 6) {
        return true;
    }

    const size_t length = (size_t)buffer[1] | ((size_t)buffer[2] << 8);
    /* A normal frame needs start + length + payload/checksum + end. */
    if (length + 4 > TIVOO_FRAME_BUFFER_SIZE) {
        return false;
    }
    if (size < length + 4) {
        return true;
    }
    for (size_t i = 1; i < size; i++) {
        if (buffer[i] == 0x02) {
            return false;
        }
    }
    return true;
}

void tivoo_frame_append(
    tivoo_frame_stream_t *stream,
    const uint8_t *buffer,
    size_t size,
    tivoo_frame_handler_t handler)
{
    while (size > 0) {
        size_t take = sizeof(stream->data) - stream->size;
        if (take > size) {
            take = size;
        }

        memcpy(stream->data + stream->size, buffer, take);
        stream->size += take;
        buffer += take;
        size -= take;

        size_t offset = 0;
        size_t frame_size = 0;
        while ((frame_size = tivoo_frame_get_size(
                    stream->data + offset, stream->size - offset)) > 0) {
            handler(stream->data + offset, frame_size);
            offset += frame_size;
        }

        size_t rest = stream->size - offset;
        if (rest > 0 &&
            (take == 0 || !tivoo_frame_is_pending(stream->data + offset, rest))) {
            handler(stream->data + offset, rest);
            offset = stream->size;
            rest = 0;
        }

        memmove(stream->data, stream->data + offset, rest);
        stream->size = rest;
    }
}
