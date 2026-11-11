// SPDX-License-Identifier: MIT
#pragma once
#include <cmath>
#include <cstdint>

// Independent of the device so real gesture sequences can be tested on the host.
struct ScreenRotation {
  float angle = 0;
  bool active = false;
  bool tracking = false, eligible = false, anchored = false;
  int startX = 0, startY = 0;
  uint32_t started = 0;
  float previous = 0;

  static float normalize(float value) {
    if (!std::isfinite(value)) return 0;
    value = std::fmod(value, 360.0f);
    return value < 0 ? value + 360.0f : value;
  }

  static void toDisplayDelta(int& dx, int& dy, float angle) {
    float radians = angle * 3.14159265358979323846f / 180.0f;
    float c = std::cos(radians), s = std::sin(radians);
    int x = std::lround(c * dx + s * dy);
    dy = std::lround(-s * dx + c * dy);
    dx = x;
  }

  // Returns true while this touch belongs to rotation, including its release.
  bool update(bool down, int x, int y, uint32_t now, bool enabled) {
    if (!down) {
      bool consumed = active;
      tracking = eligible = active = anchored = false;
      return consumed;
    }
    if (!tracking) {
      tracking = true; eligible = enabled; started = now;
      startX = x; startY = y;
    }
    if (!enabled) { eligible = false; return active; }
    if (!active) {
      int dx = x - startX, dy = y - startY;
      if (dx * dx + dy * dy > 144) eligible = false;
      if (!eligible || uint32_t(now - started) < 600) return false;
      active = true;
    }
    float dx = x - 233, dy = y - 233;
    // Near the centre the angle is unstable. Re-anchor on leaving this area.
    if (dx * dx + dy * dy < 1600) { anchored = false; return true; }
    float current = std::atan2(dy, dx) * 180.0f / 3.14159265358979323846f;
    if (anchored) {
      float delta = current - previous;
      if (delta > 180) delta -= 360;
      if (delta < -180) delta += 360;
      angle = normalize(angle + delta);
    }
    previous = current; anchored = true;
    return true;
  }
};
