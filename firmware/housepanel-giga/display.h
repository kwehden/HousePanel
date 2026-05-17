#pragma once
#include <Arduino.h>
#include "command_parser.h"

enum class DisplayState { DAILY_VIEW, DOORBELL_INTERRUPT };

void display_init();
void render_daily_view();
void render_weather_section(const WeatherData& weather);
void render_calendar_section(const char* events_text);
void ticker_append(const char* text);
void ticker_advance();
void render_doorbell_interrupt(int timeout_seconds);
void dismiss_doorbell();
DisplayState display_get_state();
void display_service();
// wifi_ok: WiFi associated; ws_ok: WebSocket connected; data_ok: data received in last 90s
void display_update_indicators(bool wifi_ok, bool ws_ok, bool data_ok);
