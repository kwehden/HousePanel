#pragma once
#include <WebSocketClient.h>
#include <WiFi.h>
#include "command_parser.h"
#include "memory_telemetry.h"
#include "checked_wifi_client.h"

// This macro changes WebSocketClient's layout. Set it globally for all sketch
// AND library translation units, never by a sketch-only #define.
static_assert(WS_TX_BUFFER_SIZE >= MEMORY_FRAME_CAPACITY,
              "Build all firmware/library sources with -DWS_TX_BUFFER_SIZE=768");

void ws_init();
bool ws_connect();
bool ws_connected();
void ws_force_reconnect();
void ws_send_hello(bool post_ota);
void ws_loop();
void ws_send_memory();
bool ws_send_text(WebSocketClient& socket, CheckedWiFiClient& network, const char* buffer, size_t length);

extern CommandFrame g_last_frame;
extern bool g_frame_ready;
