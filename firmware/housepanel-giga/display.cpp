#include "display.h"
#include "config.h"
#include "Arduino_H7_Video.h"
#include "Arduino_GigaDisplayTouch.h"
#include "lvgl.h"
#include <string.h>
#include <stdio.h>

Arduino_H7_Video Display(800, 480, GigaDisplayShield);
static Arduino_GigaDisplayTouch _touch;

static DisplayState _state = DisplayState::DAILY_VIEW;

// --- Daily view ---
static lv_obj_t* _scr_daily    = nullptr;
static lv_obj_t* _lbl_calendar = nullptr;
static lv_obj_t* _lbl_ticker   = nullptr;

// 5 weather cards: index 0=today, 1-4=forecast days
static lv_obj_t* _weather_card[5]       = {};
static lv_obj_t* _weather_icon[5]       = {};
static lv_obj_t* _weather_lbl_day[5]    = {};
static lv_obj_t* _weather_lbl_cur[1]    = {};   // current temp (today only)
static lv_obj_t* _weather_lbl_high[5]   = {};
static lv_obj_t* _weather_lbl_low[5]    = {};
static lv_obj_t* _weather_lbl_cond[5]   = {};

// Status indicator dots
static lv_obj_t* _ind_wifi = nullptr;
static lv_obj_t* _ind_ws   = nullptr;
static lv_obj_t* _ind_data = nullptr;

// Status detail popup
static lv_obj_t* _popup         = nullptr;
static lv_obj_t* _popup_content = nullptr;

static bool     _s_wifi_ok  = false;
static bool     _s_ws_ok    = false;
static bool     _s_data_ok  = false;
static char     _s_ip[20]   = {};
static uint32_t _s_data_age = 0;

// --- Doorbell screen ---
static lv_obj_t* _scr_doorbell = nullptr;
static lv_obj_t* _lbl_doorbell = nullptr;

// Ticker ring buffer
static const int TICKER_BUF_COUNT = 8;
static char _ticker_buf[TICKER_BUF_COUNT][128];
static int  _ticker_head = 0;
static int  _ticker_count = 0;
static char _ticker_combined[1024];

// C/F toggle and cached weather values
static bool _show_fahrenheit = false;

static struct {
    float temp_c, high_c, low_c;
    char  conditions[32];
    bool  valid;
} _today_wx = {};

static struct {
    float high_c, low_c;
    char  label[4];
    char  conditions[26];
    bool  valid;
} _forecast_wx[4] = {};

// Map conditions string to a color (used for card border and icon fill)
static lv_color_t conditions_color(const char* cond) {
    if (!cond || !*cond) return lv_color_hex(0xFF8C00);
    if (strstr(cond, "clear") || strstr(cond, "sunny"))
        return lv_color_hex(0xFFD700);
    if (strstr(cond, "few cloud") || strstr(cond, "scatter"))
        return lv_color_hex(0x87CEEB);
    if (strstr(cond, "cloud") || strstr(cond, "overcast"))
        return lv_color_hex(0x888888);
    if (strstr(cond, "rain") || strstr(cond, "drizzle") || strstr(cond, "shower"))
        return lv_color_hex(0x4169E1);
    if (strstr(cond, "thunder") || strstr(cond, "storm"))
        return lv_color_hex(0x9400D3);
    if (strstr(cond, "snow") || strstr(cond, "sleet") || strstr(cond, "ice"))
        return lv_color_hex(0xCCEEFF);
    if (strstr(cond, "mist") || strstr(cond, "fog") || strstr(cond, "haze"))
        return lv_color_hex(0xA9A9A9);
    return lv_color_hex(0xFF8C00);
}

// Build one weather card at x offset.
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
    lv_obj_set_scrollbar_mode(card, LV_SCROLLBAR_MODE_OFF);

    lv_obj_t* lbl_day = lv_label_create(card);
    lv_obj_set_size(lbl_day, 156, 20);
    lv_obj_set_pos(lbl_day, 2, 6);
    lv_obj_set_style_text_align(lbl_day, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
    lv_obj_set_style_text_color(lbl_day, lv_color_hex(0xAAAAAA), LV_PART_MAIN);
    lv_label_set_text(lbl_day, card_idx == 0 ? "TODAY" : "---");
    _weather_lbl_day[card_idx] = lbl_day;

    lv_obj_t* icon = lv_obj_create(card);
    int icon_size = (card_idx == 0) ? 36 : 32;
    lv_obj_set_size(icon, icon_size, icon_size);
    lv_obj_set_pos(icon, (160 - icon_size) / 2, 30);
    lv_obj_set_style_radius(icon, icon_size / 2, LV_PART_MAIN);
    lv_obj_set_style_bg_color(icon, lv_color_hex(0x444444), LV_PART_MAIN);
    lv_obj_set_style_border_width(icon, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(icon, 0, LV_PART_MAIN);
    lv_obj_remove_flag(icon, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(icon, LV_SCROLLBAR_MODE_OFF);
    _weather_icon[card_idx] = icon;

    if (card_idx == 0) {
        lv_obj_t* lbl_cur = lv_label_create(card);
        lv_obj_set_size(lbl_cur, 156, 36);
        lv_obj_set_pos(lbl_cur, 2, 74);
        lv_obj_set_style_text_align(lbl_cur, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_cur, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_cur, &lv_font_montserrat_28, LV_PART_MAIN);
        lv_label_set_text(lbl_cur, "--\xc2\xb0");
        _weather_lbl_cur[0] = lbl_cur;

        lv_obj_t* lbl_high = lv_label_create(card);
        lv_obj_set_size(lbl_high, 156, 26);
        lv_obj_set_pos(lbl_high, 2, 116);
        lv_obj_set_style_text_align(lbl_high, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_high, lv_color_hex(0xFF8C00), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_high, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_high, "H: --\xc2\xb0");
        _weather_lbl_high[0] = lbl_high;

        lv_obj_t* lbl_low = lv_label_create(card);
        lv_obj_set_size(lbl_low, 156, 26);
        lv_obj_set_pos(lbl_low, 2, 144);
        lv_obj_set_style_text_align(lbl_low, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_low, lv_color_hex(0x66AAFF), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_low, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_low, "L: --\xc2\xb0");
        _weather_lbl_low[0] = lbl_low;

        _weather_lbl_cond[0] = nullptr;
    } else {
        lv_obj_t* lbl_high = lv_label_create(card);
        lv_obj_set_size(lbl_high, 156, 26);
        lv_obj_set_pos(lbl_high, 2, 72);
        lv_obj_set_style_text_align(lbl_high, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_high, lv_color_hex(0xFF8C00), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_high, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_high, "H: --\xc2\xb0");
        _weather_lbl_high[card_idx] = lbl_high;

        lv_obj_t* lbl_low = lv_label_create(card);
        lv_obj_set_size(lbl_low, 156, 26);
        lv_obj_set_pos(lbl_low, 2, 100);
        lv_obj_set_style_text_align(lbl_low, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl_low, lv_color_hex(0x66AAFF), LV_PART_MAIN);
        lv_obj_set_style_text_font(lbl_low, &lv_font_montserrat_20, LV_PART_MAIN);
        lv_label_set_text(lbl_low, "L: --\xc2\xb0");
        _weather_lbl_low[card_idx] = lbl_low;

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

// --- C/F helpers ---

static float to_disp(float c) {
    return _show_fahrenheit ? c * 9.0f / 5.0f + 32.0f : c;
}
static const char* unit_str() {
    return _show_fahrenheit ? "\xc2\xb0""F" : "\xc2\xb0";
}

static void _render_today() {
    if (!_today_wx.valid) return;
    char buf[48];
    lv_color_t col = conditions_color(_today_wx.conditions);
    if (_weather_card[0])    lv_obj_set_style_border_color(_weather_card[0], col, LV_PART_MAIN);
    if (_weather_icon[0])    lv_obj_set_style_bg_color(_weather_icon[0],     col, LV_PART_MAIN);
    if (_weather_lbl_cur[0]) { snprintf(buf, sizeof(buf), "%.0f%s", to_disp(_today_wx.temp_c), unit_str()); lv_label_set_text(_weather_lbl_cur[0], buf); }
    if (_weather_lbl_high[0]){ snprintf(buf, sizeof(buf), "H: %.0f%s", to_disp(_today_wx.high_c), unit_str()); lv_label_set_text(_weather_lbl_high[0], buf); }
    if (_weather_lbl_low[0]) { snprintf(buf, sizeof(buf), "L: %.0f%s", to_disp(_today_wx.low_c),  unit_str()); lv_label_set_text(_weather_lbl_low[0], buf); }
}

static void _render_forecast(int c) {
    if (c < 1 || c > 4 || !_forecast_wx[c - 1].valid) return;
    int fi = c - 1;
    char buf[48];
    lv_color_t col = conditions_color(_forecast_wx[fi].conditions);
    if (_weather_card[c])     lv_obj_set_style_border_color(_weather_card[c], col, LV_PART_MAIN);
    if (_weather_icon[c])     lv_obj_set_style_bg_color(_weather_icon[c],     col, LV_PART_MAIN);
    if (_weather_lbl_day[c])  lv_label_set_text(_weather_lbl_day[c], _forecast_wx[fi].label[0] ? _forecast_wx[fi].label : "---");
    if (_weather_lbl_high[c]) { snprintf(buf, sizeof(buf), "H: %.0f%s", to_disp(_forecast_wx[fi].high_c), unit_str()); lv_label_set_text(_weather_lbl_high[c], buf); }
    if (_weather_lbl_low[c])  { snprintf(buf, sizeof(buf), "L: %.0f%s", to_disp(_forecast_wx[fi].low_c),  unit_str()); lv_label_set_text(_weather_lbl_low[c], buf); }
    if (_weather_lbl_cond[c]) lv_label_set_text(_weather_lbl_cond[c], _forecast_wx[fi].conditions);
}

static void unit_toggle_cb(lv_event_t* e) {
    static unsigned long last_ms = 0;
    unsigned long now = millis();
    if (now - last_ms < 300) return;
    last_ms = now;
    _show_fahrenheit = !_show_fahrenheit;
    _render_today();
    for (int c = 1; c <= 4; c++) _render_forecast(c);
}

// --- Status popup helpers ---

static void refresh_popup_content() {
    if (!_popup_content) return;
    char data_str[24];
    if (_s_data_age == 0)
        snprintf(data_str, sizeof(data_str), "No data yet");
    else if (_s_data_age < 60)
        snprintf(data_str, sizeof(data_str), "%us ago", (unsigned)_s_data_age);
    else
        snprintf(data_str, sizeof(data_str), "%um ago", (unsigned)(_s_data_age / 60));

    char buf[220];
    snprintf(buf, sizeof(buf),
             "WiFi:   %s\n"
             "IP:     %s\n"
             "Server: %s\n"
             "Data:   %s\n"
             "FW:     " FIRMWARE_VERSION,
             _s_wifi_ok ? "Connected" : "Down",
             _s_ip[0]   ? _s_ip : "--",
             _s_ws_ok   ? "Connected" : "Down",
             data_str);
    lv_label_set_text(_popup_content, buf);
}

static void popup_close_cb(lv_event_t* e) {
    static unsigned long last_ms = 0;
    unsigned long now = millis();
    if (now - last_ms < 300) return;
    last_ms = now;
    if (_popup) lv_obj_add_flag(_popup, LV_OBJ_FLAG_HIDDEN);
}

static void touch_read_cb(lv_indev_t* indev, lv_indev_data_t* data) {
    static lv_point_t last_point = {0, 0};
    GDTpoint_t points[1];
    uint8_t contacts = _touch.getTouchPoints(points);
    if (contacts > 0) {
        last_point.x = points[0].x;
        last_point.y = points[0].y;
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
    data->point = last_point;
}

static void status_click_cb(lv_event_t* e) {
    static unsigned long last_ms = 0;
    unsigned long now = millis();
    if (now - last_ms < 300) return;
    last_ms = now;
    if (!_popup) return;
    refresh_popup_content();
    lv_obj_remove_flag(_popup, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(_popup);
}

void display_init() {
    if (Display.begin()) {
        while (true) { delay(500); }
    }

    _scr_daily = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(_scr_daily, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_pad_all(_scr_daily, 0, LV_PART_MAIN);
    lv_obj_set_scrollbar_mode(_scr_daily, LV_SCROLLBAR_MODE_OFF);

    // --- Weather row: y=0, h=180 ---
    lv_obj_t* weather_row = lv_obj_create(_scr_daily);
    lv_obj_set_size(weather_row, 800, 180);
    lv_obj_set_pos(weather_row, 0, 0);
    lv_obj_set_style_bg_color(weather_row, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_border_width(weather_row, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(weather_row, 0, LV_PART_MAIN);
    lv_obj_remove_flag(weather_row, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(weather_row, LV_SCROLLBAR_MODE_OFF);

    for (int i = 0; i < 5; i++) {
        _weather_card[i] = make_weather_card(weather_row, i * 160, i);
    }

    // Transparent tap overlay — created AFTER cards so it sits on top in Z-order.
    // Intercepts all touches before the cards' clickable children can consume them.
    lv_obj_t* wx_tap = lv_obj_create(weather_row);
    lv_obj_set_size(wx_tap, 800, 180);
    lv_obj_set_pos(wx_tap, 0, 0);
    lv_obj_set_style_bg_opa(wx_tap, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(wx_tap, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(wx_tap, 0, LV_PART_MAIN);
    lv_obj_remove_flag(wx_tap, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(wx_tap, LV_SCROLLBAR_MODE_OFF);
    lv_obj_add_event_cb(wx_tap, unit_toggle_cb, LV_EVENT_CLICKED, nullptr);

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
    lv_obj_set_scrollbar_mode(cal_box, LV_SCROLLBAR_MODE_OFF);

    _lbl_calendar = lv_label_create(cal_box);
    lv_obj_set_size(_lbl_calendar, 784, 208);
    lv_obj_set_pos(_lbl_calendar, 8, 6);
    lv_label_set_long_mode(_lbl_calendar, LV_LABEL_LONG_CLIP);
    lv_label_set_text(_lbl_calendar, "Calendar: loading...");
    lv_obj_set_style_text_color(_lbl_calendar, lv_color_hex(0xDDDDDD), LV_PART_MAIN);
    lv_obj_set_style_text_font(_lbl_calendar, &lv_font_montserrat_20, LV_PART_MAIN);

    // --- Ticker row: y=400, h=80, width=706 (status panel lives outside to the right) ---
    lv_obj_t* ticker_box = lv_obj_create(_scr_daily);
    lv_obj_set_size(ticker_box, 706, 80);
    lv_obj_set_pos(ticker_box, 0, 400);
    lv_obj_set_style_bg_color(ticker_box, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_border_color(ticker_box, lv_color_hex(0xE94560), LV_PART_MAIN);
    lv_obj_set_style_border_width(ticker_box, 2, LV_PART_MAIN);
    lv_obj_set_style_radius(ticker_box, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(ticker_box, 0, LV_PART_MAIN);
    lv_obj_remove_flag(ticker_box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(ticker_box, LV_SCROLLBAR_MODE_OFF);

    _lbl_ticker = lv_label_create(ticker_box);
    lv_label_set_long_mode(_lbl_ticker, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_size(_lbl_ticker, 698, 76);
    lv_obj_set_pos(_lbl_ticker, 4, 2);
    lv_label_set_text(_lbl_ticker, "");
    lv_obj_set_style_text_color(_lbl_ticker, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_obj_set_style_text_font(_lbl_ticker, &lv_font_montserrat_20, LV_PART_MAIN);

    // Status panel — sits outside the red ticker border, directly in _scr_daily.
    // 94×80 at x=706, y=400 fills the remaining screen width (706+94=800).
    lv_obj_t* stat_panel = lv_obj_create(_scr_daily);
    lv_obj_set_size(stat_panel, 94, 80);
    lv_obj_set_pos(stat_panel, 706, 400);
    lv_obj_set_style_bg_opa(stat_panel, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(stat_panel, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(stat_panel, 0, LV_PART_MAIN);
    lv_obj_remove_flag(stat_panel, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(stat_panel, LV_SCROLLBAR_MODE_OFF);
    lv_obj_add_flag(stat_panel, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(stat_panel, status_click_cb, LV_EVENT_CLICKED, nullptr);

    // Each row: 26px tall. Label right-aligns into 60px, dot at x=76.
    // row_y values: 1, 27, 53 → dot y-centers at 14, 40, 66 within the 80px panel.
    auto make_indicator = [](lv_obj_t* parent, int row_y, const char* label_text) -> lv_obj_t* {
        lv_obj_t* lbl = lv_label_create(parent);
        lv_obj_set_size(lbl, 60, 16);
        lv_obj_set_pos(lbl, 2, row_y + 5);
        lv_obj_set_style_text_font(lbl, &lv_font_montserrat_14, LV_PART_MAIN);
        lv_obj_set_style_text_color(lbl, lv_color_hex(0x888888), LV_PART_MAIN);
        lv_obj_set_style_text_align(lbl, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN);
        lv_label_set_text(lbl, label_text);

        lv_obj_t* dot = lv_obj_create(parent);
        lv_obj_set_size(dot, 12, 12);
        lv_obj_set_pos(dot, 76, row_y + 7);
        lv_obj_set_style_radius(dot, 6, LV_PART_MAIN);
        lv_obj_set_style_border_width(dot, 0, LV_PART_MAIN);
        lv_obj_set_style_pad_all(dot, 0, LV_PART_MAIN);
        lv_obj_set_style_bg_color(dot, lv_color_hex(0x444444), LV_PART_MAIN);
        lv_obj_remove_flag(dot, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_scrollbar_mode(dot, LV_SCROLLBAR_MODE_OFF);
        return dot;
    };

    _ind_wifi = make_indicator(stat_panel,  1, "WiFi");
    _ind_ws   = make_indicator(stat_panel, 27, "WS");
    _ind_data = make_indicator(stat_panel, 53, "Data");

    // --- Doorbell screen ---
    _scr_doorbell = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(_scr_doorbell, lv_color_hex(0xCC0000), LV_PART_MAIN);
    lv_obj_set_style_pad_all(_scr_doorbell, 0, LV_PART_MAIN);
    lv_obj_set_scrollbar_mode(_scr_doorbell, LV_SCROLLBAR_MODE_OFF);

    _lbl_doorbell = lv_label_create(_scr_doorbell);
    lv_obj_set_style_text_font(_lbl_doorbell, &lv_font_montserrat_28, LV_PART_MAIN);
    lv_label_set_text(_lbl_doorbell, "DOORBELL");
    lv_obj_set_style_text_color(_lbl_doorbell, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_obj_center(_lbl_doorbell);

    // --- Status popup (lv_layer_top, hidden until tapped) ---
    // Size: 380×240. Centered via lv_obj_align to avoid lv_layer_top() padding surprises.
    _popup = lv_obj_create(lv_layer_top());
    lv_obj_set_size(_popup, 380, 240);
    lv_obj_set_style_bg_color(_popup, lv_color_hex(0x0D1117), LV_PART_MAIN);
    lv_obj_set_style_border_color(_popup, lv_color_hex(0x3A7BD5), LV_PART_MAIN);
    lv_obj_set_style_border_width(_popup, 2, LV_PART_MAIN);
    lv_obj_set_style_radius(_popup, 8, LV_PART_MAIN);
    lv_obj_set_style_pad_all(_popup, 0, LV_PART_MAIN);
    lv_obj_remove_flag(_popup, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(_popup, LV_SCROLLBAR_MODE_OFF);
    lv_obj_add_flag(_popup, LV_OBJ_FLAG_HIDDEN);
    lv_obj_align(_popup, LV_ALIGN_CENTER, 0, 0);

    lv_obj_t* ptitle = lv_label_create(_popup);
    lv_obj_set_pos(ptitle, 14, 12);
    lv_obj_set_style_text_font(ptitle, &lv_font_montserrat_20, LV_PART_MAIN);
    lv_obj_set_style_text_color(ptitle, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_label_set_text(ptitle, "System Status");

    // Top divider
    lv_obj_t* pdiv = lv_obj_create(_popup);
    lv_obj_set_size(pdiv, 352, 1);
    lv_obj_set_pos(pdiv, 14, 44);
    lv_obj_set_style_bg_color(pdiv, lv_color_hex(0x333355), LV_PART_MAIN);
    lv_obj_set_style_border_width(pdiv, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(pdiv, 0, LV_PART_MAIN);

    // Content label (5 lines at montserrat_14 ≈ 18px each → 90px)
    _popup_content = lv_label_create(_popup);
    lv_obj_set_pos(_popup_content, 14, 52);
    lv_obj_set_size(_popup_content, 352, 128);
    lv_obj_set_style_text_font(_popup_content, &lv_font_montserrat_14, LV_PART_MAIN);
    lv_obj_set_style_text_color(_popup_content, lv_color_hex(0xCCCCCC), LV_PART_MAIN);
    lv_label_set_long_mode(_popup_content, LV_LABEL_LONG_CLIP);
    lv_label_set_text(_popup_content, "Loading...");

    // Bottom divider
    lv_obj_t* pdiv2 = lv_obj_create(_popup);
    lv_obj_set_size(pdiv2, 352, 1);
    lv_obj_set_pos(pdiv2, 14, 188);
    lv_obj_set_style_bg_color(pdiv2, lv_color_hex(0x333355), LV_PART_MAIN);
    lv_obj_set_style_border_width(pdiv2, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(pdiv2, 0, LV_PART_MAIN);

    // CLOSE button — full width, obvious tap target
    lv_obj_t* pbtn = lv_obj_create(_popup);
    lv_obj_set_size(pbtn, 352, 40);
    lv_obj_set_pos(pbtn, 14, 194);
    lv_obj_set_style_bg_color(pbtn, lv_color_hex(0x1E3A6E), LV_PART_MAIN);
    lv_obj_set_style_border_width(pbtn, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(pbtn, 6, LV_PART_MAIN);
    lv_obj_set_style_pad_all(pbtn, 0, LV_PART_MAIN);
    lv_obj_remove_flag(pbtn, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(pbtn, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(pbtn, popup_close_cb, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* pbtn_lbl = lv_label_create(pbtn);
    lv_obj_set_size(pbtn_lbl, 352, 40);
    lv_obj_set_pos(pbtn_lbl, 0, 0);
    lv_obj_set_style_text_font(pbtn_lbl, &lv_font_montserrat_20, LV_PART_MAIN);
    lv_obj_set_style_text_color(pbtn_lbl, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_obj_set_style_text_align(pbtn_lbl, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
    lv_label_set_text(pbtn_lbl, "CLOSE");

    // Register touch input device with LVGL
    if (!_touch.begin()) {
        Serial.println("Touch init FAILED");
    } else {
        Serial.println("Touch init OK");
        lv_indev_t* indev = lv_indev_create();
        lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
        lv_indev_set_read_cb(indev, touch_read_cb);
    }

    lv_scr_load(_scr_daily);
    _state = DisplayState::DAILY_VIEW;
}

void render_daily_view() {
    lv_scr_load(_scr_daily);
    _state = DisplayState::DAILY_VIEW;
}

void render_weather_today(float temp_c, const char* conditions, float high_c, float low_c) {
    _today_wx.temp_c = temp_c;
    _today_wx.high_c = high_c;
    _today_wx.low_c  = low_c;
    strncpy(_today_wx.conditions, conditions ? conditions : "", sizeof(_today_wx.conditions) - 1);
    _today_wx.conditions[sizeof(_today_wx.conditions) - 1] = '\0';
    _today_wx.valid = true;
    _render_today();
}

void render_weather_day(int idx, const char* label, float high_c, float low_c, const char* conditions) {
    if (idx < 0 || idx > 3) return;
    _forecast_wx[idx].high_c = high_c;
    _forecast_wx[idx].low_c  = low_c;
    strncpy(_forecast_wx[idx].label, label ? label : "", sizeof(_forecast_wx[idx].label) - 1);
    _forecast_wx[idx].label[sizeof(_forecast_wx[idx].label) - 1] = '\0';
    strncpy(_forecast_wx[idx].conditions, conditions ? conditions : "", sizeof(_forecast_wx[idx].conditions) - 1);
    _forecast_wx[idx].conditions[sizeof(_forecast_wx[idx].conditions) - 1] = '\0';
    _forecast_wx[idx].valid = true;
    _render_forecast(idx + 1);
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
    if (_popup) lv_obj_add_flag(_popup, LV_OBJ_FLAG_HIDDEN);
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

void display_update_status_detail(bool wifi_ok, const char* ip_str,
                                   bool ws_ok, bool data_ok,
                                   uint32_t data_age_s) {
    _s_wifi_ok  = wifi_ok;
    _s_ws_ok    = ws_ok;
    _s_data_ok  = data_ok;
    _s_data_age = data_age_s;
    strncpy(_s_ip, ip_str ? ip_str : "", sizeof(_s_ip) - 1);
    _s_ip[sizeof(_s_ip) - 1] = '\0';
    if (_popup && !lv_obj_has_flag(_popup, LV_OBJ_FLAG_HIDDEN)) {
        refresh_popup_content();
    }
}

void display_service() { lv_timer_handler(); }
