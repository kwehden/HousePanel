#include "ota_protocol.h"
#include <assert.h>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

struct Sink : OtaSink {
    std::vector<uint8_t> image;
    int begins = 0, finishes = 0, aborts = 0;
    bool fail_begin = false, fail_write = false, fail_finish = false;
    bool begin() override { ++begins; return !fail_begin; }
    bool write(const uint8_t* data, size_t size) override {
        if (fail_write) return false;
        image.insert(image.end(), data, data + size);
        return true;
    }
    bool finish() override { ++finishes; return !fail_finish; }
    void abort() override { ++aborts; image.clear(); }
};
int main(int argc, char** argv) {
    assert(argc == 6);
    std::ifstream file(argv[1], std::ios::binary);
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)), {});
    assert(data.size() >= OTA_HEADER_SIZE);
    std::string mode = argv[4];
    static_assert(sizeof(OtaReceiver) < 1024, "OTA receive state must remain bounded");
    OtaReceiver receiver;
    assert(!receiver.configure("", 1, "bad"));
    assert(!receiver.configure(std::string(64, '0').c_str(), 1, "bad"));
    bool primary = std::string(argv[5]) == "primary";
    assert(receiver.configure(argv[2], primary ? 1 : 2, primary ?
        "HousePanel identity:primary:housepanel:end" : "HousePanel identity:panel-2:housepanel-2:end"));
    uint8_t nonce[32];
    for (size_t i = 0; i < 32; ++i) nonce[i] = static_cast<uint8_t>(i);
    receiver.challenge(nonce);
    Sink sink;
    sink.fail_begin = mode == "begin_failure";
    sink.fail_write = mode == "write_failure";
    sink.fail_finish = mode == "finish_failure";
    if (mode == "header_reject") {
        assert(!receiver.begin(data.data(), sink));
        assert(sink.begins == 0);
        return 0;
    }
    if (mode == "begin_failure") {
        assert(!receiver.begin(data.data(), sink));
        assert(sink.aborts == 1);
        assert(!receiver.begin(data.data(), sink));
        return 0;
    }
    assert(receiver.begin(data.data(), sink));
    if (mode == "cancel") {
        assert(receiver.feed(data.data() + OTA_HEADER_SIZE, 7));
        receiver.abort();
        assert(!receiver.complete() && sink.finishes == 0 && sink.aborts == 1);
        assert(!receiver.begin(data.data(), sink));
        return 0;
    }
    if (mode == "oversize") {
        assert(!receiver.feed(data.data() + OTA_HEADER_SIZE, data.size()));
        assert(sink.finishes == 0 && sink.aborts == 1);
        return 0;
    }
    bool ok = true;
    // Deliberately split AES blocks and the embedded identity across calls.
    for (size_t i = OTA_HEADER_SIZE; i < data.size() && ok; i += 7) {
        size_t size = data.size() - i < 7 ? data.size() - i : 7;
        ok = receiver.feed(data.data() + i, size);
    }
    if (mode == "body_reject" || mode == "write_failure" || mode == "finish_failure") {
        assert(!ok && !receiver.complete() && sink.aborts == 1);
        if (mode == "body_reject") assert(sink.finishes == 0);
    } else {
        assert(ok && receiver.complete() && sink.finishes == 1 && sink.aborts == 0);
        std::ofstream output(argv[3], std::ios::binary);
        output.write(reinterpret_cast<const char*>(sink.image.data()), sink.image.size());
    }
    // A second connection cannot replay the successful or failed authorization.
    assert(!receiver.begin(data.data(), sink));
}
