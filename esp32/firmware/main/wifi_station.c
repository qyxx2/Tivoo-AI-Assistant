#include "wifi_station.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include "diagnostics.h"
#include "device_status.h"
#include "network_listeners.h"

static const char *TAG = "tivoo_wifi";
static esp_netif_t *s_station_netif;
static esp_event_handler_instance_t s_wifi_event_handler;
static esp_event_handler_instance_t s_got_ip_handler;
static esp_event_handler_instance_t s_lost_ip_handler;

static void station_event_handler(
    void *context,
    esp_event_base_t event_base,
    int32_t event_id,
    void *event_data)
{
    (void)context;
    (void)event_data;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_err_t err = esp_wifi_connect();
        if (err != ESP_OK) {
            tivoo_report_error(
                "wifi_connect_failed", TAG, "initial_station_connect_failed");
        }
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        TIVOO_LOGW(TAG, "station_disconnected");
        if (network_listeners_set_ip_available(false)) {
            (void)tivoo_device_status_report_event("wifi_disconnected", NULL);
        }
        esp_err_t err = esp_wifi_connect();
        if (err != ESP_OK) {
            tivoo_report_error(
                "wifi_connect_failed", TAG, "station_reconnect_request_failed");
        }
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        TIVOO_LOGI(TAG, "station_connected");
        if (network_listeners_set_ip_available(true)) {
            (void)tivoo_device_status_report_event("wifi_connected", NULL);
        }
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_LOST_IP) {
        TIVOO_LOGW(TAG, "station_ipv4_lost");
        if (network_listeners_set_ip_available(false)) {
            (void)tivoo_device_status_report_event("wifi_disconnected", NULL);
        }
    }
}

esp_err_t tivoo_wifi_station_init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    return err;
}

esp_err_t tivoo_wifi_station_start(void)
{
    const size_t ssid_length = strlen(CONFIG_TIVOO_WIFI_SSID);
    const size_t password_length = strlen(CONFIG_TIVOO_WIFI_PASSWORD);

    if (ssid_length == 0 || ssid_length > 32 || password_length > 64) {
        tivoo_report_error(
            "wifi_init_failed", TAG,
            "wifi_credentials_missing_or_exceeding_limits");
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = esp_netif_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }

    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }

    s_station_netif = esp_netif_create_default_wifi_sta();
    if (s_station_netif == NULL) {
        return ESP_FAIL;
    }

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&init_config);
    if (err != ESP_OK) {
        return err;
    }

    err = esp_event_handler_instance_register(
        WIFI_EVENT,
        ESP_EVENT_ANY_ID,
        station_event_handler,
        NULL,
        &s_wifi_event_handler);
    if (err != ESP_OK) {
        return err;
    }

    err = esp_event_handler_instance_register(
        IP_EVENT,
        IP_EVENT_STA_GOT_IP,
        station_event_handler,
        NULL,
        &s_got_ip_handler);
    if (err != ESP_OK) {
        return err;
    }

    err = esp_event_handler_instance_register(
        IP_EVENT,
        IP_EVENT_STA_LOST_IP,
        station_event_handler,
        NULL,
        &s_lost_ip_handler);
    if (err != ESP_OK) {
        return err;
    }

    err = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (err != ESP_OK) {
        return err;
    }

    err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err != ESP_OK) {
        return err;
    }

    wifi_config_t wifi_config = {0};
    memcpy(wifi_config.sta.ssid, CONFIG_TIVOO_WIFI_SSID, ssid_length);
    memcpy(wifi_config.sta.password, CONFIG_TIVOO_WIFI_PASSWORD, password_length);

    err = esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    if (err != ESP_OK) {
        return err;
    }

    return esp_wifi_start();
}


bool tivoo_wifi_station_get_status(tivoo_wifi_status_t *status)
{
    if (status == NULL) {
        return false;
    }
    memset(status, 0, sizeof(*status));
    status->connected = network_listeners_get_ip_available();
    if (!status->connected || s_station_netif == NULL) {
        return true;
    }

    esp_netif_ip_info_t ip_info = {0};
    if (esp_netif_get_ip_info(s_station_netif, &ip_info) == ESP_OK &&
        ip_info.ip.addr != 0U &&
        esp_ip4addr_ntoa(&ip_info.ip, status->ip, sizeof(status->ip)) != NULL) {
        status->ip_available = true;
    }

    wifi_ap_record_t ap_info = {0};
    if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
        status->rssi_available = true;
        status->rssi_dbm = ap_info.rssi;
    }
    return true;
}
