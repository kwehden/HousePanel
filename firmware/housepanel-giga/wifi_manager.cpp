#include "wifi_manager.h"
#include "config.h"

void wifi_connect(void (*pump)()) {
    Serial.print("Connecting to WiFi");
    WiFi.setHostname(HOUSEPANEL_HOSTNAME);
    while (WiFi.status() != WL_CONNECTED) {
        mbed::Watchdog::get_instance().kick();
        // The pinned core's begin() is synchronous. A failed attempt will not
        // recover by polling status alone; discard it before retrying.
        int result = WiFi.begin(WIFI_SSID, WIFI_PASS);
        Serial.print(" WiFi.begin status=");
        Serial.println(result);
        if (WiFi.status() == WL_CONNECTED) break;
        WiFi.disconnect();
        for (int i = 0; i < 500; i++) {
            mbed::Watchdog::get_instance().kick();
            if (pump) pump();
            delay(10);
        }
        Serial.println("Retrying WiFi");
    }
    Serial.println(" connected");
    Serial.print("Hostname: ");
    Serial.println(HOUSEPANEL_HOSTNAME);
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("MAC: ");
    Serial.println(WiFi.macAddress());
}

bool wifi_status_ok() {
    return WiFi.status() == WL_CONNECTED;
}
