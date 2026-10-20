#include "ota_runtime.h"
#include "ota_update.h"
#include <assert.h>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>

const char* root;
static std::string mapped(const char* path) {
    return std::string(path).rfind("/fs/", 0) == 0 ? std::string(root) + (path + 3) : path;
}
extern "C" FILE* __real_fopen(const char*, const char*);
extern "C" int __real_remove(const char*);
extern "C" int __real_rename(const char*, const char*);
extern "C" FILE* __wrap_fopen(const char* path, const char* mode) { return __real_fopen(mapped(path).c_str(), mode); }
extern "C" int __wrap_remove(const char* path) { return __real_remove(mapped(path).c_str()); }
extern "C" int __wrap_rename(const char* from, const char* to) { return __real_rename(mapped(from).c_str(), mapped(to).c_str()); }

std::shared_ptr<Link> connect(const std::vector<uint8_t>& input) {
    auto link = std::make_shared<Link>();
    link->in = input;
    pending.push_back(link);
    return link;
}
std::string output(std::shared_ptr<Link> link) { return {link->out.begin(), link->out.end()}; }
void run(unsigned count = 10) { while (count--) { ota_loop(); fake_ms += 5; } }
int main(int argc, char** argv) {
    assert(argc == 4);
    root = argv[2];
    std::string mode = argv[3];
    layout_ok = mode != "init_layout";
    bootloader_capable = mode != "init_bootloader";
    storage_ready = mode != "init_storage";
    entropy_ok = mode != "init_entropy";
    ota_init();
    if (mode.rfind("init_", 0) == 0) {
        run(10000);
        assert(listens == 0 && arms == 0 && resets == 0);
        assert(mounts == (mode == "init_storage" ? 1 : 0));
        return 0;
    }
    std::vector<uint8_t> command{'H','P','O','T','A','1','S','\n'};
    command.insert(command.end(), 32, 0xa0);
    auto query = connect(command);
    run();
    assert(!query->connected && mounts == 1);
    std::cout << output(query);
    if (mode == "status_soak") {
        for (unsigned i = 0; i < 10000; ++i) {
            auto repeat = connect(command); run(1);
            assert(!repeat->connected);
        }
        assert(mounts == 1 && arms == 0 && resets == 0);
        return 0;
    }
    std::ifstream file(argv[1], std::ios::binary);
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)), {});
    if (mode == "expired") fake_ms += 60001;
    auto update = connect({data.begin(), data.begin() + 141});
    run();
    if (mode == "bad_auth" || mode == "expired") {
        assert(!update->connected && arms == 0 && resets == 0);
        return 0;
    }
    assert(output(update) == "{\"accepted\":true}\n");
    if (mode == "timeout") { fake_ms += 5001; run(); }
    else if (mode == "disconnect") { update->connected = false; run(); }
    else if (mode == "wifi_loss") { wifi_up = false; run(); wifi_up = true; run(); }
    else {
        arm_failure = mode == "arm_failure";
        update->in.insert(update->in.end(), data.begin() + 141, data.end());
        run(100);
    }
    if (mode == "ok") {
        assert(arms == 1 && resets == 1 && output(update) == "{\"accepted\":true}\n{\"ok\":true}\n");
        std::ifstream staged(std::string(root) + "/UPDATE.BIN", std::ios::binary);
        std::vector<uint8_t> image((std::istreambuf_iterator<char>(staged)), {});
        assert(!image.empty());
    } else if (mode == "arm_failure") {
        assert(arms == 1 && resets == 0);
    } else {
        assert(arms == 0 && resets == 0);
        std::ifstream partial(std::string(root) + "/UPDATE.PART");
        assert(!partial.good());
    }
    assert(mounts == 1 && !update->connected);
}
