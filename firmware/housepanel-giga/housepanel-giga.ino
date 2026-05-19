#include "config.h"
#include "display.h"
#include "wifi_manager.h"
#include "ws_client.h"
#include "command_parser.h"
#include <mbed.h>
#include <WiFi.h>

static bool _rtc_synced    = false;
static int  _last_clock_min = -1;

static unsigned long _doorbell_start_ms = 0;
static unsigned long _doorbell_timeout_ms = 0;
static unsigned long _last_data_rx_ms = 0;
static unsigned long _last_indicator_ms = 0;

static char _cal_text[512];
static int  _cal_text_len = 0;

void setup() {
    Serial.begin(115200);
    delay(1000);
    display_init();
    wifi_connect(display_service);
    ws_init();
    if (ws_connect()) {
        ws_send_hello(false);
    }
    // Seed the RTC from NTP
    unsigned long epoch = WiFi.getTime();
    if (epoch > 0) {
        set_time((time_t)epoch);
        _rtc_synced = true;
        Serial.print("RTC set epoch=");
        Serial.println(epoch);
    } else {
        Serial.println("NTP failed, will retry");
    }
    mbed::Watchdog::get_instance().start(8000);
}

static unsigned long _loop_count = 0;

void loop() {
    mbed::Watchdog::get_instance().kick();
    _loop_count++;
    if (_loop_count % 200 == 0) {
        Serial.print("loop #");
        Serial.print(_loop_count);
        Serial.print(" ws_connected=");
        Serial.println(ws_connected());
    }
    if (!wifi_status_ok()) {
        wifi_connect(display_service);
    }
    if (!ws_connected()) {
        if (ws_connect()) {
            ws_send_hello(false);
        }
    }
    ws_loop();
    if (g_frame_ready) {
        g_frame_ready = false;
        switch (g_last_frame.type) {
            case CommandType::DOORBELL:
                Serial.println("DOORBELL received");
                render_doorbell_interrupt(g_last_frame.doorbell.timeout_seconds);
                _doorbell_start_ms = millis();
                _doorbell_timeout_ms = (unsigned long)g_last_frame.doorbell.timeout_seconds * 1000UL;
                break;
            case CommandType::TICKER_APPEND:
                Serial.print("TICKER: ");
                Serial.println(g_last_frame.ticker.text);
                if (display_get_state() == DisplayState::DAILY_VIEW) {
                    ticker_append(g_last_frame.ticker.text);
                }
                break;
            case CommandType::WEATHER:
                Serial.print("WEATHER: t=");
                Serial.print(g_last_frame.weather.temp_c);
                Serial.print(" co=");
                Serial.println(g_last_frame.weather.conditions);
                render_weather_today(g_last_frame.weather.temp_c, g_last_frame.weather.conditions,
                                     g_last_frame.weather.high_c, g_last_frame.weather.low_c);
                _last_data_rx_ms = millis();
                break;
            case CommandType::WEATHER_DAY:
                Serial.print("WEATHER_DAY: i=");
                Serial.print(g_last_frame.weather_day.idx);
                Serial.print(" l=");
                Serial.println(g_last_frame.weather_day.label);
                render_weather_day(g_last_frame.weather_day.idx, g_last_frame.weather_day.label,
                                   g_last_frame.weather_day.high_c, g_last_frame.weather_day.low_c,
                                   g_last_frame.weather_day.conditions);
                _last_data_rx_ms = millis();
                break;
            case CommandType::CAL_EVENT: {
                int idx = g_last_frame.cal_event.idx;
                Serial.print("CAL_EVENT: i=");
                Serial.print(idx);
                Serial.print(" s=");
                Serial.println(g_last_frame.cal_event.summary);
                if (idx == 0) {
                    _cal_text_len = 0;
                    memset(_cal_text, 0, sizeof(_cal_text));
                }
                char line[128];
                if (g_last_frame.cal_event.all_day) {
                    // time_str is "YYYY-MM-DD"; show as "MM/DD  summary"
                    const char* d = g_last_frame.cal_event.time_str;
                    char date_mmdd[6] = "?";
                    if (strlen(d) >= 10) snprintf(date_mmdd, sizeof(date_mmdd), "%.2s/%.2s", d+5, d+8);
                    snprintf(line, sizeof(line), "%s  %s\n", date_mmdd, g_last_frame.cal_event.summary);
                } else {
                    snprintf(line, sizeof(line), "%s  %s\n",
                             g_last_frame.cal_event.time_str, g_last_frame.cal_event.summary);
                }
                int rem = (int)sizeof(_cal_text) - _cal_text_len - 1;
                if (rem > 0) {
                    strncat(_cal_text + _cal_text_len, line, rem);
                    _cal_text_len += strlen(line);
                }
                render_calendar_section(_cal_text);
                _last_data_rx_ms = millis();
                break;
            }
            case CommandType::TIME_SYNC:
                if (g_last_frame.time_sync.epoch > 0) {
                    set_time((time_t)g_last_frame.time_sync.epoch);
                    _rtc_synced = true;
                    Serial.print("RTC synced from server epoch=");
                    Serial.println(g_last_frame.time_sync.epoch);
                }
                break;
            case CommandType::OTA_PAUSE:
                Serial.println("OTA_PAUSE received");
                break;
            default:
                break;
        }
    }
    if (display_get_state() == DisplayState::DOORBELL_INTERRUPT &&
        _doorbell_timeout_ms > 0 && (millis() - _doorbell_start_ms) >= _doorbell_timeout_ms) {
        dismiss_doorbell();
        _doorbell_timeout_ms = 0;
    }
    if ((millis() - _last_indicator_ms) >= 1000) {
        _last_indicator_ms = millis();
        bool wifi_ok = wifi_status_ok();
        bool ws_ok   = ws_connected();
        bool data_ok = (_last_data_rx_ms > 0) && ((millis() - _last_data_rx_ms) < 90000UL);
        uint32_t data_age_s = (_last_data_rx_ms > 0)
                              ? (uint32_t)((millis() - _last_data_rx_ms) / 1000)
                              : 0;
        display_update_indicators(wifi_ok, ws_ok, data_ok);
        IPAddress lip = WiFi.localIP();
        char ip_buf[20];
        snprintf(ip_buf, sizeof(ip_buf), "%d.%d.%d.%d", lip[0], lip[1], lip[2], lip[3]);
        display_update_status_detail(wifi_ok, ip_buf, ws_ok, data_ok, data_age_s);

        // Update clock from RTC
        if (!_rtc_synced) {
            unsigned long epoch = WiFi.getTime();
            if (epoch > 0) { set_time((time_t)epoch); _rtc_synced = true; }
        }
        if (_rtc_synced) {
            time_t now = time(nullptr);
            struct tm* utc = gmtime(&now);
            int month = utc->tm_mon + 1;
            int offset = (month >= 3 && month <= 10) ? -7 : -8;
            now += (time_t)(offset * 3600);
            struct tm* local = gmtime(&now);
            int cm = local->tm_min;
            if (cm != _last_clock_min) {
                _last_clock_min = cm;
                display_update_clock(local->tm_hour, cm);
            }
        }
    }
    display_service();
    delay(5);
}
