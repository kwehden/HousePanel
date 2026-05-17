#pragma once
#include <WiFi.h>

void wifi_connect(void (*pump)() = nullptr);
bool wifi_status_ok();
