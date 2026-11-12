#include "device_status_host_stub.h"

#include <stdio.h>
#include <string.h>

static tivoo_wifi_status_t s_wifi_status;
static tivoo_spp_link_state_t s_spp_state = TIVOO_SPP_LINK_DISCONNECTED;
static uint8_t s_spp_peer[6];
static bool s_spp_peer_valid;

void p6_host_set_wifi(bool connected, const char *ip, int rssi)
{
    memset(&s_wifi_status, 0, sizeof(s_wifi_status));
    s_wifi_status.connected = connected;
    if (connected && ip != NULL && ip[0] != '\0') {
        (void)snprintf(s_wifi_status.ip, sizeof(s_wifi_status.ip), "%s", ip);
        s_wifi_status.ip_available = true;
        s_wifi_status.rssi_available = true;
        s_wifi_status.rssi_dbm = rssi;
    }
}

void p6_host_set_spp(tivoo_spp_link_state_t state, const uint8_t peer[6])
{
    s_spp_state = state;
    s_spp_peer_valid = peer != NULL;
    if (peer != NULL) {
        memcpy(s_spp_peer, peer, sizeof(s_spp_peer));
    } else {
        memset(s_spp_peer, 0, sizeof(s_spp_peer));
    }
}

bool tivoo_wifi_station_get_status(tivoo_wifi_status_t *status)
{
    if (status == NULL) {
        return false;
    }
    *status = s_wifi_status;
    return true;
}

void tivoo_spp_get_status(
    tivoo_spp_link_state_t *state, uint8_t peer[6], bool *peer_valid)
{
    if (state != NULL) {
        *state = s_spp_state;
    }
    if (peer_valid != NULL) {
        *peer_valid = s_spp_peer_valid;
    }
    if (peer != NULL) {
        memcpy(peer, s_spp_peer, sizeof(s_spp_peer));
    }
}
