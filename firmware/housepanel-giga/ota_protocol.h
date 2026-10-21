#pragma once
#include <stddef.h>
#include <stdint.h>
#include <mbedtls/aes.h>
#include <mbedtls/sha256.h>

constexpr size_t OTA_HEADER_SIZE = 141;
// GIGA M7 application starts at 0x08040000; preserve the upper 512 KiB for M4.
constexpr uint32_t OTA_MAX_IMAGE = 0x08180000 - 0x08040000;
constexpr uint16_t OTA_PORT = 8266;

class OtaSink {
public:
    virtual ~OtaSink() = default;
    virtual bool begin() = 0;
    virtual bool write(const uint8_t* data, size_t size) = 0;
    virtual bool finish() = 0;
    virtual void abort() = 0;
};

// Fixed-size authenticated envelope; no socket, filesystem or heap ownership.
class OtaReceiver {
public:
    OtaReceiver();
    ~OtaReceiver();
    OtaReceiver(const OtaReceiver&) = delete;
    OtaReceiver& operator=(const OtaReceiver&) = delete;
    bool configure(const char* key_hex, uint8_t panel, const char* identity);
    void challenge(const uint8_t nonce[32]);
    bool begin(const uint8_t header[OTA_HEADER_SIZE], OtaSink& sink);
    bool feed(uint8_t* data, size_t size);
    bool sign(const uint8_t* data, size_t size, uint8_t tag[32]) const;
    void abort();
    bool complete() const { return _complete; }
private:
    uint8_t _key[32] = {}, _nonce[32] = {}, _plain_digest[32] = {}, _wire_digest[32] = {};
    uint8_t _counter[16] = {}, _stream[16] = {};
    uint8_t _vectors[8] = {};
    size_t _vector_size = 0;
    uint8_t _panel = 0;
    uint32_t _remaining = 0;
    uint32_t _image_size = 0;
    size_t _offset = 0, _matched = 0;
    const char* _identity = nullptr;
    OtaSink* _sink = nullptr;
    bool _configured = false, _issued = false, _identity_found = false, _complete = false;
    mbedtls_aes_context _aes;
    mbedtls_sha256_context _plain, _wire;
};
