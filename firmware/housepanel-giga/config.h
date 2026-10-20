#pragma once

// Local credentials and network config — defined in secrets.h (git-ignored).
// Copy secrets.h.example → secrets.h and fill in your values.
#include "secrets.h"

#ifndef HOUSEPANEL_PANEL_ID
#define HOUSEPANEL_PANEL_ID "primary"
#endif
#ifndef HOUSEPANEL_HOSTNAME
#define HOUSEPANEL_HOSTNAME "housepanel"
#endif
#define TRANSPORT_ADAPTER_WS_PATH "/ws/panels/" HOUSEPANEL_PANEL_ID
#define FIRMWARE_VERSION "0.5.3"
