#pragma once
#include <ArduinoHttpClient.h>
#include <WiFi.h>
#include "command_parser.h"

void ws_init();
bool ws_connect();
void ws_disconnect();
bool ws_connected();
void ws_send_hello(bool post_ota);
void ws_loop();

extern CommandFrame g_last_frame;
extern bool g_frame_ready;
