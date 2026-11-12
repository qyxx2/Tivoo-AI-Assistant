#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_GAP_IO_CAP_NONE 3

typedef enum {
    TIVOO_GAP_EVENT_PIN_REQUEST,
    TIVOO_GAP_EVENT_SSP_CONFIRM,
    TIVOO_GAP_EVENT_SSP_PASSKEY,
    TIVOO_GAP_EVENT_AUTH_COMPLETE,
} tivoo_gap_event_t;

typedef struct {
    uint8_t peer[6];
    bool min_16_digit;
    int status;
    uint8_t link_key_type;
} tivoo_gap_event_data_t;

typedef struct {
    void *context;
    bool (*set_io_capability)(void *context, uint8_t capability);
    bool (*pin_reply)(
        void *context, const uint8_t peer[6], bool accept,
        const uint8_t *pin, size_t pin_size);
    bool (*ssp_confirm_reply)(
        void *context, const uint8_t peer[6], bool accept);
    bool (*ssp_passkey_reply)(
        void *context, const uint8_t peer[6], bool accept, uint32_t passkey);
    void (*auth_complete)(
        void *context, const uint8_t peer[6], int status, uint8_t link_key_type,
        bool target_match, bool authenticated);
} tivoo_gap_callbacks_t;

typedef struct {
    uint8_t target[6];
    bool authenticated;
    int auth_status;
    uint8_t link_key_type;
    tivoo_gap_callbacks_t callbacks;
} tivoo_gap_security_t;

bool tivoo_gap_security_init(
    tivoo_gap_security_t *security,
    const uint8_t target[6],
    const tivoo_gap_callbacks_t *callbacks);
bool tivoo_gap_security_handle(
    tivoo_gap_security_t *security,
    tivoo_gap_event_t event,
    const tivoo_gap_event_data_t *data);
bool tivoo_gap_security_authenticated(const tivoo_gap_security_t *security);
bool tivoo_gap_bond_contains(
    const uint8_t target[6],
    const uint8_t (*bond_addresses)[6],
    size_t bond_count);
