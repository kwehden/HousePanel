#include "wifi_manager.h"
#include "config.h"

void wifi_connect(void (*pump)()) {
    Serial.print("Connecting to WiFi");
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    while (WiFi.status() != WL_CONNECTED) {
        if (pump) {
            for (int i = 0; i < 50; i++) { pump(); delay(10); }
        } else {
            delay(500);
        }
        Serial.print(".");
    }
    Serial.println(" connected");
}

bool wifi_status_ok() {
    return WiFi.status() == WL_CONNECTED;
}
