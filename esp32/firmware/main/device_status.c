#include "device_status.h"

#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "diagnostics.h"
#include "network_listeners.h"
#include "tivoo_spp.h"
#include "wifi_station.h"

#ifdef ESP_PLATFORM
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
static portMUX_TYPE s_audio_resource_mux = portMUX_INITIALIZER_UNLOCKED;
#define AUDIO_RESOURCE_LOCK() portENTER_CRITICAL(&s_audio_resource_mux)
#define AUDIO_RESOURCE_UNLOCK() portEXIT_CRITICAL(&s_audio_resource_mux)
#else
#include <time.h>
#define AUDIO_RESOURCE_LOCK() ((void)0)
#define AUDIO_RESOURCE_UNLOCK() ((void)0)
#endif

#ifndef TIVOO_FIRMWARE_VERSION
#define TIVOO_FIRMWARE_VERSION "0.1.0+unknown"
#endif

#define TYPE_PING 0x03U
#define TYPE_PONG 0x04U
#define TYPE_GET_STATUS 0x10U
#define TYPE_DEVICE_STATUS 0x11U
#define TYPE_DEVICE_EVENT 0x40U
#define AUDIO_PLAYBACK_ID_MAX 64U

static bool s_audio_resource_fetching;
static char s_audio_resource_playback_id[AUDIO_PLAYBACK_ID_MAX + 1U];

bool tivoo_device_status_set_audio_resource(bool fetching, const char *playback_id)
{
    if (fetching && (playback_id == NULL || playback_id[0] == '\0' ||
                     strlen(playback_id) > AUDIO_PLAYBACK_ID_MAX)) {
        return false;
    }

    AUDIO_RESOURCE_LOCK();
    s_audio_resource_fetching = fetching;
    if (fetching) {
        (void)snprintf(
            s_audio_resource_playback_id,
            sizeof(s_audio_resource_playback_id), "%s", playback_id);
    } else {
        s_audio_resource_playback_id[0] = '\0';
    }
    AUDIO_RESOURCE_UNLOCK();
    return true;
}

static void get_audio_resource_status(bool *fetching, char playback_id[AUDIO_PLAYBACK_ID_MAX + 1U])
{
    AUDIO_RESOURCE_LOCK();
    *fetching = s_audio_resource_fetching;
    (void)snprintf(
        playback_id, AUDIO_PLAYBACK_ID_MAX + 1U, "%s",
        s_audio_resource_playback_id);
    AUDIO_RESOURCE_UNLOCK();
}

static uint64_t device_uptime_ms(void)
{
#ifdef ESP_PLATFORM
    return (uint64_t)(esp_timer_get_time() / 1000);
#else
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return 0U;
    }
    return (uint64_t)now.tv_sec * 1000U + (uint64_t)now.tv_nsec / 1000000U;
#endif
}

static bool valid_event(const char *event)
{
    static const char *const allowed[] = {
        "wifi_connected",
        "wifi_disconnected",
        "spp_connecting",
        "spp_connected",
        "spp_disconnected",
    };
    if (event == NULL) {
        return false;
    }
    for (size_t i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++) {
        if (strcmp(event, allowed[i]) == 0) {
            return true;
        }
    }
    return false;
}

static void add_spp_state(cJSON *root)
{
    static const char *const states[] = {
        "disconnected", "connecting", "connected"
    };
    tivoo_spp_link_state_t state = TIVOO_SPP_LINK_DISCONNECTED;
    uint8_t peer[6] = {0};
    bool peer_valid = false;
    tivoo_spp_get_status(&state, peer, &peer_valid);

    cJSON *spp = cJSON_AddObjectToObject(root, "spp");
    if (spp == NULL) {
        return;
    }
    if (state < TIVOO_SPP_LINK_DISCONNECTED ||
        state > TIVOO_SPP_LINK_CONNECTED) {
        state = TIVOO_SPP_LINK_DISCONNECTED;
    }
    cJSON_AddStringToObject(spp, "state", states[state]);
    if (peer_valid) {
        char mac[18];
        (void)snprintf(
            mac, sizeof(mac), "%02X:%02X:%02X:%02X:%02X:%02X",
            peer[0], peer[1], peer[2], peer[3], peer[4], peer[5]);
        cJSON_AddStringToObject(spp, "mac", mac);
    }
}

static bool send_device_status(const char *request_id)
{
    tivoo_wifi_status_t wifi = {0};
    if (!tivoo_wifi_station_get_status(&wifi)) {
        return false;
    }

    bool control_connected = false;
    bool diagnostic_connected = false;
    network_listeners_get_client_status(
        &control_connected, &diagnostic_connected);

    cJSON *root = cJSON_CreateObject();
    if (root == NULL) {
        return false;
    }
    cJSON_AddStringToObject(root, "request_id", request_id);
    cJSON_AddStringToObject(root, "device_id", "tivoo-esp32");
    cJSON_AddStringToObject(root, "firmware_version", TIVOO_FIRMWARE_VERSION);
    cJSON_AddNumberToObject(root, "uptime_ms", (double)device_uptime_ms());

    cJSON *wifi_json = cJSON_AddObjectToObject(root, "wifi");
    if (wifi_json != NULL) {
        cJSON_AddStringToObject(
            wifi_json, "state", wifi.connected ? "connected" : "disconnected");
        if (wifi.ip_available && wifi.ip[0] != '\0') {
            cJSON_AddStringToObject(wifi_json, "ip", wifi.ip);
        }
        if (wifi.rssi_available) {
            cJSON_AddNumberToObject(wifi_json, "rssi_dbm", wifi.rssi_dbm);
        }
    }

    cJSON *tcp = cJSON_AddObjectToObject(root, "tcp");
    if (tcp != NULL) {
        cJSON_AddStringToObject(
            tcp, "7777", control_connected ? "connected" : "disconnected");
        cJSON_AddStringToObject(
            tcp, "7778", diagnostic_connected ? "connected" : "disconnected");
    }
    add_spp_state(root);

    bool audio_fetching = false;
    char playback_id[AUDIO_PLAYBACK_ID_MAX + 1U] = {0};
    get_audio_resource_status(&audio_fetching, playback_id);
    cJSON *audio = cJSON_AddObjectToObject(root, "audio_resource");
    if (audio != NULL) {
        cJSON_AddStringToObject(
            audio, "state", audio_fetching ? "fetching" : "idle");
        if (audio_fetching) {
            cJSON_AddStringToObject(audio, "playback_id", playback_id);
        } else {
            cJSON_AddNullToObject(audio, "playback_id");
        }
    }

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (payload == NULL) {
        return false;
    }
    const bool sent = tivoo_diagnostics_send_message(
        TYPE_DEVICE_STATUS, (const uint8_t *)payload, strlen(payload));
    cJSON_free(payload);
    return sent;
}

bool tivoo_device_status_handle_message(
    uint8_t type, const uint8_t *payload, size_t size)
{
    if (type == TYPE_PING) {
        if (size != 0U) {
            tivoo_report_error(
                "protocol_invalid_payload", "device_status", "PING payload must be empty");
            return true;
        }
        return tivoo_diagnostics_send_message(TYPE_PONG, NULL, 0U);
    }

    if (type != TYPE_GET_STATUS) {
        return true;
    }
    if (payload == NULL || size == 0U) {
        tivoo_report_error(
            "protocol_invalid_payload", "device_status", "GET_STATUS requires request_id");
        return true;
    }

    cJSON *request = cJSON_ParseWithLength((const char *)payload, size);
    const cJSON *request_id_item = cJSON_IsObject(request)
        ? cJSON_GetObjectItemCaseSensitive(request, "request_id")
        : NULL;
    const char *request_id = cJSON_IsString(request_id_item)
        ? cJSON_GetStringValue(request_id_item)
        : NULL;
    if (request_id == NULL || request_id[0] == '\0' ||
        strlen(request_id) > 64U) {
        cJSON_Delete(request);
        tivoo_report_error(
            "protocol_invalid_payload", "device_status", "invalid GET_STATUS request_id");
        return true;
    }

    const bool sent = send_device_status(request_id);
    cJSON_Delete(request);
    if (!sent) {
        tivoo_report_error(
            "protocol_invalid_payload", "device_status", "DEVICE_STATUS snapshot unavailable");
    }
    return true;
}

bool tivoo_device_status_report_event(
    const char *event, const uint8_t peer[6])
{
    if (!valid_event(event)) {
        return false;
    }

    cJSON *root = cJSON_CreateObject();
    cJSON *data = cJSON_CreateObject();
    if (root == NULL || data == NULL) {
        cJSON_Delete(root);
        cJSON_Delete(data);
        return false;
    }
    cJSON_AddStringToObject(root, "event", event);
    cJSON_AddNumberToObject(root, "uptime_ms", (double)device_uptime_ms());
    if (peer != NULL) {
        char mac[18];
        (void)snprintf(
            mac, sizeof(mac), "%02X:%02X:%02X:%02X:%02X:%02X",
            peer[0], peer[1], peer[2], peer[3], peer[4], peer[5]);
        cJSON_AddStringToObject(data, "mac", mac);
    }
    cJSON_AddItemToObject(root, "data", data);

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (payload == NULL) {
        return false;
    }
    const bool sent = tivoo_diagnostics_send_message(
        TYPE_DEVICE_EVENT, (const uint8_t *)payload, strlen(payload));
    cJSON_free(payload);
    return sent;
}

bool tivoo_device_status_report_transition(
    const char *event,
    int previous_state,
    int current_state,
    const uint8_t peer[6])
{
    if (previous_state == current_state) {
        return true;
    }
    return tivoo_device_status_report_event(event, peer);
}
