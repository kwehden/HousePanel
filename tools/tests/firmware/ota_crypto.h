#pragma once
#include <openssl/aes.h>
#include <openssl/hmac.h>
#include <openssl/sha.h>
#include <string.h>

// Host compatibility for Mbed TLS calls; real AES/HMAC/SHA, not fake digests.
struct mbedtls_aes_context { AES_KEY key; };
struct mbedtls_sha256_context { SHA256_CTX hash; };
using mbedtls_md_info_t = int;
constexpr int MBEDTLS_MD_SHA256 = 1;
inline const mbedtls_md_info_t* mbedtls_md_info_from_type(int) { static int type = 1; return &type; }
inline int mbedtls_md_hmac(const int*, const unsigned char* key, size_t key_size,
                           const unsigned char* data, size_t size, unsigned char* out) {
    unsigned int length = 0;
    return HMAC(EVP_sha256(), key, key_size, data, size, out, &length) && length == 32 ? 0 : -1;
}
inline void mbedtls_aes_init(mbedtls_aes_context*) {}
inline void mbedtls_aes_free(mbedtls_aes_context*) {}
inline int mbedtls_aes_setkey_enc(mbedtls_aes_context* ctx, const unsigned char* key, unsigned int bits) {
    return AES_set_encrypt_key(key, bits, &ctx->key);
}
constexpr int MBEDTLS_AES_ENCRYPT = 1;
inline int mbedtls_aes_crypt_ecb(mbedtls_aes_context* ctx, int, const unsigned char in[16], unsigned char out[16]) {
    AES_encrypt(in, out, &ctx->key);
    return 0;
}
inline int mbedtls_aes_crypt_ctr(mbedtls_aes_context* ctx, size_t size, size_t* offset,
                               unsigned char counter[16], unsigned char block[16],
                               const unsigned char* in, unsigned char* out) {
    for (size_t i = 0; i < size; ++i) {
        if (*offset == 0) {
            AES_encrypt(counter, block, &ctx->key);
            for (int j = 15; j >= 0; --j) if (++counter[j]) break;
        }
        out[i] = in[i] ^ block[*offset];
        *offset = (*offset + 1) % 16;
    }
    return 0;
}
inline void mbedtls_sha256_init(mbedtls_sha256_context*) {}
inline void mbedtls_sha256_free(mbedtls_sha256_context*) {}
inline int mbedtls_sha256_starts_ret(mbedtls_sha256_context* ctx, int) { return SHA256_Init(&ctx->hash) == 1 ? 0 : -1; }
inline int mbedtls_sha256_update_ret(mbedtls_sha256_context* ctx, const unsigned char* data, size_t size) {
    return SHA256_Update(&ctx->hash, data, size) == 1 ? 0 : -1;
}
inline int mbedtls_sha256_finish_ret(mbedtls_sha256_context* ctx, unsigned char* out) {
    return SHA256_Final(out, &ctx->hash) == 1 ? 0 : -1;
}
