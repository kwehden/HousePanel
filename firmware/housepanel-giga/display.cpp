#include "display.h"
#include "Arduino_H7_Video.h"
#include "lvgl.h"
#include <string.h>
#include <stdio.h>

// Display object — must be at file scope
Arduino_H7_Video Display(800, 480, GigaDisplayShield);

static DisplayState _state = DisplayState::DAILY_VIEW;

// --- Daily view screen and widgets ---
static lv_obj_t* _scr_daily    = nullptr;
static lv_obj_t* _lbl_weather  = nullptr;
static lv_obj_t* _lbl_calendar = nullptr;
static lv_obj_t* _lbl_ticker   = nullptr;

// Ticker ring buffer
static const int TICKER_BUF_COUNT = 8;
static char _ticker_buf[TICKER_BUF_COUNT][128];
static int  _ticker_head = 0;
static int  _ticker_count = 0;
static char _ticker_combined[1024];

// Indicator dots (top-right of weather panel): WiFi, WS, Data
static lv_obj_t* _ind_wifi = nullptr;
static lv_obj_t* _ind_ws   = nullptr;
static lv_obj_t* _ind_data = nullptr;

// --- Doorbell screen and widgets ---
static lv_obj_t* _scr_doorbell = nullptr;
static lv_obj_t* _lbl_doorbell = nullptr;

// Only lv_font_montserrat_14 is enabled in lv_conf_9.h; all labels use the default font.

void display_init() {
    if (Display.begin()) {
        // Display init failed — blink LED indefinitely
        while (true) { delay(500); }
    }

    // --- Build daily view screen ---
    _scr_daily = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(_scr_daily, lv_color_hex(0x1A1A2E), LV_PART_MAIN);

    // Weather section — top 120px
    lv_obj_t* weather_box = lv_obj_create(_scr_daily);
    lv_obj_set_size(weather_box, 800, 120);
    lv_obj_set_pos(weather_box, 0, 0);
    lv_obj_set_style_bg_color(weather_box, lv_color_hex(0x16213E), LV_PART_MAIN);
    lv_obj_set_style_border_width(weather_box, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(weather_box, 0, LV_PART_MAIN);

    _lbl_weather = lv_label_create(weather_box);
    lv_obj_set_width(_lbl_weather, 700);
    lv_label_set_text(_lbl_weather, "Weather: --");
    lv_obj_set_style_text_color(_lbl_weather, lv_color_hex(0xE0E0E0), LV_PART_MAIN);
    lv_obj_align(_lbl_weather, LV_ALIGN_LEFT_MID, 10, 0);

    // Indicator dots — 16x16 circles, right-aligned in weather panel
    // Order right-to-left: Data (rightmost), WS, WiFi
    auto make_dot = [](lv_obj_t* parent, int x, int y) -> lv_obj_t* {
        lv_obj_t* dot = lv_obj_create(parent);
        lv_obj_set_size(dot, 16, 16);
        lv_obj_set_pos(dot, x, y);
        lv_obj_set_style_radius(dot, 8, LV_PART_MAIN);
        lv_obj_set_style_border_width(dot, 0, LV_PART_MAIN);
        lv_obj_set_style_bg_color(dot, lv_color_hex(0x444444), LV_PART_MAIN);
        lv_obj_remove_flag(dot, LV_OBJ_FLAG_SCROLLABLE);
        return dot;
    };
    _ind_data = make_dot(weather_box, 776, 52);
    _ind_ws   = make_dot(weather_box, 752, 52);
    _ind_wifi = make_dot(weather_box, 728, 52);

    // Calendar section — middle 280px
    lv_obj_t* cal_box = lv_obj_create(_scr_daily);
    lv_obj_set_size(cal_box, 800, 280);
    lv_obj_set_pos(cal_box, 0, 120);
    lv_obj_set_style_bg_color(cal_box, lv_color_hex(0x0F3460), LV_PART_MAIN);
    lv_obj_set_style_border_width(cal_box, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(cal_box, 0, LV_PART_MAIN);

    _lbl_calendar = lv_label_create(cal_box);
    lv_obj_set_width(_lbl_calendar, 780);
    lv_label_set_long_mode(_lbl_calendar, LV_LABEL_LONG_WRAP);
    lv_label_set_text(_lbl_calendar, "Calendar: loading...");
    lv_obj_set_style_text_color(_lbl_calendar, lv_color_hex(0xE0E0E0), LV_PART_MAIN);
    lv_obj_align(_lbl_calendar, LV_ALIGN_TOP_LEFT, 10, 10);

    // Ticker section — bottom 80px, scrolling marquee
    lv_obj_t* ticker_box = lv_obj_create(_scr_daily);
    lv_obj_set_size(ticker_box, 800, 80);
    lv_obj_set_pos(ticker_box, 0, 400);
    lv_obj_set_style_bg_color(ticker_box, lv_color_hex(0xE94560), LV_PART_MAIN);
    lv_obj_set_style_border_width(ticker_box, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(ticker_box, 0, LV_PART_MAIN);
    lv_obj_add_flag(ticker_box, LV_OBJ_FLAG_OVERFLOW_VISIBLE);
    lv_obj_remove_flag(ticker_box, LV_OBJ_FLAG_SCROLLABLE);

    _lbl_ticker = lv_label_create(ticker_box);
    lv_label_set_long_mode(_lbl_ticker, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_width(_lbl_ticker, 800);
    lv_label_set_text(_lbl_ticker, "");
    lv_obj_set_style_text_color(_lbl_ticker, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_obj_align(_lbl_ticker, LV_ALIGN_LEFT_MID, 0, 0);

    // --- Build doorbell screen ---
    _scr_doorbell = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(_scr_doorbell, lv_color_hex(0xFF0000), LV_PART_MAIN);

    _lbl_doorbell = lv_label_create(_scr_doorbell);
    lv_label_set_text(_lbl_doorbell, "DOORBELL");
    lv_obj_set_style_text_color(_lbl_doorbell, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_obj_center(_lbl_doorbell);

    lv_scr_load(_scr_daily);
    _state = DisplayState::DAILY_VIEW;
}

void render_daily_view() {
    lv_scr_load(_scr_daily);
    _state = DisplayState::DAILY_VIEW;
}

void render_weather_section(float temp_c, const char* conditions) {
    if (!_lbl_weather) return;
    char buf[128];
    snprintf(buf, sizeof(buf), "%.1f°C  %s", temp_c, conditions ? conditions : "");
    lv_label_set_text(_lbl_weather, buf);
}

void render_calendar_section(const char* events_text) {
    if (!_lbl_calendar) return;
    lv_label_set_text(_lbl_calendar, events_text ? events_text : "No events");
}

void ticker_append(const char* text) {
    if (!text || !_lbl_ticker) return;
    int idx = (_ticker_head + _ticker_count) % TICKER_BUF_COUNT;
    if (_ticker_count < TICKER_BUF_COUNT) {
        _ticker_count++;
    } else {
        _ticker_head = (_ticker_head + 1) % TICKER_BUF_COUNT;
    }
    strncpy(_ticker_buf[idx], text, sizeof(_ticker_buf[0]) - 1);
    _ticker_buf[idx][sizeof(_ticker_buf[0]) - 1] = '\0';

    int off = 0;
    for (int i = 0; i < _ticker_count; i++) {
        int pos = (_ticker_head + i) % TICKER_BUF_COUNT;
        int rem = (int)sizeof(_ticker_combined) - off;
        if (rem <= 1) break;
        off += snprintf(_ticker_combined + off, (size_t)rem, "%s%s",
                        _ticker_buf[pos],
                        (i < _ticker_count - 1) ? " | " : "");
    }
    lv_label_set_text(_lbl_ticker, _ticker_combined);
}

void ticker_advance() {
    // LVGL scroll animation is driven by lv_timer_handler() in loop()
    // Nothing to do here — kept for API compatibility
}

void render_doorbell_interrupt(int timeout_seconds) {
    char buf[64];
    snprintf(buf, sizeof(buf), "DOORBELL\n%ds", timeout_seconds);
    if (_lbl_doorbell) lv_label_set_text(_lbl_doorbell, buf);
    lv_scr_load(_scr_doorbell);
    _state = DisplayState::DOORBELL_INTERRUPT;
}

void dismiss_doorbell() {
    lv_scr_load(_scr_daily);
    _state = DisplayState::DAILY_VIEW;
}

DisplayState display_get_state() { return _state; }

void display_update_indicators(bool wifi_ok, bool ws_ok, bool data_ok) {
    if (_ind_wifi) lv_obj_set_style_bg_color(_ind_wifi,
        wifi_ok ? lv_color_hex(0x00CC44) : lv_color_hex(0xFF3333), LV_PART_MAIN);
    if (_ind_ws)   lv_obj_set_style_bg_color(_ind_ws,
        ws_ok   ? lv_color_hex(0x00CC44) : lv_color_hex(0xFF3333), LV_PART_MAIN);
    if (_ind_data) lv_obj_set_style_bg_color(_ind_data,
        data_ok ? lv_color_hex(0x00CC44) : lv_color_hex(0xFFAA00), LV_PART_MAIN);
}

void display_service() { lv_timer_handler(); }
