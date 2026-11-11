#include "wifi_station.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include "network_listeners.h"

static const char *TAG = "tivoo_wifi";
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
            ESP_LOGW(TAG, "Initial Station connect failed (error %d)", (int)err);
        }
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        network_listeners_set_ip_available(false);
        esp_err_t err = esp_wifi_connect();
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "Station reconnect request failed (error %d)", (int)err);
        }
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ESP_LOGI(TAG, "Station acquired IPv4; TCP listeners enabled");
        network_listeners_set_ip_available(true);
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_LOST_IP) {
        ESP_LOGW(TAG, "Station IPv4 lost; TCP listeners disabled");
        network_listeners_set_ip_available(false);
    }
}

static esp_err_t initialize_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES ||
        err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        err = nvs_flash_erase();
        if (err != ESP_OK) {
            return err;
        }
        err = nvs_flash_init();
    }
    return err;
}

esp_err_t tivoo_wifi_station_start(void)
{
    const size_t ssid_length = strlen(CONFIG_TIVOO_WIFI_SSID);
    const size_t password_length = strlen(CONFIG_TIVOO_WIFI_PASSWORD);

    if (ssid_length == 0 || ssid_length > 32 || password_length > 64) {
        ESP_LOGE(TAG, "Wi-Fi credentials are not configured or exceed limits");
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = initialize_nvs();
    if (err != ESP_OK) {
        return err;
    }

    err = esp_netif_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }

    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }

    if (esp_netif_create_default_wifi_sta() == NULL) {
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
