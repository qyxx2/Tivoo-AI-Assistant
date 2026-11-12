#include "tivoo_spp.h"

#include <inttypes.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

#include "bt_security_policy.h"
#include "control_bridge.h"
#include "diagnostics.h"
#include "device_status.h"
#include "esp_bt.h"
#include "esp_bt_device.h"
#include "esp_bt_main.h"
#include "esp_gap_bt_api.h"
#include "esp_log.h"
#include "esp_spp_api.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "tivoo_frame_stream.h"
#include "tivoo_spp_session.h"

#define SPP_TX_QUEUE_SIZE 32
#define SPP_QUEUE_WRITE_TIMEOUT_MS 1000
#define SPP_READY_TIMEOUT_MS 10000
#define SPP_OPERATION_TIMEOUT_MS 10000
#define SPP_WRITE_TIMEOUT_MS 1000
#define SPP_CONGESTION_TIMEOUT_MS 1000
#define SPP_OPEN_SETTLE_MS 500
#define SPP_WORKER_POLL_MS 250
#define SPP_RECONNECT_RETRY_MS 2000

#define EVENT_SPP_READY BIT0
#define EVENT_SPP_INIT_FAILED BIT1
#define EVENT_DISCOVERY_DONE BIT2
#define EVENT_OPEN BIT3
#define EVENT_AUTH_DONE BIT4
#define EVENT_AUTH_OK BIT5
#define EVENT_FAILED BIT6
#define EVENT_CLOSED BIT7
#define EVENT_UNCONGESTED BIT8
#define EVENT_WRITE_DONE BIT9
#define EVENT_LINK_LOST BIT10
#define EVENT_AUTO_RECONNECT BIT11

static const char *TAG = "tivoo_spp";

typedef enum {
    REQUEST_CONNECT,
    REQUEST_DISCONNECT,
    REQUEST_RECONNECT,
    REQUEST_FRAME,
} request_type_t;

typedef struct {
    request_type_t type;
    uint8_t peer[6];
    size_t size;
    uint8_t data[];
} spp_request_t;

static QueueHandle_t s_request_queue;
static EventGroupHandle_t s_events;
static uint8_t s_target[6];
static TickType_t s_reconnect_not_before;
static volatile uint32_t s_handle;
static uint8_t s_discovered_scn;
static tivoo_gap_security_t s_gap_security;
static tivoo_spp_session_t s_session;

typedef tivoo_spp_link_state_t spp_link_state_t;
#define SPP_LINK_DISCONNECTED TIVOO_SPP_LINK_DISCONNECTED
#define SPP_LINK_CONNECTING TIVOO_SPP_LINK_CONNECTING
#define SPP_LINK_CONNECTED TIVOO_SPP_LINK_CONNECTED

static atomic_int s_link_state = ATOMIC_VAR_INIT(SPP_LINK_DISCONNECTED);
static atomic_bool s_disconnect_pending = ATOMIC_VAR_INIT(false);
static portMUX_TYPE s_link_peer_mux = portMUX_INITIALIZER_UNLOCKED;
static bool s_link_peer_valid;
static uint8_t s_link_peer[6];

static void publish_link_peer(const uint8_t peer[6])
{
    portENTER_CRITICAL(&s_link_peer_mux);
    memcpy(s_link_peer, peer, sizeof(s_link_peer));
    s_link_peer_valid = true;
    portEXIT_CRITICAL(&s_link_peer_mux);
}

static void clear_link_peer(void)
{
    portENTER_CRITICAL(&s_link_peer_mux);
    s_link_peer_valid = false;
    portEXIT_CRITICAL(&s_link_peer_mux);
}

static bool link_peer_matches(const uint8_t peer[6])
{
    portENTER_CRITICAL(&s_link_peer_mux);
    const bool matches = s_link_peer_valid &&
        memcmp(s_link_peer, peer, sizeof(s_link_peer)) == 0;
    portEXIT_CRITICAL(&s_link_peer_mux);
    return matches;
}

static void report_link_event(const char *event)
{
    uint8_t peer[6];
    const uint8_t *peer_data = NULL;
    portENTER_CRITICAL(&s_link_peer_mux);
    if (s_link_peer_valid) {
        memcpy(peer, s_link_peer, sizeof(peer));
        peer_data = peer;
    }
    portEXIT_CRITICAL(&s_link_peer_mux);
    (void)tivoo_device_status_report_event(event, peer_data);
}

static void set_link_state(spp_link_state_t state)
{
    const int previous = atomic_exchange(&s_link_state, (int)state);
    if (previous == (int)state) {
        return;
    }

    const char *event = state == SPP_LINK_CONNECTING
        ? "spp_connecting"
        : (state == SPP_LINK_CONNECTED ? "spp_connected" : "spp_disconnected");
    report_link_event(event);
}

void tivoo_spp_get_status(
    tivoo_spp_link_state_t *state, uint8_t peer[6], bool *peer_valid)
{
    if (state != NULL) {
        *state = (tivoo_spp_link_state_t)atomic_load(&s_link_state);
    }
    portENTER_CRITICAL(&s_link_peer_mux);
    if (peer_valid != NULL) {
        *peer_valid = s_link_peer_valid;
    }
    if (peer != NULL) {
        if (s_link_peer_valid) {
            memcpy(peer, s_link_peer, sizeof(s_link_peer));
        } else {
            memset(peer, 0, sizeof(s_link_peer));
        }
    }
    portEXIT_CRITICAL(&s_link_peer_mux);
}

static bool same_address(const uint8_t left[6], const uint8_t right[6])
{
    return memcmp(left, right, 6) == 0;
}

static void report_spp_error(const char *code, const char *detail)
{
    tivoo_report_error(code, TAG, detail);
}

static bool gap_set_io_capability(void *context, uint8_t capability)
{
    (void)context;
    esp_bt_io_cap_t value = capability;
    return esp_bt_gap_set_security_param(
        ESP_BT_SP_IOCAP_MODE, &value, sizeof(value)) == ESP_OK;
}

static bool gap_pin_reply(
    void *context, const uint8_t peer[6], bool accept,
    const uint8_t *pin, size_t pin_size)
{
    (void)context;
    esp_bt_pin_code_t code = {0};
    if (pin_size > sizeof(code)) {
        return false;
    }
    if (pin != NULL && pin_size > 0) {
        memcpy(code, pin, pin_size);
    }
    return esp_bt_gap_pin_reply(
        (uint8_t *)peer, accept, (uint8_t)pin_size, code) == ESP_OK;
}

static bool gap_ssp_confirm_reply(
    void *context, const uint8_t peer[6], bool accept)
{
    (void)context;
    return esp_bt_gap_ssp_confirm_reply((uint8_t *)peer, accept) == ESP_OK;
}

static bool gap_ssp_passkey_reply(
    void *context, const uint8_t peer[6], bool accept, uint32_t passkey)
{
    (void)context;
    return esp_bt_gap_ssp_passkey_reply(
        (uint8_t *)peer, accept, passkey) == ESP_OK;
}

static void gap_auth_complete(
    void *context, const uint8_t peer[6], int status, uint8_t link_key_type,
    bool target_match, bool authenticated)
{
    (void)context;
    if (authenticated) {
        TIVOO_LOGI(
            TAG,
            "auth_complete peer=%02X:%02X:%02X:%02X:%02X:%02X status=%d link_key_type=%u target_match=1 authenticated=1",
            peer[0], peer[1], peer[2], peer[3], peer[4], peer[5], status,
            (unsigned int)link_key_type);
    } else {
        TIVOO_LOGW(
            TAG,
            "auth_complete peer=%02X:%02X:%02X:%02X:%02X:%02X status=%d link_key_type=%u target_match=%u authenticated=0",
            peer[0], peer[1], peer[2], peer[3], peer[4], peer[5], status,
            (unsigned int)link_key_type, target_match ? 1U : 0U);
    }
}

static const tivoo_gap_callbacks_t s_gap_callbacks = {
    .context = NULL,
    .set_io_capability = gap_set_io_capability,
    .pin_reply = gap_pin_reply,
    .ssp_confirm_reply = gap_ssp_confirm_reply,
    .ssp_passkey_reply = gap_ssp_passkey_reply,
    .auth_complete = gap_auth_complete,
};

static void gap_event_handler(
    esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param)
{
    if (param == NULL) {
        return;
    }

    tivoo_gap_event_data_t event_data = {0};
    tivoo_gap_event_t policy_event;
    switch (event) {
    case ESP_BT_GAP_PIN_REQ_EVT:
        memcpy(event_data.peer, param->pin_req.bda, 6);
        event_data.min_16_digit = param->pin_req.min_16_digit;
        TIVOO_LOGI(
            TAG,
            "gap_pin_request peer=%02X:%02X:%02X:%02X:%02X:%02X min_16_digit=%u",
            event_data.peer[0], event_data.peer[1], event_data.peer[2],
            event_data.peer[3], event_data.peer[4], event_data.peer[5],
            event_data.min_16_digit ? 1U : 0U);
        policy_event = TIVOO_GAP_EVENT_PIN_REQUEST;
        break;
    case ESP_BT_GAP_CFM_REQ_EVT:
        memcpy(event_data.peer, param->cfm_req.bda, 6);
        TIVOO_LOGW(
            TAG,
            "gap_ssp_confirm_request_rejected peer=%02X:%02X:%02X:%02X:%02X:%02X reason=no_display",
            event_data.peer[0], event_data.peer[1], event_data.peer[2],
            event_data.peer[3], event_data.peer[4], event_data.peer[5]);
        policy_event = TIVOO_GAP_EVENT_SSP_CONFIRM;
        break;
    case ESP_BT_GAP_KEY_REQ_EVT:
        memcpy(event_data.peer, param->key_req.bda, 6);
        TIVOO_LOGW(
            TAG,
            "gap_passkey_request_rejected peer=%02X:%02X:%02X:%02X:%02X:%02X reason=no_keyboard",
            event_data.peer[0], event_data.peer[1], event_data.peer[2],
            event_data.peer[3], event_data.peer[4], event_data.peer[5]);
        policy_event = TIVOO_GAP_EVENT_SSP_PASSKEY;
        break;
    case ESP_BT_GAP_AUTH_CMPL_EVT:
        memcpy(event_data.peer, param->auth_cmpl.bda, 6);
        event_data.status = (int)param->auth_cmpl.stat;
        event_data.link_key_type = (uint8_t)param->auth_cmpl.lk_type;
        policy_event = TIVOO_GAP_EVENT_AUTH_COMPLETE;
        break;
    case ESP_BT_GAP_KEY_NOTIF_EVT:
        /* Never print or expose the displayed passkey. */
        return;
    default:
        return;
    }

    (void)tivoo_gap_security_handle(&s_gap_security, policy_event, &event_data);
    if (event == ESP_BT_GAP_AUTH_CMPL_EVT) {
        xEventGroupSetBits(s_events, EVENT_AUTH_DONE);
        if (tivoo_gap_security_authenticated(&s_gap_security) &&
            same_address(event_data.peer, s_target)) {
            xEventGroupSetBits(s_events, EVENT_AUTH_OK);
        } else {
            xEventGroupSetBits(s_events, EVENT_FAILED);
        }
    }
}

static void spp_event_handler(esp_spp_cb_event_t event, esp_spp_cb_param_t *param)
{
    if (param == NULL || s_events == NULL) {
        return;
    }

    switch (event) {
    case ESP_SPP_INIT_EVT:
        if (param->init.status == ESP_SPP_SUCCESS) {
            xEventGroupSetBits(s_events, EVENT_SPP_READY);
        } else {
            xEventGroupSetBits(s_events, EVENT_SPP_INIT_FAILED);
        }
        break;
    case ESP_SPP_DISCOVERY_COMP_EVT:
        s_discovered_scn = 0;
        if (param->disc_comp.status == ESP_SPP_SUCCESS &&
            param->disc_comp.scn_num > 0) {
            s_discovered_scn = param->disc_comp.scn[0];
        }
        TIVOO_LOGI(
            TAG,
            "spp_discovery_complete status=%d scn_num=%u scn0=%u",
            (int)param->disc_comp.status,
            (unsigned int)param->disc_comp.scn_num,
            (unsigned int)s_discovered_scn);
        xEventGroupSetBits(s_events, EVENT_DISCOVERY_DONE);
        break;
    case ESP_SPP_CL_INIT_EVT:
        TIVOO_LOGI(
            TAG,
            "spp_client_init status=%d handle=%" PRIu32 " sec_id=%u",
            (int)param->cl_init.status,
            param->cl_init.handle,
            (unsigned int)param->cl_init.sec_id);
        if (param->cl_init.status != ESP_SPP_SUCCESS) {
            xEventGroupSetBits(s_events, EVENT_FAILED);
        }
        break;
    case ESP_SPP_OPEN_EVT:
        TIVOO_LOGI(
            TAG,
            "spp_open status=%d handle=%" PRIu32 " peer=%02X:%02X:%02X:%02X:%02X:%02X",
            (int)param->open.status,
            param->open.handle,
            param->open.rem_bda[0], param->open.rem_bda[1],
            param->open.rem_bda[2], param->open.rem_bda[3],
            param->open.rem_bda[4], param->open.rem_bda[5]);
        if (param->open.status != ESP_SPP_SUCCESS ||
            !same_address(param->open.rem_bda, s_target)) {
            if (param->open.status == ESP_SPP_SUCCESS) {
                (void)esp_spp_disconnect(param->open.handle);
            }
            xEventGroupSetBits(s_events, EVENT_FAILED);
            break;
        }
        s_handle = param->open.handle;
        xEventGroupSetBits(s_events, EVENT_OPEN | EVENT_UNCONGESTED);
        break;
    case ESP_SPP_CLOSE_EVT:
        TIVOO_LOGW(
            TAG,
            "spp_close status=%d handle=%" PRIu32 " async=%u port_status=%" PRIu32,
            (int)param->close.status,
            param->close.handle,
            param->close.async ? 1U : 0U,
            param->close.port_status);
        if (param->close.handle == s_handle) {
            s_handle = 0;
            atomic_store(&s_disconnect_pending, false);
            const int previous_state = atomic_exchange(
                &s_link_state, SPP_LINK_DISCONNECTED);
            if (previous_state != SPP_LINK_DISCONNECTED) {
                report_link_event("spp_disconnected");
            }
            xEventGroupClearBits(s_events, EVENT_OPEN | EVENT_UNCONGESTED);
            EventBits_t close_bits = EVENT_CLOSED;
            if ((xEventGroupGetBits(s_events) & EVENT_AUTO_RECONNECT) != 0) {
                close_bits |= EVENT_FAILED | EVENT_LINK_LOST;
            } else if (param->close.status != ESP_SPP_SUCCESS) {
                close_bits |= EVENT_FAILED;
            }
            xEventGroupSetBits(s_events, close_bits);
        }
        break;
    case ESP_SPP_CONG_EVT:
        if (param->cong.handle == s_handle) {
            if (param->cong.status != ESP_SPP_SUCCESS) {
                xEventGroupSetBits(s_events, EVENT_FAILED);
            } else if (param->cong.cong) {
                xEventGroupClearBits(s_events, EVENT_UNCONGESTED);
            } else {
                xEventGroupSetBits(s_events, EVENT_UNCONGESTED);
            }
        }
        break;
    case ESP_SPP_WRITE_EVT:
        if (param->write.handle == s_handle) {
            if (param->write.status == ESP_SPP_SUCCESS) {
                if (param->write.cong) {
                    xEventGroupClearBits(s_events, EVENT_UNCONGESTED);
                } else {
                    xEventGroupSetBits(s_events, EVENT_UNCONGESTED);
                }
                xEventGroupSetBits(s_events, EVENT_WRITE_DONE);
            } else {
                xEventGroupSetBits(s_events, EVENT_FAILED);
            }
        }
        break;
    case ESP_SPP_DATA_IND_EVT:
        if (param->data_ind.handle == s_handle &&
            param->data_ind.data != NULL && param->data_ind.len > 0) {
            (void)tivoo_control_spp_data(
                (const uint8_t *)param->data_ind.data,
                (size_t)param->data_ind.len);
        }
        break;
    default:
        break;
    }
}

static bool bond_list_contains_target(void)
{
    int bond_count = esp_bt_gap_get_bond_device_num();
    if (bond_count <= 0) {
        return false;
    }

    esp_bd_addr_t *addresses = calloc((size_t)bond_count, sizeof(*addresses));
    if (addresses == NULL) {
        return false;
    }

    int list_count = bond_count;
    esp_err_t err = esp_bt_gap_get_bond_device_list(&list_count, addresses);
    const bool found = err == ESP_OK && list_count > 0 &&
        tivoo_gap_bond_contains(
            s_target, (const uint8_t (*)[6])addresses, (size_t)list_count);
    free(addresses);
    return found;
}

static bool disconnect_active_peer(void)
{
    const uint32_t handle = s_handle;
    if (handle == 0) {
        return true;
    }

    xEventGroupClearBits(s_events, EVENT_CLOSED | EVENT_FAILED);
    esp_err_t err = esp_spp_disconnect(handle);
    if (err != ESP_OK) {
        return false;
    }

    EventBits_t bits = xEventGroupWaitBits(
        s_events, EVENT_CLOSED | EVENT_FAILED, pdFALSE, pdFALSE,
        pdMS_TO_TICKS(SPP_OPERATION_TIMEOUT_MS));
    if ((bits & EVENT_CLOSED) == 0) {
        return false;
    }
    return true;
}

static bool wait_for_open_and_auth(bool target_bonded)
{
    const TickType_t deadline =
        xTaskGetTickCount() + pdMS_TO_TICKS(SPP_OPERATION_TIMEOUT_MS);
    for (;;) {
        const EventBits_t current = xEventGroupGetBits(s_events);
        if ((current & EVENT_FAILED) != 0) {
            TIVOO_LOGW(
                TAG,
                "spp_connect_failed_events open=%u auth_done=%u auth_ok=%u failed=1",
                (current & EVENT_OPEN) != 0 ? 1U : 0U,
                (current & EVENT_AUTH_DONE) != 0 ? 1U : 0U,
                (current & EVENT_AUTH_OK) != 0 ? 1U : 0U);
            return false;
        }
        if (tivoo_spp_connection_is_ready(
                current, EVENT_OPEN, EVENT_AUTH_DONE, EVENT_AUTH_OK,
                EVENT_FAILED, target_bonded)) {
            return true;
        }

        const TickType_t now = xTaskGetTickCount();
        if (now >= deadline) {
            const EventBits_t final_bits = xEventGroupGetBits(s_events);
            TIVOO_LOGW(
                TAG,
                "spp_connect_wait_timeout open=%u auth_done=%u auth_ok=%u failed=%u",
                (final_bits & EVENT_OPEN) != 0 ? 1U : 0U,
                (final_bits & EVENT_AUTH_DONE) != 0 ? 1U : 0U,
                (final_bits & EVENT_AUTH_OK) != 0 ? 1U : 0U,
                (final_bits & EVENT_FAILED) != 0 ? 1U : 0U);
            return false;
        }
        const TickType_t remaining = deadline - now;
        const EventBits_t wait_mask = (EventBits_t)tivoo_spp_connection_wait_mask(
            current, EVENT_OPEN,
            target_bonded ? 0 : EVENT_AUTH_DONE, EVENT_FAILED);
        const EventBits_t observed = xEventGroupWaitBits(
            s_events, wait_mask, pdFALSE, pdFALSE, remaining);
        if ((observed & EVENT_FAILED) != 0) {
            TIVOO_LOGW(
                TAG,
                "spp_connect_failed_events open=%u auth_done=%u auth_ok=%u",
                (observed & EVENT_OPEN) != 0 ? 1U : 0U,
                (observed & EVENT_AUTH_DONE) != 0 ? 1U : 0U,
                (observed & EVENT_AUTH_OK) != 0 ? 1U : 0U);
            return false;
        }
    }
}

static bool connect_peer(const uint8_t peer[6])
{
    /* Retry cleanup if an earlier asynchronous disconnect did not complete. */
    if (s_handle != 0 && !disconnect_active_peer()) {
        return false;
    }

    memcpy(s_target, peer, sizeof(s_target));
    if (!tivoo_gap_security_init(&s_gap_security, s_target, &s_gap_callbacks)) {
        return false;
    }

    /* Successful reuse of a stored BR/EDR link key does not emit AUTH_CMPL. */
    const bool target_bonded_before_connect = bond_list_contains_target();

    xEventGroupClearBits(
        s_events,
        EVENT_DISCOVERY_DONE | EVENT_OPEN | EVENT_AUTH_DONE |
            EVENT_AUTH_OK | EVENT_FAILED | EVENT_CLOSED | EVENT_LINK_LOST);
    s_discovered_scn = 0;

    bool discovery_completed = false;
    const esp_err_t discovery_err =
        esp_spp_start_discovery((uint8_t *)s_target);
    if (discovery_err == ESP_OK) {
        const EventBits_t bits = xEventGroupWaitBits(
            s_events, EVENT_DISCOVERY_DONE, pdTRUE, pdTRUE,
            pdMS_TO_TICKS(SPP_OPERATION_TIMEOUT_MS));
        discovery_completed = (bits & EVENT_DISCOVERY_DONE) != 0;
    }
    if (!discovery_completed) {
        TIVOO_LOGW(
            TAG,
            "spp_discovery_unavailable api_err=%s completed=0 fallback_scn=1",
            esp_err_to_name(discovery_err));
    }

    const uint8_t channel = tivoo_spp_select_scn(
        discovery_completed, s_discovered_scn);
    if (!discovery_completed || s_discovered_scn == 0) {
        TIVOO_LOGW(TAG, "spp_scn_fallback");
    }

    esp_err_t err = esp_spp_connect(
        ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT,
        ESP_SPP_ROLE_MASTER,
        channel,
        (uint8_t *)s_target);
    TIVOO_LOGI(
        TAG,
        "spp_connect_requested peer=%02X:%02X:%02X:%02X:%02X:%02X scn=%u sec_mask=0x%04X api_err=%s",
        s_target[0], s_target[1], s_target[2], s_target[3], s_target[4],
        s_target[5], (unsigned int)channel,
        (unsigned int)(ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT),
        esp_err_to_name(err));
    if (err != ESP_OK ||
        !wait_for_open_and_auth(target_bonded_before_connect)) {
        if (s_handle != 0) {
            (void)disconnect_active_peer();
        }
        return false;
    }

    if (!bond_list_contains_target()) {
        TIVOO_LOGW(
            TAG,
            "spp_bond_missing peer=%02X:%02X:%02X:%02X:%02X:%02X",
            s_target[0], s_target[1], s_target[2], s_target[3],
            s_target[4], s_target[5]);
        (void)disconnect_active_peer();
        return false;
    }

    if (target_bonded_before_connect) {
        TIVOO_LOGI(
            TAG,
            "spp_bond_reused_after_open peer=%02X:%02X:%02X:%02X:%02X:%02X security=authenticate+encrypt",
            s_target[0], s_target[1], s_target[2], s_target[3], s_target[4],
            s_target[5]);
    } else {
        TIVOO_LOGI(
            TAG,
            "spp_bond_created_after_auth peer=%02X:%02X:%02X:%02X:%02X:%02X",
            s_target[0], s_target[1], s_target[2], s_target[3], s_target[4],
            s_target[5]);
    }

    vTaskDelay(pdMS_TO_TICKS(SPP_OPEN_SETTLE_MS));
    TIVOO_LOGI(
        TAG,
        "authenticated_spp_peer_ready peer=%02X:%02X:%02X:%02X:%02X:%02X bond_list=confirmed",
        s_target[0], s_target[1], s_target[2], s_target[3], s_target[4],
        s_target[5]);
    return true;
}

static bool write_chunk(const uint8_t *data, size_t size)
{
    if (s_handle == 0) {
        return false;
    }

    EventBits_t bits = xEventGroupWaitBits(
        s_events, EVENT_UNCONGESTED | EVENT_FAILED,
        pdFALSE, pdFALSE, pdMS_TO_TICKS(SPP_CONGESTION_TIMEOUT_MS));
    if ((bits & EVENT_UNCONGESTED) == 0 || (bits & EVENT_FAILED) != 0) {
        return false;
    }

    xEventGroupClearBits(s_events, EVENT_WRITE_DONE | EVENT_FAILED);
    esp_err_t err = esp_spp_write(s_handle, (int)size, (uint8_t *)data);
    if (err != ESP_OK) {
        return false;
    }

    bits = xEventGroupWaitBits(
        s_events, EVENT_WRITE_DONE | EVENT_FAILED,
        pdTRUE, pdFALSE, pdMS_TO_TICKS(SPP_WRITE_TIMEOUT_MS));
    return (bits & EVENT_WRITE_DONE) != 0 &&
        (bits & EVENT_FAILED) == 0;
}

static bool session_disconnect(void *context, const uint8_t peer[6])
{
    (void)context;
    (void)peer;
    return disconnect_active_peer();
}

static bool session_connect(void *context, const uint8_t peer[6])
{
    (void)context;
    return connect_peer(peer);
}

static bool session_write_chunk(
    void *context, const uint8_t *data, size_t size)
{
    (void)context;
    return write_chunk(data, size);
}

static void session_delay(void *context, uint32_t delay_ms)
{
    (void)context;
    vTaskDelay(pdMS_TO_TICKS(delay_ms));
}

static const tivoo_spp_session_backend_t s_session_backend = {
    .context = NULL,
    .disconnect = session_disconnect,
    .connect = session_connect,
    .write_chunk = session_write_chunk,
    .delay_ms = session_delay,
};

static void service_spp_reconnect(void)
{
    if ((xEventGroupGetBits(s_events) & EVENT_AUTO_RECONNECT) == 0) {
        xEventGroupClearBits(s_events, EVENT_LINK_LOST);
        return;
    }

    const EventBits_t events = xEventGroupGetBits(s_events);
    if ((events & EVENT_LINK_LOST) != 0) {
        xEventGroupClearBits(s_events, EVENT_LINK_LOST);
        tivoo_spp_session_mark_disconnected(&s_session);
    }

    if (!s_session.peer_valid || s_session.connected) {
        return;
    }

    const TickType_t now = xTaskGetTickCount();
    if (s_reconnect_not_before != 0 &&
        (int32_t)(now - s_reconnect_not_before) < 0) {
        return;
    }

    const tivoo_spp_request_t request = {
        .type = TIVOO_SPP_REQUEST_RECONNECT,
    };
    set_link_state(SPP_LINK_CONNECTING);
    const tivoo_spp_session_result_t result = tivoo_spp_session_process(
        &s_session, &request, &s_session_backend);
    if (result == TIVOO_SPP_SESSION_OK) {
        publish_link_peer(s_session.peer);
        set_link_state(SPP_LINK_CONNECTED);
        s_reconnect_not_before = 0;
        TIVOO_LOGI(
            TAG,
            "spp_reconnected peer=%02X:%02X:%02X:%02X:%02X:%02X",
            s_session.peer[0], s_session.peer[1], s_session.peer[2],
            s_session.peer[3], s_session.peer[4], s_session.peer[5]);
        return;
    }
    set_link_state(SPP_LINK_DISCONNECTED);
    s_reconnect_not_before =
        xTaskGetTickCount() + pdMS_TO_TICKS(SPP_RECONNECT_RETRY_MS);
    TIVOO_LOGW(TAG, "spp_reconnect_failed retry_ms=%u", SPP_RECONNECT_RETRY_MS);
}

static void process_request(spp_request_t *queued)
{
    if (queued->type == REQUEST_CONNECT) {
        const bool already_connected = s_session.peer_valid &&
            s_session.connected && same_address(queued->peer, s_session.peer);
        if (already_connected) {
            TIVOO_LOGI(
                TAG,
                "spp_connect_duplicate_ignored peer=%02X:%02X:%02X:%02X:%02X:%02X",
                queued->peer[0], queued->peer[1], queued->peer[2],
                queued->peer[3], queued->peer[4], queued->peer[5]);
        } else {
            publish_link_peer(queued->peer);
            set_link_state(SPP_LINK_CONNECTING);
        }
        xEventGroupSetBits(s_events, EVENT_AUTO_RECONNECT);
        s_reconnect_not_before = 0;
    } else if (queued->type == REQUEST_DISCONNECT && s_session.peer_valid &&
               same_address(queued->peer, s_session.peer)) {
        xEventGroupClearBits(s_events, EVENT_AUTO_RECONNECT);
        s_reconnect_not_before = 0;
    }

    tivoo_spp_request_t request = {0};
    request.type = (tivoo_spp_request_type_t)queued->type;
    memcpy(request.peer, queued->peer, sizeof(request.peer));
    request.frame = queued->data;
    request.frame_size = queued->size;

    const tivoo_spp_session_result_t result = tivoo_spp_session_process(
        &s_session, &request, &s_session_backend);
    switch (result) {
    case TIVOO_SPP_SESSION_OK:
        if (queued->type == REQUEST_CONNECT) {
            publish_link_peer(s_session.peer);
            set_link_state(SPP_LINK_CONNECTED);
        } else if (queued->type == REQUEST_DISCONNECT) {
            atomic_store(&s_disconnect_pending, false);
            if (!s_session.peer_valid) {
                clear_link_peer();
            }
            set_link_state(s_session.connected ? SPP_LINK_CONNECTED : SPP_LINK_DISCONNECTED);
        }
        break;
    case TIVOO_SPP_SESSION_CONNECT_FAILED:
        set_link_state(SPP_LINK_DISCONNECTED);
        if ((xEventGroupGetBits(s_events) & EVENT_AUTO_RECONNECT) != 0) {
            s_reconnect_not_before =
                xTaskGetTickCount() + pdMS_TO_TICKS(SPP_RECONNECT_RETRY_MS);
        }
        report_spp_error("spp_connect_failed", "spp_open_or_authentication_failed");
        break;
    case TIVOO_SPP_SESSION_DISCONNECT_FAILED:
        atomic_store(&s_disconnect_pending, false);
        if (s_handle != 0U) {
            atomic_store(&s_link_state, SPP_LINK_CONNECTED);
        } else {
            set_link_state(SPP_LINK_DISCONNECTED);
        }
        report_spp_error("spp_disconnect_failed", "spp_close_event_not_received");
        break;
    case TIVOO_SPP_SESSION_NOT_CONNECTED:
        set_link_state(SPP_LINK_DISCONNECTED);
        report_spp_error(
            "spp_not_connected", "tivoo_frame_received_without_authenticated_peer");
        break;
    case TIVOO_SPP_SESSION_WRITE_FAILED:
        set_link_state(SPP_LINK_DISCONNECTED);
        report_spp_error("spp_write_failed", "spp_chunk_write_or_completion_failed");
        break;
    case TIVOO_SPP_SESSION_INVALID_REQUEST:
    default:
        report_spp_error("tivoo_frame_malformed", "invalid_spp_worker_request");
        break;
    }
}

static void spp_worker(void *context)
{
    (void)context;
    for (;;) {
        spp_request_t *request = NULL;
        const BaseType_t received = xQueueReceive(
            s_request_queue, &request, pdMS_TO_TICKS(SPP_WORKER_POLL_MS));
        if (received == pdTRUE && request != NULL) {
            process_request(request);
            free(request);
        }
        service_spp_reconnect();
    }
}

static bool queue_request(
    request_type_t type, const uint8_t peer[6],
    const uint8_t *data, size_t size)
{
    if (s_request_queue == NULL ||
        (size > 0 && data == NULL) ||
        size > TIVOO_FRAME_BUFFER_SIZE) {
        return false;
    }

    spp_request_t *request = malloc(sizeof(*request) + size);
    if (request == NULL) {
        return false;
    }
    request->type = type;
    request->size = size;
    if (peer != NULL) {
        memcpy(request->peer, peer, sizeof(request->peer));
    } else {
        memset(request->peer, 0, sizeof(request->peer));
    }
    if (size > 0) {
        memcpy(request->data, data, size);
    }

    if (xQueueSend(
            s_request_queue, &request,
            pdMS_TO_TICKS(SPP_QUEUE_WRITE_TIMEOUT_MS)) != pdTRUE) {
        free(request);
        return false;
    }
    return true;
}

bool tivoo_spp_queue_connect(const uint8_t peer[6])
{
    if (peer == NULL) {
        return false;
    }
    const bool already_connected =
        atomic_load(&s_link_state) == SPP_LINK_CONNECTED &&
        link_peer_matches(peer);
    if (!already_connected) {
        atomic_store(&s_disconnect_pending, false);
    }
    return queue_request(REQUEST_CONNECT, peer, NULL, 0);
}

bool tivoo_spp_queue_disconnect(const uint8_t peer[6])
{
    if (peer == NULL) {
        return false;
    }
    const bool target_match = link_peer_matches(peer);
    if (target_match) {
        /* Block new writes while keeping the reported link state physical. */
        atomic_store(&s_disconnect_pending, true);
    }
    if (!queue_request(REQUEST_DISCONNECT, peer, NULL, 0)) {
        if (target_match) {
            atomic_store(&s_disconnect_pending, false);
        }
        return false;
    }
    return true;
}

tivoo_spp_queue_result_t tivoo_spp_queue_frame(
    const uint8_t *frame, size_t size)
{
    if (frame == NULL || size < 6 ||
        size > TIVOO_FRAME_BUFFER_SIZE ||
        frame[0] != 0x01 || frame[size - 1] != 0x02) {
        return TIVOO_SPP_QUEUE_FULL;
    }

    if (atomic_load(&s_disconnect_pending)) {
        return TIVOO_SPP_QUEUE_DISCONNECTED;
    }
    const int state = atomic_load(&s_link_state);
    if (state == SPP_LINK_CONNECTING) {
        return TIVOO_SPP_QUEUE_CONNECTING;
    }
    if (state != SPP_LINK_CONNECTED) {
        return TIVOO_SPP_QUEUE_DISCONNECTED;
    }
    return queue_request(REQUEST_FRAME, NULL, frame, size)
        ? TIVOO_SPP_QUEUE_QUEUED : TIVOO_SPP_QUEUE_FULL;
}

esp_err_t tivoo_spp_start(void)
{
    s_request_queue = xQueueCreate(SPP_TX_QUEUE_SIZE, sizeof(spp_request_t *));
    s_events = xEventGroupCreate();
    if (s_request_queue == NULL || s_events == NULL) {
        return ESP_ERR_NO_MEM;
    }

    esp_bt_controller_config_t controller_config = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    controller_config.mode = ESP_BT_MODE_CLASSIC_BT;
    esp_err_t err;
    if (esp_bt_controller_get_status() == ESP_BT_CONTROLLER_STATUS_IDLE) {
        err = esp_bt_controller_init(&controller_config);
        if (err != ESP_OK) {
            return err;
        }
    }
    if (esp_bt_controller_get_status() == ESP_BT_CONTROLLER_STATUS_INITED) {
        err = esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT);
        if (err != ESP_OK) {
            return err;
        }
    }

    if (esp_bluedroid_get_status() == ESP_BLUEDROID_STATUS_UNINITIALIZED) {
        err = esp_bluedroid_init();
        if (err != ESP_OK) {
            return err;
        }
    }
    if (esp_bluedroid_get_status() != ESP_BLUEDROID_STATUS_ENABLED) {
        err = esp_bluedroid_enable();
        if (err != ESP_OK) {
            return err;
        }
    }

    const uint8_t empty_target[6] = {0};
    if (!tivoo_gap_security_init(&s_gap_security, empty_target, &s_gap_callbacks)) {
        return ESP_FAIL;
    }

    err = esp_bt_gap_register_callback(gap_event_handler);
    if (err != ESP_OK) {
        return err;
    }
    esp_bt_pin_code_t empty_pin = {0};
    err = esp_bt_gap_set_pin(ESP_BT_PIN_TYPE_VARIABLE, 0, empty_pin);
    if (err != ESP_OK) {
        return err;
    }

    err = esp_spp_register_callback(spp_event_handler);
    if (err != ESP_OK) {
        return err;
    }

    if (xTaskCreate(
            spp_worker, "tivoo_spp", 4096, NULL,
            configMAX_PRIORITIES - 2, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    const esp_spp_cfg_t spp_config = {
        .mode = ESP_SPP_MODE_CB,
        .enable_l2cap_ertm = false,
        .tx_buffer_size = 0,
    };
    err = esp_spp_enhanced_init(&spp_config);
    if (err != ESP_OK) {
        return err;
    }

    EventBits_t bits = xEventGroupWaitBits(
        s_events, EVENT_SPP_READY | EVENT_SPP_INIT_FAILED,
        pdFALSE, pdFALSE, pdMS_TO_TICKS(SPP_READY_TIMEOUT_MS));
    if ((bits & EVENT_SPP_READY) == 0) {
        return ESP_FAIL;
    }

    TIVOO_LOGI(TAG, "classic_spp_initiator_ready");
    return ESP_OK;
}
