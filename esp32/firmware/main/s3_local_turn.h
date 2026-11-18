#pragma once
#include "esp_err.h"
#include "p68_afe_flow.h"

esp_err_t tivoo_s3_local_turn_init(bool test_gate, bool calibrated, unsigned tail, int offset);
void tivoo_s3_local_turn_event(void *ctx, const tivoo_afe_event_t *event);
void tivoo_s3_local_turn_tick(void);
bool tivoo_s3_local_turn_followup_message(const uint8_t *payload, size_t size);
void tivoo_s3_local_turn_playback_finished(const char *session_id, const char *playback_id, uint32_t epoch, bool completed);
bool tivoo_s3_local_turn_ready_message(const uint8_t *payload, size_t size);
void tivoo_s3_local_turn_stop(const char *session_id, const char *reason);
bool tivoo_s3_local_turn_bind_playback(const char *session_id, const char *playback_id);
