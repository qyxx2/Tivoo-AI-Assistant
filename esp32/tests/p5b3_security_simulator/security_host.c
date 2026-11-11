#include "bt_security_policy.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    unsigned int io_capability_calls;
    uint8_t io_capability;
    unsigned int pin_calls;
    bool pin_accepted;
    uint8_t pin[16];
    size_t pin_size;
    unsigned int confirm_calls;
    bool confirm_accepted;
    unsigned int passkey_calls;
    bool passkey_accepted;
    uint32_t passkey;
    unsigned int auth_complete_calls;
    uint8_t auth_peer[6];
    int auth_status;
    uint8_t auth_link_key_type;
    bool auth_target_match;
    bool auth_authenticated;
} capture_t;

static bool set_io_capability(void *context, uint8_t value)
{
    capture_t *capture = context;
    capture->io_capability_calls++;
    capture->io_capability = value;
    return true;
}

static bool pin_reply(
    void *context, const uint8_t peer[6], bool accept,
    const uint8_t *pin, size_t pin_size)
{
    (void)peer;
    capture_t *capture = context;
    capture->pin_calls++;
    capture->pin_accepted = accept;
    capture->pin_size = pin_size;
    if (pin_size > sizeof(capture->pin)) {
        return false;
    }
    if (pin != NULL) {
        memcpy(capture->pin, pin, pin_size);
    }
    return true;
}

static bool confirm_reply(void *context, const uint8_t peer[6], bool accept)
{
    (void)peer;
    capture_t *capture = context;
    capture->confirm_calls++;
    capture->confirm_accepted = accept;
    return true;
}

static bool passkey_reply(
    void *context, const uint8_t peer[6], bool accept, uint32_t passkey)
{
    (void)peer;
    capture_t *capture = context;
    capture->passkey_calls++;
    capture->passkey_accepted = accept;
    capture->passkey = passkey;
    return true;
}

static void auth_complete(
    void *context, const uint8_t peer[6], int status, uint8_t link_key_type,
    bool target_match, bool authenticated)
{
    capture_t *capture = context;
    capture->auth_complete_calls++;
    memcpy(capture->auth_peer, peer, sizeof(capture->auth_peer));
    capture->auth_status = status;
    capture->auth_link_key_type = link_key_type;
    capture->auth_target_match = target_match;
    capture->auth_authenticated = authenticated;
}

int main(void)
{
    const uint8_t target[6] = {0x11, 0x75, 0x58, 0x97, 0x49, 0x98};
    const uint8_t other[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};
    capture_t capture = {0};
    tivoo_gap_callbacks_t callbacks = {
        .context = &capture,
        .set_io_capability = set_io_capability,
        .pin_reply = pin_reply,
        .ssp_confirm_reply = confirm_reply,
        .ssp_passkey_reply = passkey_reply,
        .auth_complete = auth_complete,
    };
    tivoo_gap_security_t security;
    assert(tivoo_gap_security_init(&security, target, &callbacks));
    assert(capture.io_capability_calls == 1);
    assert(capture.io_capability == TIVOO_GAP_IO_CAP_NONE);

    tivoo_gap_event_data_t event = {.peer = {0}, .min_16_digit = true};
    memcpy(event.peer, target, sizeof(target));
    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_PIN_REQUEST, &event));
    assert(capture.pin_calls == 1 && capture.pin_accepted);
    assert(capture.pin_size == 16);
    for (size_t i = 0; i < 16; i++) {
        assert(capture.pin[i] == '0');
    }

    event.min_16_digit = false;
    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_PIN_REQUEST, &event));
    assert(capture.pin_calls == 2 && capture.pin_accepted);
    assert(capture.pin_size == 4 && memcmp(capture.pin, "1234", 4) == 0);

    memcpy(event.peer, other, sizeof(other));
    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_PIN_REQUEST, &event));
    assert(capture.pin_calls == 3 && !capture.pin_accepted);

    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_SSP_CONFIRM, &event));
    assert(capture.confirm_calls == 1 && !capture.confirm_accepted);
    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_SSP_PASSKEY, &event));
    assert(capture.passkey_calls == 1 && !capture.passkey_accepted);
    assert(capture.passkey == 0);

    event.status = 0;
    event.link_key_type = 2;
    memcpy(event.peer, other, sizeof(other));
    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_AUTH_COMPLETE, &event));
    assert(!tivoo_gap_security_authenticated(&security));
    assert(capture.auth_complete_calls == 1);
    assert(memcmp(capture.auth_peer, other, 6) == 0);
    assert(capture.auth_status == 0 && capture.auth_link_key_type == 2);
    assert(!capture.auth_target_match && !capture.auth_authenticated);

    memcpy(event.peer, target, sizeof(target));
    event.status = 1;
    event.link_key_type = 4;
    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_AUTH_COMPLETE, &event));
    assert(!tivoo_gap_security_authenticated(&security));
    assert(capture.auth_complete_calls == 2);
    assert(memcmp(capture.auth_peer, target, 6) == 0);
    assert(capture.auth_status == 1 && capture.auth_link_key_type == 4);
    assert(capture.auth_target_match && !capture.auth_authenticated);

    event.status = 0;
    event.link_key_type = 5;
    assert(tivoo_gap_security_handle(&security, TIVOO_GAP_EVENT_AUTH_COMPLETE, &event));
    assert(tivoo_gap_security_authenticated(&security));
    assert(capture.auth_complete_calls == 3);
    assert(capture.auth_status == 0 && capture.auth_link_key_type == 5);
    assert(capture.auth_target_match && capture.auth_authenticated);

    uint8_t bonds[3][6] = {
        {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF},
        {0x11, 0x75, 0x58, 0x97, 0x49, 0x98},
        {0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    };
    assert(tivoo_gap_bond_contains(target, (const uint8_t (*)[6])bonds, 3));
    assert(!tivoo_gap_bond_contains(target, (const uint8_t (*)[6])bonds, 1));
    assert(!tivoo_gap_bond_contains(target, NULL, 0));

    puts("P5b3 GAP policy checks passed");
    return 0;
}
