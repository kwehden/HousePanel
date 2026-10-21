#include "ota_protocol.h"
#include <mbedtls/md.h>
#include <string.h>

namespace {
bool equal(const uint8_t* a, const uint8_t* b, size_t size) {
    uint8_t difference = 0;
    for (size_t i = 0; i < size; ++i) difference |= a[i] ^ b[i];
    return difference == 0;
}
bool hmac(const uint8_t key[32], const uint8_t* data, size_t size, uint8_t out[32]) {
    return mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, 32, data, size, out) == 0;
}
int hex(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}
}

OtaReceiver::OtaReceiver() {
    mbedtls_aes_init(&_aes);
    mbedtls_sha256_init(&_plain);
    mbedtls_sha256_init(&_wire);
}
OtaReceiver::~OtaReceiver() {
    mbedtls_aes_free(&_aes);
    mbedtls_sha256_free(&_plain);
    mbedtls_sha256_free(&_wire);
}
bool OtaReceiver::configure(const char* key_hex, uint8_t panel, const char* identity) {
    _configured = false;
    if (!key_hex || strlen(key_hex) != 64 || (panel != 1 && panel != 2) || !identity || !*identity) return false;
    uint8_t any = 0;
    for (size_t i = 0; i < 32; ++i) {
        int hi = hex(key_hex[2 * i]), lo = hex(key_hex[2 * i + 1]);
        if (hi < 0 || lo < 0) return false;
        _key[i] = static_cast<uint8_t>((hi << 4) | lo);
        any |= _key[i];
    }
    if (!any) return false;
    _panel = panel;
    _identity = identity;
    _configured = true;
    return true;
}
void OtaReceiver::challenge(const uint8_t nonce[32]) {
    memcpy(_nonce, nonce, sizeof(_nonce));
    _issued = _configured;
}
bool OtaReceiver::sign(const uint8_t* data, size_t size, uint8_t tag[32]) const {
    uint8_t auth_key[32];
    constexpr char label[] = "housepanel-ota-authentication-v1";
    return _configured && hmac(_key, reinterpret_cast<const uint8_t*>(label), sizeof(label) - 1, auth_key) &&
           hmac(auth_key, data, size, tag);
}
bool OtaReceiver::begin(const uint8_t header[OTA_HEADER_SIZE], OtaSink& sink) {
    if (_sink || !_issued || memcmp(header, "HPOTA1U\n", 8) != 0 || header[8] != _panel ||
        !equal(header + 13, _nonce, 32)) return false;
    uint32_t size = 0;
    for (size_t i = 9; i < 13; ++i) size = (size << 8) | header[i];
    if (size < 256 || size > OTA_MAX_IMAGE) return false;
    uint8_t auth_key[32], tag[32], enc_key[32];
    constexpr char auth_label[] = "housepanel-ota-authentication-v1";
    constexpr char enc_label[] = "housepanel-ota-encryption-v1";
    if (!hmac(_key, reinterpret_cast<const uint8_t*>(auth_label), sizeof(auth_label) - 1, auth_key) ||
        !hmac(auth_key, header, OTA_HEADER_SIZE - 32, tag) || !equal(tag, header + OTA_HEADER_SIZE - 32, 32)) return false;
    // An authenticated attempt consumes its nonce even if storage subsequently fails.
    _issued = false;
    if (!hmac(_key, reinterpret_cast<const uint8_t*>(enc_label), sizeof(enc_label) - 1, enc_key) ||
        mbedtls_aes_setkey_enc(&_aes, enc_key, 256) != 0) return false;
    memcpy(_counter, _nonce, sizeof(_counter));
    memset(_stream, 0, sizeof(_stream));
    memcpy(_plain_digest, header + 45, 32);
    memcpy(_wire_digest, header + 77, 32);
    _remaining = size;
    _image_size = size;
    _offset = _matched = 0;
    _vector_size = 0;
    _complete = _identity_found = false;
    if (mbedtls_sha256_starts_ret(&_plain, 0) != 0 || mbedtls_sha256_starts_ret(&_wire, 0) != 0) return false;
    _sink = &sink;
    if (!_sink->begin()) { abort(); return false; }
    return true;
}
bool OtaReceiver::feed(uint8_t* data, size_t size) {
    if (!_sink || !size || size > _remaining) { abort(); return false; }
    if (mbedtls_sha256_update_ret(&_wire, data, size) != 0) { abort(); return false; }
    // Core 4.5.0 disables the CTR convenience API. Use its AES primitive with
    // the standard big-endian 128-bit CTR counter, cross-checked against Python.
    for (size_t i = 0; i < size; ++i) {
        if (_offset == 0) {
            if (mbedtls_aes_crypt_ecb(&_aes, MBEDTLS_AES_ENCRYPT, _counter, _stream) != 0) { abort(); return false; }
            for (int j = 15; j >= 0; --j) if (++_counter[j]) break;
        }
        data[i] ^= _stream[_offset];
        _offset = (_offset + 1) % 16;
    }
    if (mbedtls_sha256_update_ret(&_plain, data, size) != 0) { abort(); return false; }
    for (size_t i = 0; i < size && _vector_size < sizeof(_vectors); ++i) _vectors[_vector_size++] = data[i];
    if (_vector_size == sizeof(_vectors)) {
        uint32_t stack = 0, reset = 0;
        for (int i = 3; i >= 0; --i) { stack = (stack << 8) | _vectors[i]; reset = (reset << 8) | _vectors[i + 4]; }
        if (stack <= 0x24000000 || stack > 0x24080000 || (stack & 7) || !(reset & 1) ||
            reset < 0x08040000 || reset >= 0x08040000 + _image_size) { abort(); return false; }
    }
    for (size_t i = 0; i < size && !_identity_found; ++i) {
        if (data[i] == static_cast<uint8_t>(_identity[_matched])) ++_matched;
        else _matched = data[i] == static_cast<uint8_t>(_identity[0]) ? 1 : 0;
        if (!_identity[_matched]) _identity_found = true;
    }
    if (!_sink->write(data, size)) { abort(); return false; }
    _remaining -= size;
    if (!_remaining) {
        uint8_t plain[32], wire[32];
        if (mbedtls_sha256_finish_ret(&_plain, plain) != 0 || mbedtls_sha256_finish_ret(&_wire, wire) != 0 ||
            !equal(plain, _plain_digest, 32) || !equal(wire, _wire_digest, 32) || !_identity_found ||
            !_sink->finish()) { abort(); return false; }
        _sink = nullptr;
        _complete = true;
    }
    return true;
}
void OtaReceiver::abort() {
    if (_sink) _sink->abort();
    _sink = nullptr;
    _remaining = 0;
    _complete = false;
}
