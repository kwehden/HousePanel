#pragma once
#include "Arduino.h"
#include <cassert>

constexpr int WL_CONNECTED = 3;
constexpr int WL_CONNECT_FAILED = 4;

struct FakeWiFi {
    int attempts = 0, failures = 0, disconnects = 0;
    int current = WL_CONNECT_FAILED;
    unsigned long last_attempt = 0;
    bool pending_failure = false;
    std::string hostname;
    void setHostname(const char* name) { hostname = name; }
    int status() { return current; }
    int begin(const char*, const char*) {
        assert(!pending_failure);
        if (attempts) assert(millis() - last_attempt >= 5000);
        last_attempt = millis();
        ++attempts;
        current = attempts <= failures ? WL_CONNECT_FAILED : WL_CONNECTED;
        pending_failure = current != WL_CONNECTED;
        return current;
    }
    int disconnect() {
        assert(pending_failure);
        ++disconnects;
        pending_failure = false;
        return current;
    }
    const char* localIP() { return "192.0.2.1"; }
    const char* macAddress() { return "00:00:00:00:00:01"; }
};
inline FakeWiFi WiFi;

namespace mbed {
class Watchdog {
public:
    unsigned kicks = 0;
    static Watchdog& get_instance() { static Watchdog value; return value; }
    void kick() { ++kicks; }
};
}
