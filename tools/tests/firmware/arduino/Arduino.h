#pragma once
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <string>
#include <type_traits>

using byte = uint8_t;
using std::min;
inline uint64_t test_clock_ms = 0;
inline unsigned long millis() { return (unsigned long)test_clock_ms; }
inline void delay(unsigned long value) { test_clock_ms += value; }
inline long random(long maximum) { return maximum ? 42 % maximum : 0; }
inline long random(long minimum, long maximum) { return minimum + random(maximum - minimum); }
inline bool isSpace(char c) { return std::isspace((unsigned char)c); }
inline bool isHexadecimalDigit(char c) { return std::isxdigit((unsigned char)c); }

class String : public std::string {
public:
    String() = default;
    String(const char* value) : std::string(value ? value : "") {}
    String(std::string value) : std::string(value) {}
    bool reserve(size_t count) { std::string::reserve(count); return true; }
    bool concat(char c) { push_back(c); return true; }
    int indexOf(char c) const { auto i = find(c); return i == npos ? -1 : (int)i; }
    String substring(size_t start, size_t end = npos) const { return substr(start, end == npos ? npos : end - start); }
};

class Print {
public:
    virtual ~Print() = default;
    virtual size_t write(uint8_t) = 0;
    virtual size_t write(const uint8_t* data, size_t length) {
        size_t count = 0;
        while (count < length && write(data[count])) ++count;
        return count;
    }
    size_t write(const char* data, size_t length) { return write((const uint8_t*)data, length); }
    size_t print(const char* s) { return write((const uint8_t*)s, strlen(s)); }
    size_t print(const String& s) { return print(s.c_str()); }
    size_t print(char c) { return write((uint8_t)c); }
    template<class T, typename std::enable_if<std::is_integral<T>::value, int>::type = 0>
    size_t print(T value) { return print(std::to_string(value).c_str()); }
    size_t println() { return print("\r\n"); }
    template<class T> size_t println(const T& value) { return print(value) + println(); }
};

class Stream : public Print {
public:
    virtual int available() = 0;
    virtual int read() = 0;
    virtual int read(uint8_t* buffer, size_t length) {
        size_t count = 0;
        while (count < length && available()) buffer[count++] = (uint8_t)read();
        return (int)count;
    }
    virtual int peek() = 0;
    virtual void flush() {}
    int timedRead() { return read(); }
};

class SerialSink : public Print {
public:
    using Print::write;
    size_t write(uint8_t) override { return 1; }
};
inline SerialSink Serial;
