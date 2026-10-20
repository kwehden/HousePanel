#pragma once

// Start with the pinned Arduino H7 display configuration. Apply the same
// project font selection to sketch C++ and LVGL's C sources via LV_CONF_PATH.
#include <lv_conf_9.h>
// Preserve the deployed UI's pool budget independently of local core edits.
#undef LV_MEM_SIZE
#define LV_MEM_SIZE (128 * 1024U)
#undef LV_FONT_MONTSERRAT_16
#undef LV_FONT_MONTSERRAT_18
#undef LV_FONT_MONTSERRAT_20
#undef LV_FONT_MONTSERRAT_28
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_18 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_28 1
