/* b1: fail closed until b2 supplies real UART transport and bridge STATUS. */
#include <string.h>
#include "control_bridge.h"
#include "tivoo_spp.h"

void tivoo_spp_get_status(tivoo_spp_link_state_t *state, uint8_t peer[6], bool *peer_valid)
{
    *state = TIVOO_SPP_LINK_DISCONNECTED;
    memset(peer, 0, 6);
    *peer_valid = false;
}
void tivoo_control_client_connected(int fd) { (void)fd; }
void tivoo_control_client_disconnected(int fd) { (void)fd; }
bool tivoo_control_client_data(int fd, const uint8_t *data, size_t size)
{
    (void)fd; (void)data; (void)size;
    return false;
}
bool tivoo_control_client_has_pending(int fd) { (void)fd; return false; }
bool tivoo_control_client_send_pending(int fd) { (void)fd; return false; }
void tivoo_control_report_pending_errors(void) {}
