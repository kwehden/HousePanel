#include "command_parser.h"
#include <ArduinoJson.h>
#include <string.h>

CommandType command_type_from_string(const char* cmd) {
    if (!cmd) return CommandType::UNKNOWN;
    if (strcmp(cmd, "DOORBELL")        == 0) return CommandType::DOORBELL;
    if (strcmp(cmd, "TICKER-APPEND")   == 0) return CommandType::TICKER_APPEND;
    if (strcmp(cmd, "WEATHER-UPDATE")  == 0) return CommandType::WEATHER_UPDATE;
    if (strcmp(cmd, "CALENDAR-UPDATE") == 0) return CommandType::CALENDAR_UPDATE;
    if (strcmp(cmd, "OTA-PAUSE")       == 0) return CommandType::OTA_PAUSE;
    if (strcmp(cmd, "OTA-RESUME")      == 0) return CommandType::OTA_RESUME;
    return CommandType::UNKNOWN;
}

bool parse_command_frame(const String& raw_json, CommandFrame& out) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, raw_json);
    if (err) return false;

    const char* cmd = doc["cmd"] | "";
    out.type = command_type_from_string(cmd);

    const char* mid = doc["message_id"] | "";
    strncpy(out.message_id, mid, sizeof(out.message_id) - 1);
    out.message_id[sizeof(out.message_id) - 1] = '\0';

    switch (out.type) {
        case CommandType::DOORBELL:
            out.doorbell.timeout_seconds = doc["timeout_seconds"] | 30;
            break;
        case CommandType::TICKER_APPEND:
            strncpy(out.ticker.text, doc["text"] | "", sizeof(out.ticker.text) - 1);
            out.ticker.text[sizeof(out.ticker.text) - 1] = '\0';
            out.ticker.ttl_seconds = doc["ttl_seconds"] | 60;
            break;
        case CommandType::WEATHER_UPDATE:
            out.weather.temperature_c  = doc["temperature_c"]  | 0.0f;
            out.weather.humidity_pct   = doc["humidity_pct"]   | 0.0f;
            out.weather.wind_speed_ms  = doc["wind_speed_ms"]  | 0.0f;
            out.weather.today_high_c   = doc["today_high_c"]   | out.weather.temperature_c;
            out.weather.today_low_c    = doc["today_low_c"]    | out.weather.temperature_c;
            strncpy(out.weather.conditions, doc["conditions"] | "", sizeof(out.weather.conditions) - 1);
            out.weather.conditions[sizeof(out.weather.conditions) - 1] = '\0';
            {
                JsonArray fc = doc["forecast"].as<JsonArray>();
                int n = 0;
                for (JsonObject day : fc) {
                    if (n >= 4) break;
                    strncpy(out.weather.forecast[n].day_label, day["day_label"] | "", sizeof(ForecastDay::day_label) - 1);
                    out.weather.forecast[n].day_label[sizeof(ForecastDay::day_label) - 1] = '\0';
                    out.weather.forecast[n].high_c = day["high_c"] | 0.0f;
                    out.weather.forecast[n].low_c  = day["low_c"]  | 0.0f;
                    strncpy(out.weather.forecast[n].conditions, day["conditions"] | "", sizeof(ForecastDay::conditions) - 1);
                    out.weather.forecast[n].conditions[sizeof(ForecastDay::conditions) - 1] = '\0';
                    n++;
                }
                // Zero-initialize remaining slots
                for (; n < 4; n++) {
                    out.weather.forecast[n] = ForecastDay{};
                }
            }
            break;
        case CommandType::CALENDAR_UPDATE: {
            String eventsStr;
            serializeJson(doc["events"], eventsStr);
            strncpy(out.calendar.events_json, eventsStr.c_str(), sizeof(out.calendar.events_json) - 1);
            out.calendar.events_json[sizeof(out.calendar.events_json) - 1] = '\0';
            break;
        }
        default:
            break;
    }
    return true;
}

void format_calendar_events(const char* events_json, char* out_buf, size_t buf_size) {
    JsonDocument doc;
    if (deserializeJson(doc, events_json) != DeserializationError::Ok || !doc.is<JsonArray>()) {
        strncpy(out_buf, "No upcoming events", buf_size - 1);
        out_buf[buf_size - 1] = '\0';
        return;
    }
    JsonArray arr = doc.as<JsonArray>();
    if (arr.size() == 0) {
        strncpy(out_buf, "No upcoming events", buf_size - 1);
        out_buf[buf_size - 1] = '\0';
        return;
    }
    int off = 0;
    for (JsonObject ev : arr) {
        bool all_day = ev["all_day"] | false;
        const char* summary = ev["summary"] | "(no title)";
        const char* start   = ev["start"]   | "";
        char line[192];
        if (all_day) {
            snprintf(line, sizeof(line), "All day: %s\n", summary);
        } else {
            const char* t = strchr(start, 'T');
            if (t && strlen(t) >= 6) {
                snprintf(line, sizeof(line), "%.5s  %s\n", t + 1, summary);
            } else {
                snprintf(line, sizeof(line), "%s  %s\n", start, summary);
            }
        }
        int rem = (int)buf_size - off - 1;
        if (rem <= 0) break;
        off += snprintf(out_buf + off, (size_t)rem, "%s", line);
    }
    if (off == 0) {
        strncpy(out_buf, "No upcoming events", buf_size - 1);
        out_buf[buf_size - 1] = '\0';
    }
}
