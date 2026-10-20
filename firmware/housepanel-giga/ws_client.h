#pragma once
#include <ArduinoHttpClient.h>
#include <WiFi.h>
#include "command_parser.h"

void ws_init();
bool ws_connect();
bool ws_connected();
void ws_force_reconnect();
void ws_send_hello(bool post_ota);
void ws_loop();
void ws_send_memory();

extern CommandFrame g_last_frame;
extern bool g_frame_ready;
