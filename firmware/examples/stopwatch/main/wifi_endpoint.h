// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

struct WifiEndpoint {
  uint8_t version = 0, channel = 0, length = 0;
  uint8_t bssid[6] = {};
  char ssid[32] = {};
  bool matches(const char* name, size_t size) const {
    uint8_t any = 0;
    for (uint8_t byte : bssid) any |= byte;
    return version == 1 && channel >= 1 && channel <= 14 &&
           length >= 1 && length <= sizeof(ssid) && size == length &&
           any && !(bssid[0] & 1) && std::memcmp(ssid, name, size) == 0;
  }
  bool assign(const char* name, size_t size, const uint8_t* address, int chan) {
    if (!name || !address || !size || size > sizeof(ssid) || chan < 1 || chan > 14) return false;
    *this = WifiEndpoint{};
    version = 1; channel = chan; length = size;
    std::memcpy(ssid, name, size);
    std::memcpy(bssid, address, sizeof(bssid));
    return matches(name, size);
  }
};
static_assert(sizeof(WifiEndpoint) == 41, "Persisted endpoint format must be stable");
