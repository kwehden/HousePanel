#include "display.h"
#include "Arduino_H7_Video.h"
#include "lvgl.h"
#include <string.h>
#include <stdio.h>

Arduino_H7_Video Display(800, 480, GigaDisplayShield);

static DisplayState _state = DisplayState::DAILY_VIEW;

// --- Daily view ---
static lv_obj_t* _scr_daily    = nullptr;
static lv_obj_t* _lbl_calendar = nullptr;
static lv_obj_t* _lbl_ticker   = nullptr;

// 5 weather cards: index 0=today, 1-4=forecast days
static lv_obj_t* _weather_card[5]       = {};
static lv_obj_t* _weather_icon[5]       = {};   // colored circle
static lv_obj_t* _weather_lbl_day[5]    = {};   // "TODAY", "Mon", etc.
static lv_obj_t* _weather_lbl_cur[1]    = {};   // current temp (today only)
static lv_obj_t* _weather_lbl_high[5]   = {};
static lv_obj_t* _weather_lbl_low[5]    = {};
static lv_obj_t* _weather_lbl_cond[5]   = {};   // conditions text

// Status indicator dots (in ticker row, right side)
static lv_obj_t* _ind_wifi = nullptr;
static lv_obj_t* _ind_ws   = nullptr;
static lv_obj_t* _ind_data = nullptr;

// --- Doorbell screen ---
static lv_obj_t* _scr_doorbell = nullptr;
static lv_obj_t* _lbl_doorbell = nullptr;

// Ticker ring buffer
static const int TICKER_BUF_COUNT = 8;
static char _ticker_buf[TICKER_BUF_COUNT][128];
static int  _ticker_head = 0;
static int  _ticker_count = 0;
static char _ticker_combined[1024];

// Map conditions string to a color (used for card border and icon fill)
static lv_color_t conditions_color(const char* cond) {
    if (!cond || !*cond) return lv_color_hex(0xFF8C00);
    if (strstr(cond, "clear") || strstr(cond, "sunny"))
        return lv_color_hex(0xFFD700);   // gold
    if (strstr(cond, "few cloud") || strstr(cond, "scatter"))
        return lv_color_hex(0x87CEEB);   // sky blue
    if (strstr(cond, "cloud") || strstr(cond, "overcast"))
        return lv_color_hex(0x888888);   // gray
    if (strstr(cond, "rain") || strstr(cond, "drizzle") || strstr(cond, "shower"))
        return lv_color_hex(0x4169E1);   // royal blue
    if (strstr(cond, "thunder") || strstr(cond, "storm"))
        return lv_color_hex(0x9400D3);   // purple
    if (strstr(cond, "snow") || strstr(cond, "sleet") || strstr(cond, "ice"))
        return lv_color_hex(0xCCEEFF);   // light blue-white
    if (strstr(cond, "mist") || strstr(cond, "fog") || strstr(cond, "haze"))
        return lv_color_hex(0xA9A9A9);   // dark gray
    return lv_color_hex(0xFF8C00);       // orange fallback
}

// Build one weather card at x offset. Returns the card object.
// Card dimensions: 160 wide × 180 tall, pad_all=0, black bg, 2px colored border.
static lv_obj_t* make_weather_card(lv_obj_t* parent, int x_pos, int card_idx) {
    lv_obj_t* card = lv_obj_create(parent);
    lv_obj_set_size(card, 160, 180);
    lv_obj_set_pos(card, x_pos, 0);
    lv_obj_set_style_pad_all(card, 0, LV_PART_MAIN);
    lv_obj_set_style_bg_color(card, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_border_color(card, lv_color_hex(0x444444), LV_PART_MAIN);
    lv_obj_set_style_border_width(card, 2, LV_PART_MAIN);
    lv_obj_set_style_radius(card, 4, LV_PART_MAIN);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);

    // Day label (top center)
    lv_obj_t* lbl_day = lv_label_create(card);
    lv_obj_set_size(lbl_day, 156, 20);
    lv_obj_set_pos(lbl_day, 2, 6);
    lv_obj_set_style_text_align(lbl_day, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
    lv_obj_set_style_text_color(lbl_day, lv_color_hex(0xAAAAAA), LV_PART_MAIN);
    lv_label_set_text(lbl_day, card_idx == 0 ? "TODAY" : "---");
    _weather_lbl_day[card_idx] = lbl_day;

    // Weather icon — filled circle
    lv_obj_t* icon = lv_obj_create(card);
    int icon_size = (card_idx == 0) ? 36 : 32;
    lv_obj_set_size(icon, icon_size, icon_size);
    lv_obj_set_pos(icon, (160 - icon_size) / 2, 30);
    lv_obj_set_style_radius(icon, icon_size / 2, LV_PART_MAIN);
    lv_obj_set_style_bg_color(icon, lv_color_hex(0x444444), LV_PART_MAIN);
    lv_obj_set_style_border_width(icon, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(icon, 0, LV_PART_MAIN);
    lv_obj_remove_flag(icon, LV_OBJ_FLAG_SCROLLABLE);
    _weather_icon[card_idx] = icon;

    if (card_idx == 0) {
        // Current temperature (large, today only)
        lv_obj_t* lbl_cur = lv_label_create(card);
        lv_obj_set_size(lbl_cur, 156, 36);
        lv_obj_set_pos(lbl_cur, 2, 74);
        lv_obj_set_style_text_align(lbl_cur, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_cur, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_cur, &lv_font_montserrat_28, LV_PART_MAIN);
        lv_label_set_text(lbl_cur, "--°");
        _weather_lbl_cur[0] = lbl_cur;

        // High
        lv_obj_t* lbl_high = lv_label_create(card);
        lv_obj_set_size(lbl_high, 156, 26);
        lv_obj_set_pos(lbl_high, 2, 116);
        lv_obj_set_style_text_align(lbl_high, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_high, lv_color_hex(0xFF8C00), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_high, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_high, "H: --°");
        _weather_lbl_high[0] = lbl_high;

        // Low
        lv_obj_t* lbl_low = lv_label_create(card);
        lv_obj_set_size(lbl_low, 156, 26);
        lv_obj_set_pos(lbl_low, 2, 144);
        lv_obj_set_style_text_align(lbl_low, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_low, lv_color_hex(0x66AAFF), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_low, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_low, "L: --°");
        _weather_lbl_low[0] = lbl_low;

        // No conditions label for today (conditions shown via icon color)
        _weather_lbl_cond[0] = nullptr;
    } else {
        // High
        lv_obj_t* lbl_high = lv_label_create(card);
        lv_obj_set_size(lbl_high, 156, 26);
        lv_obj_set_pos(lbl_high, 2, 72);
        lv_obj_set_style_text_align(lbl_high, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_high, lv_color_hex(0xFF8C00), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_high, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_high, "H: --°");
        _weather_lbl_high[card_idx] = lbl_high;

        // Low
        lv_obj_t* lbl_low = lv_label_create(card);
        lv_obj_set_size(lbl_low, 156, 26);
        lv_obj_set_pos(lbl_low, 2, 100);
        lv_obj_set_style_text_align(lbl_low, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_low, lv_color_hex(0x66AAFF), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_low, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_low, "L: --°");
        _weather_lbl_low[card_idx] = lbl_low;

        // Conditions text (small, bottom)
        lv_obj_t* lbl_cond = lv_label_create(card);
        lv_obj_set_size(lbl_cond, 154, 20);
        lv_obj_set_pos(lbl_cond, 3, 134);
        lv_obj_set_style_text_align(lbl_cond, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_cond, lv_color_hex(0x888888), LV_PART_MAIN);
        lv_label_set_long_mode(lbl_cond, LV_LABEL_LONG_CLIP);
        lv_label_set_text(lbl_cond, "");
        _weather_lbl_cond[card_idx] = lbl_cond;
    }

    return card;
}

void display_init() {
    if (Display.begin()) {
        while (true) { delay(500); }
    }

    _scr_daily = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(_scr_daily, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_pad_all(_scr_daily, 0, LV_PART_MAIN);

    // --- Weather row: y=0, h=180, 5 cards ---
    lv_obj_t* weather_row = lv_obj_create(_scr_daily);
    lv_obj_set_size(weather_row, 800, 180);
    lv_obj_set_pos(weather_row, 0, 0);
    lv_obj_set_style_bg_color(weather_row, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_border_width(weather_row, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(weather_row, 0, LV_PART_MAIN);
    lv_obj_remove_flag(weather_row, LV_OBJ_FLAG_SCROLLABLE);

    for (int i = 0; i < 5; i++) {
        _weather_card[i] = make_weather_card(weather_row, i * 160, i);
    }

    // --- Calendar row: y=180, h=220 ---
    lv_obj_t* cal_box = lv_obj_create(_scr_daily);
    lv_obj_set_size(cal_box, 800, 220);
    lv_obj_set_pos(cal_box, 0, 180);
    lv_obj_set_style_bg_color(cal_box, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_border_color(cal_box, lv_color_hex(0x1565C0), LV_PART_MAIN);
    lv_obj_set_style_border_width(cal_box, 2, LV_PART_MAIN);
    lv_obj_set_style_radius(cal_box, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(cal_box, 0, LV_PART_MAIN);
    lv_obj_remove_flag(cal_box, LV_OBJ_FLAG_SCROLLABLE);

    _lbl_calendar = lv_label_create(cal_box);
    lv_obj_set_size(_lbl_calendar, 784, 208);
    lv_obj_set_pos(_lbl_calendar, 8, 6);
    lv_label_set_long_mode(_lbl_calendar, LV_LABEL_LONG_CLIP);
    lv_label_set_text(_lbl_calendar, "Calendar: loading...");
    lv_obj_set_style_text_color(_lbl_calendar, lv_color_hex(0xDDDDDD), LV_PART_MAIN);
    lv_obj_set_style_text_font(_lbl_calendar, &lv_font_montserrat_20, LV_PART_MAIN);

    // --- Ticker row: y=400, h=80 ---
    lv_obj_t* ticker_box = lv_obj_create(_scr_daily);
    lv_obj_set_size(ticker_box, 800, 80);
    lv_obj_set_pos(ticker_box, 0, 400);
    lv_obj_set_style_bg_color(ticker_box, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_border_color(ticker_box, lv_color_hex(0xE94560), LV_PART_MAIN);
    lv_obj_set_style_border_width(ticker_box, 2, LV_PART_MAIN);
    lv_obj_set_style_radius(ticker_box, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(ticker_box, 0, LV_PART_MAIN);
    lv_obj_remove_flag(ticker_box, LV_OBJ_FLAG_SCROLLABLE);

    // Ticker label — leave 52px on the right for status dots
    _lbl_ticker = lv_label_create(ticker_box);
    lv_label_set_long_mode(_lbl_ticker, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_size(_lbl_ticker, 742, 76);
    lv_obj_set_pos(_lbl_ticker, 4, 2);
    lv_label_set_text(_lbl_ticker, "");
    lv_obj_set_style_text_color(_lbl_ticker, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_obj_set_style_text_font(_lbl_ticker, &lv_font_montserrat_20, LV_PART_MAIN);

    // Status indicator dots (right side of ticker row)
    // 3 × 12px circles, x=748,764,780  y=34 (centered in 80px: (80-12)/2=34)
    auto make_dot = [](lv_obj_t* parent, int x, int y) -> lv_obj_t* {
        lv_obj_t* dot = lv_obj_create(parent);
        lv_obj_set_size(dot, 12, 12);
        lv_obj_set_pos(dot, x, y);
        lv_obj_set_style_radius(dot, 6, LV_PART_MAIN);
        lv_obj_set_style_border_width(dot, 0, LV_PART_MAIN);
        lv_obj_set_style_pad_all(dot, 0, LV_PART_MAIN);
        lv_obj_set_style_bg_color(dot, lv_color_hex(0x444444), LV_PART_MAIN);
        lv_obj_remove_flag(dot, LV_OBJ_FLAG_SCROLLABLE);
        return dot;
    };
    _ind_wifi = make_dot(ticker_box, 748, 34);
    _ind_ws   = make_dot(ticker_box, 764, 34);
    _ind_data = make_dot(ticker_box, 780, 34);

    // --- Doorbell screen ---
    _scr_doorbell = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(_scr_doorbell, lv_color_hex(0xCC0000), LV_PART_MAIN);
    lv_obj_set_style_pad_all(_scr_doorbell, 0, LV_PART_MAIN);

    _lbl_doorbell = lv_label_create(_scr_doorbell);
    lv_obj_set_style_text_font(_lbl_doorbell, &lv_font_montserrat_28, LV_PART_MAIN);
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

void render_weather_section(const WeatherData& w) {
    char buf[64];

    // Today card
    lv_color_t col = conditions_color(w.conditions);
    if (_weather_card[0]) {
        lv_obj_set_style_border_color(_weather_card[0], col, LV_PART_MAIN);
    }
    if (_weather_icon[0]) {
        lv_obj_set_style_bg_color(_weather_icon[0], col, LV_PART_MAIN);
    }
    if (_weather_lbl_cur[0]) {
        snprintf(buf, sizeof(buf), "%.0f\xc2\xb0", w.temperature_c);  // °
        lv_label_set_text(_weather_lbl_cur[0], buf);
    }
    if (_weather_lbl_high[0]) {
        snprintf(buf, sizeof(buf), "H: %.0f\xc2\xb0", w.today_high_c);
        lv_label_set_text(_weather_lbl_high[0], buf);
    }
    if (_weather_lbl_low[0]) {
        snprintf(buf, sizeof(buf), "L: %.0f\xc2\xb0", w.today_low_c);
        lv_label_set_text(_weather_lbl_low[0], buf);
    }

    // Forecast cards 1-4
    for (int i = 0; i < 4; i++) {
        const ForecastDay& fd = w.forecast[i];
        lv_color_t fc = conditions_color(fd.conditions);

        if (_weather_card[i + 1]) {
            lv_obj_set_style_border_color(_weather_card[i + 1], fc, LV_PART_MAIN);
        }
        if (_weather_icon[i + 1]) {
            lv_obj_set_style_bg_color(_weather_icon[i + 1], fc, LV_PART_MAIN);
        }
        if (_weather_lbl_day[i + 1]) {
            lv_label_set_text(_weather_lbl_day[i + 1], fd.day_label[0] ? fd.day_label : "---");
        }
        if (_weather_lbl_high[i + 1]) {
            snprintf(buf, sizeof(buf), "H: %.0f\xc2\xb0", fd.high_c);
            lv_label_set_text(_weather_lbl_high[i + 1], buf);
        }
        if (_weather_lbl_low[i + 1]) {
            snprintf(buf, sizeof(buf), "L: %.0f\xc2\xb0", fd.low_c);
            lv_label_set_text(_weather_lbl_low[i + 1], buf);
        }
        if (_weather_lbl_cond[i + 1]) {
            lv_label_set_text(_weather_lbl_cond[i + 1], fd.conditions);
        }
    }
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

void ticker_advance() {}

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
