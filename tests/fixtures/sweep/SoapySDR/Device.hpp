// SPDX-License-Identifier: MIT
#ifndef RP1_GPCLK_TEST_SOAPY_DEVICE_HPP
#define RP1_GPCLK_TEST_SOAPY_DEVICE_HPP

#include <cstdlib>
#include <map>
#include <string>

#define SOAPY_SDR_RX 0

/* Compile the real renderer without an SDR library. Every hardware call aborts. */
namespace SoapySDR {
using Kwargs = std::map<std::string, std::string>;
struct Stream {};
class Device {
public:
    static Device *make(const Kwargs &) { std::abort(); }
    static void unmake(Device *) { std::abort(); }
    void setSampleRate(int, size_t, double) { std::abort(); }
    void setBandwidth(int, size_t, double) { std::abort(); }
    void setFrequency(int, size_t, double) { std::abort(); }
    void setGainMode(int, size_t, bool) { std::abort(); }
    void setGain(int, size_t, double) { std::abort(); }
    Stream *setupStream(int, const std::string &) { std::abort(); }
    int activateStream(Stream *) { std::abort(); }
    int readStream(Stream *, void *const *, size_t, int &, long long &, long)
    {
        std::abort();
    }
    int deactivateStream(Stream *) { std::abort(); }
    void closeStream(Stream *) { std::abort(); }
};
}

#endif
