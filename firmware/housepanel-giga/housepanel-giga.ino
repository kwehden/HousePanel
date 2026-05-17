#include "config.h"
#include "display.h"
#include "wifi_manager.h"
#include "ws_client.h"
#include "command_parser.h"

static unsigned long _doorbell_start_ms = 0;
static unsigned long _doorbell_timeout_ms = 0;
static unsigned long _last_data_rx_ms = 0;
static unsigned long _last_indicator_ms = 0;

void setup() {
    Serial.begin(115200);
    delay(1000);
    display_init();
    wifi_connect(display_service);
    ws_init();
    if (ws_connect()) {
        ws_send_hello(false);
    }
}

static unsigned long _loop_count = 0;

void loop() {
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
            case CommandType::WEATHER_UPDATE:
                Serial.print("WEATHER: ");
                Serial.println(g_last_frame.weather.temperature_c);
                render_weather_section(g_last_frame.weather);
                _last_data_rx_ms = millis();
                break;
            case CommandType::CALENDAR_UPDATE: {
                Serial.println("CALENDAR: start");
                Serial.print("CALENDAR: events_json len=");
                Serial.println(strlen(g_last_frame.calendar.events_json));
                Serial.print("CALENDAR: events_json prefix=");
                Serial.println(String(g_last_frame.calendar.events_json).substring(0, 80));
                char cal_text[512];
                Serial.println("CALENDAR: calling format_calendar_events");
                format_calendar_events(g_last_frame.calendar.events_json, cal_text, sizeof(cal_text));
                Serial.print("CALENDAR: result=");
                Serial.println(cal_text);
                render_calendar_section(cal_text);
                _last_data_rx_ms = millis();
                Serial.println("CALENDAR: done");
                break;
            }
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
        bool data_ok = (_last_data_rx_ms > 0) && ((millis() - _last_data_rx_ms) < 90000UL);
        display_update_indicators(wifi_status_ok(), ws_connected(), data_ok);
    }
    display_service();
    delay(5);
}
