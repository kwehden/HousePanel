#include "command_parser.h"
#include <ArduinoJson.h>
#include <string.h>

bool parse_command_frame(const char* raw_json, CommandFrame& out) {
    JsonDocument doc;
    if (deserializeJson(doc, raw_json) != DeserializationError::Ok) return false;

    const char* cmd = doc["cmd"] | "";
    if (!cmd || !*cmd) return false;

    if (strcmp(cmd, "DOORBELL") == 0) {
        out.type = CommandType::DOORBELL;
        out.doorbell.timeout_seconds = doc["timeout_seconds"] | 30;
        return true;
    }

    if (strcmp(cmd, "TICKER-APPEND") == 0) {
        out.type = CommandType::TICKER_APPEND;
        strncpy(out.ticker.text, doc["text"] | "", sizeof(out.ticker.text) - 1);
        out.ticker.text[sizeof(out.ticker.text) - 1] = '\0';
        return true;
    }

    if (strcmp(cmd, "WEATHER") == 0) {
        out.type = CommandType::WEATHER;
        out.weather.temp_c = doc["t"] | 0.0f;
        out.weather.high_c = doc["h"] | out.weather.temp_c;
        out.weather.low_c  = doc["l"] | out.weather.temp_c;
        strncpy(out.weather.conditions, doc["co"] | "", sizeof(out.weather.conditions) - 1);
        out.weather.conditions[sizeof(out.weather.conditions) - 1] = '\0';
        return true;
    }

    if (strcmp(cmd, "WEATHER_DAY") == 0) {
        out.type = CommandType::WEATHER_DAY;
        out.weather_day.idx   = doc["i"] | 0;
        out.weather_day.high_c = doc["h"] | 0.0f;
        out.weather_day.low_c  = doc["lo"] | 0.0f;
        strncpy(out.weather_day.label, doc["l"] | "", sizeof(out.weather_day.label) - 1);
        out.weather_day.label[sizeof(out.weather_day.label) - 1] = '\0';
        strncpy(out.weather_day.conditions, doc["c"] | "", sizeof(out.weather_day.conditions) - 1);
        out.weather_day.conditions[sizeof(out.weather_day.conditions) - 1] = '\0';
        return true;
    }

    if (strcmp(cmd, "CAL_EVENT") == 0) {
        out.type = CommandType::CAL_EVENT;
        out.cal_event.idx     = doc["i"] | 0;
        out.cal_event.all_day = doc["a"] | false;
        strncpy(out.cal_event.summary,  doc["s"] | "", sizeof(out.cal_event.summary) - 1);
        out.cal_event.summary[sizeof(out.cal_event.summary) - 1] = '\0';
        strncpy(out.cal_event.time_str, doc["t"] | "", sizeof(out.cal_event.time_str) - 1);
        out.cal_event.time_str[sizeof(out.cal_event.time_str) - 1] = '\0';
        return true;
    }

    if (strcmp(cmd, "TIME") == 0) {
        out.type = CommandType::TIME_SYNC;
        out.time_sync.epoch          = (uint32_t)(doc["epoch"] | 0);
        out.time_sync.utc_offset_min = (int16_t)(doc["utc_offset_min"] | -480);
        return true;
    }

    if (strcmp(cmd, "SYSMON_TEMP") == 0) {
        out.type = CommandType::SYSMON_TEMP;
        out.sysmon.temp_c = doc["t"] | 0.0f;
        out.sysmon.count  = 0;
        const char* h_str = doc["h"] | "";
        if (h_str && *h_str) {
            char buf[128];
            strncpy(buf, h_str, sizeof(buf) - 1);
            buf[sizeof(buf) - 1] = '\0';
            char* tok = strtok(buf, ",");
            while (tok && out.sysmon.count < 20) {
                out.sysmon.history[out.sysmon.count++] = (int16_t)atoi(tok);
                tok = strtok(nullptr, ",");
            }
        }
        return true;
    }

    if (strcmp(cmd, "OTA-PAUSE") == 0)  { out.type = CommandType::OTA_PAUSE;  return true; }
    if (strcmp(cmd, "OTA-RESUME") == 0) { out.type = CommandType::OTA_RESUME; return true; }

    out.type = CommandType::UNKNOWN;
    return false;
}
