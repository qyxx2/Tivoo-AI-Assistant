#include "bt_security_policy.h"

#include <string.h>

bool tivoo_gap_security_init(
    tivoo_gap_security_t *security,
    const uint8_t target[6],
    const tivoo_gap_callbacks_t *callbacks)
{
    if (security == NULL || target == NULL || callbacks == NULL ||
        callbacks->set_io_capability == NULL || callbacks->pin_reply == NULL ||
        callbacks->ssp_confirm_reply == NULL ||
        callbacks->ssp_passkey_reply == NULL) {
        return false;
    }

    memset(security, 0, sizeof(*security));
    memcpy(security->target, target, sizeof(security->target));
    security->callbacks = *callbacks;
    return security->callbacks.set_io_capability(
        security->callbacks.context, TIVOO_GAP_IO_CAP_NONE);
}

bool tivoo_gap_security_handle(
    tivoo_gap_security_t *security,
    tivoo_gap_event_t event,
    const tivoo_gap_event_data_t *data)
{
    if (security == NULL || data == NULL) {
        return false;
    }

    const bool is_target = memcmp(security->target, data->peer, 6) == 0;
    switch (event) {
    case TIVOO_GAP_EVENT_PIN_REQUEST: {
        static const uint8_t legacy_pin[] = {'1', '2', '3', '4'};
        static const uint8_t long_pin[16] = {
            '0', '0', '0', '0', '0', '0', '0', '0',
            '0', '0', '0', '0', '0', '0', '0', '0',
        };
        if (!is_target) {
            return security->callbacks.pin_reply(
                security->callbacks.context, data->peer, false, NULL, 0);
        }
        const uint8_t *pin = data->min_16_digit ? long_pin : legacy_pin;
        const size_t pin_size = data->min_16_digit ? sizeof(long_pin) : sizeof(legacy_pin);
        return security->callbacks.pin_reply(
            security->callbacks.context, data->peer, true, pin, pin_size);
    }
    case TIVOO_GAP_EVENT_SSP_CONFIRM:
        return security->callbacks.ssp_confirm_reply(
            security->callbacks.context, data->peer, false);
    case TIVOO_GAP_EVENT_SSP_PASSKEY:
        return security->callbacks.ssp_passkey_reply(
            security->callbacks.context, data->peer, false, 0);
    case TIVOO_GAP_EVENT_AUTH_COMPLETE:
        security->authenticated = is_target && data->status == 0;
        security->auth_status = data->status;
        security->link_key_type = data->link_key_type;
        return true;
    default:
        return false;
    }
}

bool tivoo_gap_security_authenticated(const tivoo_gap_security_t *security)
{
    return security != NULL && security->authenticated;
}

bool tivoo_gap_bond_contains(
    const uint8_t target[6],
    const uint8_t (*bond_addresses)[6],
    size_t bond_count)
{
    if (target == NULL || bond_addresses == NULL) {
        return false;
    }
    for (size_t i = 0; i < bond_count; i++) {
        if (memcmp(target, bond_addresses[i], 6) == 0) {
            return true;
        }
    }
    return false;
}
