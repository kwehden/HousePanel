#pragma once
#include <Arduino.h>

enum class CommandType {
    DOORBELL,
    TICKER_APPEND,
    WEATHER,        // current: temp, conditions, H, L
    WEATHER_DAY,    // one forecast day: idx, label, H, L, conditions
    CAL_EVENT,      // one calendar event: idx, summary, time, all_day
    TIME_SYNC,      // server-pushed UTC epoch
    OTA_PAUSE,
    OTA_RESUME,
    UNKNOWN
};

struct DoorbellData { int timeout_seconds; };
struct TimeSyncData { uint32_t epoch; int16_t utc_offset_min; };
struct TickerData   { char text[128]; };

struct WeatherData {
    float temp_c;
    char  conditions[32];
    float high_c;
    float low_c;
};

struct WeatherDayData {
    int  idx;           // 0-3
    char label[4];      // "Mon", etc.
    float high_c;
    float low_c;
    char conditions[26];
};

struct CalEventData {
    int  idx;           // 0-7; idx==0 clears the event buffer
    char summary[52];
    char time_str[18];  // "09:00" or "2026-05-17"
    bool all_day;
};

struct CommandFrame {
    CommandType type;
    union {
        DoorbellData   doorbell;
        TickerData     ticker;
        WeatherData    weather;
        WeatherDayData weather_day;
        CalEventData   cal_event;
        TimeSyncData   time_sync;
    };
};

bool parse_command_frame(const char* raw_json, CommandFrame& out);
