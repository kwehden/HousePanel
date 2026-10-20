#pragma once
#include "Client.h"
#include <vector>

// Only the hardware socket is faked. HttpClient/WebSocketClient run unchanged.
class WiFiClient : public Client {
public:
    inline static WiFiClient* instance = nullptr;
    std::vector<uint8_t> tx;
    String rx;
    size_t rx_offset = 0;
    bool alive = false, short_bulk_write = false;
    unsigned stops = 0;
    WiFiClient() { instance = this; }
    using Print::write;
    int connect(IPAddress, uint16_t) override { return connect("test", 80); }
    int connect(const char*, uint16_t) override {
        alive = true;
        rx = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n";
        rx_offset = 0;
        return 1;
    }
    void stop() override { alive = false; ++stops; }
    uint8_t connected() override { return alive; }
    operator bool() override { return alive; }
    size_t write(uint8_t c) override { tx.push_back(c); return 1; }
    size_t write(const uint8_t* data, size_t length) override {
        if (!alive) return 0;
        size_t accepted = short_bulk_write && length > 4 ? length - 1 : length;
        tx.insert(tx.end(), data, data + accepted);
        return accepted;
    }
    int available() override { return (int)(rx.size() - rx_offset); }
    int read() override { return available() ? (uint8_t)rx[rx_offset++] : -1; }
    int read(uint8_t* data, size_t length) override { return Stream::read(data, length); }
    int peek() override { return available() ? (uint8_t)rx[rx_offset] : -1; }
};
