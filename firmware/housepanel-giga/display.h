#pragma once
#include <Arduino.h>

enum class DisplayState { DAILY_VIEW, DOORBELL_INTERRUPT };

void display_init();
void render_weather_today(float temp_c, const char* conditions, float high_c, float low_c);
void render_weather_day(int idx, const char* label, float high_c, float low_c, const char* conditions);
void render_calendar_section(const char* events_text);
void ticker_append(const char* text);
void ticker_advance();
void render_doorbell_interrupt(int timeout_seconds);
void dismiss_doorbell();
DisplayState display_get_state();
void display_service();
void display_update_indicators(bool wifi_ok, bool ws_ok, bool data_ok);
void display_update_status_detail(bool wifi_ok, const char* ip_str,
                                   bool ws_ok, bool data_ok,
                                   uint32_t data_age_s);
