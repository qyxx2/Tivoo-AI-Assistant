#pragma once
#include "driver/gpio.h"
#include "esp_err.h"
esp_err_t tivoo_board_rgb_off(gpio_num_t pin);
void tivoo_board_memory_report(void);
