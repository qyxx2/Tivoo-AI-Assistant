#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool tivoo_device_status_handle_message(
    uint8_t type, const uint8_t *payload, size_t size);
bool tivoo_device_status_set_audio_resource(bool fetching, const char *playback_id);
bool tivoo_device_status_report_event(
    const char *event, const uint8_t peer[6]);
bool tivoo_device_status_report_transition(
    const char *event,
    int previous_state,
    int current_state,
    const uint8_t peer[6]);
