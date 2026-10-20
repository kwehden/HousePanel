#include "wifi_manager.h"
#include "config.h"

void wifi_connect(void (*pump)()) {
    Serial.print("Connecting to WiFi");
    WiFi.setHostname(HOUSEPANEL_HOSTNAME);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    while (WiFi.status() != WL_CONNECTED) {
        mbed::Watchdog::get_instance().kick();
        if (pump) {
            for (int i = 0; i < 50; i++) { pump(); delay(10); }
        } else {
            delay(500);
        }
        Serial.print(".");
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
