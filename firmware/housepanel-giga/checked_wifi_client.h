#pragma once
#include <WiFi.h>

// ArduinoHttpClient endMessage() checks only its final payload write. Track
// every virtual write so a failed opcode/length/mask also invalidates the socket.
class CheckedWiFiClient : public WiFiClient {
public:
    using WiFiClient::write;
    void clear_write_error() { write_error_ = false; }
    bool write_failed() const { return write_error_; }

    size_t write(uint8_t value) override {
        size_t count = WiFiClient::write(value);
        write_error_ |= count != 1;
        return count;
    }

    size_t write(const uint8_t* buffer, size_t length) override {
        size_t count = WiFiClient::write(buffer, length);
        write_error_ |= count != length;
        return count;
    }

private:
    bool write_error_ = false;
};
