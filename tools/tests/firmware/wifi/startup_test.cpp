#include "wifi_manager.h"
#include <cassert>
#include <cstdlib>

static unsigned pumps = 0;
static void pump() { ++pumps; }

int main(int argc, char** argv) {
    assert(argc == 3);
    WiFi.failures = std::atoi(argv[1]);
    int mode = std::atoi(argv[2]);
    if (mode == 2) WiFi.current = WL_CONNECTED;
    wifi_connect(mode == 1 ? nullptr : pump);
    assert(wifi_status_ok());
    assert(WiFi.hostname == HOUSEPANEL_HOSTNAME);
    if (mode == 2) {
        assert(WiFi.attempts == 0 && pumps == 0 && millis() == 0);
    } else {
        assert(WiFi.attempts == WiFi.failures + 1);
        assert(WiFi.disconnects == WiFi.failures);
        assert(millis() == (unsigned long)WiFi.failures * 5000);
        assert(pumps == (mode == 1 ? 0u : (unsigned)WiFi.failures * 500));
        assert(mbed::Watchdog::get_instance().kicks ==
               (unsigned)(WiFi.failures + 1 + WiFi.failures * 500));
    }
}
