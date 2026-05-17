#pragma once
#include <Arduino.h>

enum class CommandType {
    DOORBELL,
    TICKER_APPEND,
    WEATHER_UPDATE,
    CALENDAR_UPDATE,
    OTA_PAUSE,
    OTA_RESUME,
    UNKNOWN
};

struct DoorbellData   { int timeout_seconds; };
struct TickerData     { char text[256]; int ttl_seconds; };
struct WeatherData    { float temperature_c; char conditions[64]; float humidity_pct; float wind_speed_ms; };
struct CalendarData   { char events_json[2048]; };

struct CommandFrame {
    CommandType type;
    char message_id[37];
    union {
        DoorbellData  doorbell;
        TickerData    ticker;
        WeatherData   weather;
        CalendarData  calendar;
    };
};

CommandType command_type_from_string(const char* cmd);
bool parse_command_frame(const String& raw_json, CommandFrame& out);
void format_calendar_events(const char* events_json, char* out_buf, size_t buf_size);
