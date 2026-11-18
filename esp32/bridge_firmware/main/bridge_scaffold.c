/* Local UART0 logging; bounded error/status notifications to UART1 transport. */
#include <stdarg.h>
#include "control_bridge.h"
#include "device_status.h"
#include "diagnostics.h"
#include "uart_transport.h"

void tivoo_log_write(esp_log_level_t level, const char *module, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    esp_log_writev(level, module, format, args);
    va_end(args);
    esp_log_write(level, module, "\n");
}
void tivoo_report_error(const char *code, const char *module, const char *message)
{
    ESP_LOGE(module, "%s: %s", code, message);
    tivoo_uart_bridge_error(code);
}
bool tivoo_device_status_report_event(const char *event, const uint8_t peer[6])
{
    (void)peer;
    ESP_LOGI("tivoo_bridge", "%s", event);
    tivoo_uart_bridge_status_changed();
    return true;
}
