// SPDX-License-Identifier: MIT
// Standalone StopWatch voice client.
#include <M5Unified.h>
#include <cmath>
#include <cJSON.h>
#include "navigation.h"
#include "rotation.h"
#include <Preferences.h>
#include <mbedtls/base64.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <deque>
#include <vector>
#ifdef XANGI_STOPWATCH_TAILNET
#include <WiFi.h>
#include <esp_wifi.h>
#include "wifi_endpoint.h"
#include <atomic>
#include <time.h>
#include "microlink.h"
#if __has_include("tailnet_secrets.h")
#include "tailnet_secrets.h"
#else
#include "tailnet_secrets.example.h"
#endif
#ifndef XANGI_WIFI_COUNTRY_CODE
#define XANGI_WIFI_COUNTRY_CODE ""
#endif
#endif

namespace {
constexpr size_t MAX_AUDIO = 600000, MAX_IMAGE = 100000;
struct Audio { uint8_t* data; size_t size; };
std::deque<Audio> audio;
std::vector<uint8_t> frames[64];
SemaphoreHandle_t guard;
bool playing = false;
constexpr uint32_t MIC_RATE = 16000, MIC_MAX_SECONDS = 30;
constexpr size_t MIC_BLOCK_SAMPLES = 256, MIC_READ_MAX_BYTES = 16384;
int16_t* micSamples = nullptr;
size_t micCount = 0;
bool micButtons = false, micStart = false, micRecording = false;
bool micFinish = false, micCancel = false, micReady = false;
uint32_t micId = 0;
String micError;

bool characterNextPending = false;
bool conversationBusy = false, stopPending = false, stopRequested = false;
int batteryPercent = -1;
bool batteryCharging = false;
String batteryPosition = "right";
bool textVisible = true;
uint32_t nextBatteryRead = 0;
bool faceShown = false;
uint32_t nextBootDraw = 0;
String bootStage = "起動しています";

volatile bool networkActive = false;
#ifdef XANGI_STOPWATCH_TAILNET
microlink_t* networkClient = nullptr;
volatile uint32_t networkAttempts = 0;
std::atomic<uint32_t> wifiAttempts{0};
std::atomic<uint8_t> wifiDisconnectReason{0};
std::atomic<uint32_t> wifiDisconnectEvents{0}, wifiRadioRestarts{0}, wifiCachedAttempts{0};
std::atomic<int32_t> wifiScanCount{-3}, wifiScanChannel{0}, wifiScanRssi{-127};
std::atomic<int32_t> wifiScanHidden{0}, wifiScanChannels{0}, wifiSavedApAuth{-1}, wifiSavedApChannel{0};
std::atomic<bool> wifiSavedApSeen{false};
std::atomic<int> wifiCountryError{0};
#endif
uint32_t epoch = 0, nextFrame = 0;
int volume = 25, frameIndex = 0, interval = 0;
Preferences settings;
M5Canvas canvas(&M5.Display);
bool canvasReady = false;
M5Canvas screenCanvas(&M5.Display);
bool rotationReady = false;
ScreenRotation screenRotation;
float savedScreenAngle = 0;
uint32_t lastRotationDraw = 0;
int lastFrame = 0;
String voiceLabel, captionRole;
std::vector<String> captionLines;
size_t captionPage = 0;
int captionIndex = 0;
uint32_t nextCaption = 0;
uint32_t captionPageMs = 4000;

std::vector<int> animation;
struct Lock { Lock() { xSemaphoreTakeRecursive(guard, portMAX_DELAY); }
              ~Lock() { xSemaphoreGiveRecursive(guard); } };
// Compose every screen upright, then rotate the complete frame once.
void presentCanvas() {
  if (screenRotation.active) {
    canvas.fillRoundRect(123, 175, 220, 48, 12, TFT_BLACK);
    canvas.setFont(&fonts::lgfxJapanGothic_24);
    canvas.setTextDatum(middle_center); canvas.setTextColor(TFT_CYAN);
    canvas.drawString("回転 " + String(screenRotation.angle, 0) + "°", 233, 199);
  }
  if (rotationReady && screenRotation.angle != 0) {
    screenCanvas.fillScreen(TFT_BLACK);
    canvas.pushRotateZoom(&screenCanvas, 233, 233, screenRotation.angle, 1.0f, 1.0f);
    screenCanvas.pushSprite(0, 0);
  } else {
    canvas.pushSprite(0, 0);
  }
}
#include "dashboard.h"
void setBootStage(const char* text) { Lock lock; bootStage = text; }
template<class Display> void drawBattery(Display& display) {
  if (batteryPosition == "hidden" || (faceShown && !textVisible)) return;
  int x = batteryPosition == "left" ? 62 : batteryPosition == "center" ? 167 : 272;
  int y = batteryPosition == "center" ? 32 : 88;
  display.fillRoundRect(x, y, 132, 38, 12, TFT_BLACK);
  display.drawRoundRect(x + 8, y + 10, 34, 18, 3, TFT_WHITE);
  display.fillRect(x + 42, y + 15, 3, 8, TFT_WHITE);
  if (batteryPercent > 0)
    display.fillRect(x + 11, y + 13, std::max(1, 28 * batteryPercent / 100), 12, TFT_GREEN);
  if (batteryCharging) {
    display.fillTriangle(x + 29, y + 9, x + 20, y + 20, x + 27, y + 20, TFT_YELLOW);
    display.fillTriangle(x + 23, y + 18, x + 30, y + 18, x + 21, y + 29, TFT_YELLOW);
  }
  display.setTextDatum(middle_center);
  display.setFont(&fonts::lgfxJapanGothic_20);
  display.setTextColor(TFT_WHITE);
  display.drawString(batteryPercent < 0 ? "--%" : String(batteryPercent) + "%", x + 87, y + 19);
}
template<class Display> void drawBootScreen(Display& display) {
  display.fillScreen(0x0841);
  display.setTextDatum(middle_center);
  display.setTextColor(TFT_WHITE);
  display.setFont(&fonts::lgfxJapanGothic_40);
  display.drawString("xangi-stopwatch", 233, 150);
  display.setFont(&fonts::lgfxJapanGothic_28);
  display.setTextColor(TFT_CYAN);
  display.drawString(bootStage, 233, 245);
  display.setFont(&fonts::lgfxJapanGothic_24);
  display.setTextColor(TFT_WHITE);
  display.drawString(String(millis() / 1000) + " 秒経過", 233, 294);
  drawBattery(display);
  if (millis() > 30000 && bootStage != "接続設定がありません" && bootStage != "通信の初期化に失敗") {
    display.drawString("接続に時間がかかっています", 233, 339);
    display.drawString("自動で再試行します", 233, 372);
  }
}
void showBootScreen() {
  Lock lock;
  if (faceShown || dashboardView || millis() < nextBootDraw) return;
  nextBootDraw = millis() + 1000;
  if (canvasReady) { drawBootScreen(canvas); presentCanvas(); }
  else drawBootScreen(M5.Display);
}
void showFrame(int slot) {
  if (slot >= 0 && slot < 64 && !frames[slot].empty()) {
    faceShown = true;
    lastFrame = slot;
    if (dashboardView) return;
    const auto& data = frames[slot];
    if (canvasReady) {
      canvas.fillScreen(TFT_BLACK);
      canvas.drawJpg(data.data(), data.size(), 0, 0, 466, 466, 0, 0, 1.0f, 1.0f, middle_center);
      if (textVisible && voiceLabel.length()) {
        canvas.fillRoundRect(83, 378, 300, 48, 12, TFT_BLACK);
        canvas.setFont(&fonts::lgfxJapanGothic_24);
        canvas.setTextColor(TFT_WHITE); canvas.setTextDatum(middle_center);
        canvas.drawString(voiceLabel, 233, 402);
      }
      if (!captionLines.empty()) {
        canvas.fillRoundRect(51, 274, 364, 98, 14, TFT_WHITE);
        canvas.setTextColor(TFT_BLACK); canvas.setTextDatum(top_left);
        canvas.setFont(&fonts::lgfxJapanGothic_16);
        String title = captionRole == "U" ? "あなた" : "返答";
        if (captionRole == "A" && captionIndex > 0) title += " " + String(captionIndex) + "文目";
        if (captionLines.size() > 2) title += " " + String(captionPage + 1) + "/" + String((captionLines.size() + 1) / 2) + "頁";
        canvas.drawString(title, 65, 280);
        canvas.setFont(&fonts::lgfxJapanGothic_28);
        for (size_t row = 0; row < 2 && captionPage * 2 + row < captionLines.size(); ++row)
          canvas.drawString(captionLines[captionPage * 2 + row], 65, 303 + row * 30);
      }
      drawBattery(canvas);
      presentCanvas();
    } else {
      M5.Display.drawJpg(data.data(), data.size(), 0, 0, 466, 466, 0, 0, 1.0f, 1.0f, middle_center);
      drawBattery(M5.Display);
    }
  }
}
void stopAudio() {
  Lock lock;
  ++epoch;
  M5.Speaker.stop();
  for (auto& item : audio) free(item.data);
  audio.clear();
  interval = 0;
  animation.clear();
}
void micLabel(const char* text) {
  Lock lock;
  voiceLabel = text;
  showFrame(lastFrame);
}
void microphone(void*) {
  for (;;) {
    bool start;
    { Lock lock; start = micStart; micStart = false; }
    if (!start) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
    stopAudio();
    while (M5.Speaker.isPlaying()) vTaskDelay(pdMS_TO_TICKS(5));
    M5.Speaker.end();
    { Lock lock;
      micReady = false; micCount = 0; micError = "";
      micFinish = false; micCancel = false; micRecording = true;
    }
    micLabel("A: 送信 B: 停止");
    bool ok = micSamples && M5.Mic.begin();
    while (ok) {
      { Lock lock;
        if (micFinish || micCancel) break;
        if (micCount + MIC_BLOCK_SAMPLES > MIC_RATE * MIC_MAX_SECONDS) {
          micCancel = true; micError = "recording limit reached"; break;
        }
      }
      ok = M5.Mic.record(micSamples + micCount, MIC_BLOCK_SAMPLES, MIC_RATE);
      while (M5.Mic.isRecording()) vTaskDelay(pdMS_TO_TICKS(2));
      if (ok) { Lock lock; micCount += MIC_BLOCK_SAMPLES; }
    }
    M5.Mic.end();
    M5.Speaker.begin(); M5.Speaker.setVolume(volume);
    { Lock lock;
      micRecording = false;
      micReady = ok && micFinish && !micCancel && micCount >= MIC_RATE / 4;
      if (!ok) micError = "microphone unavailable";
      conversationBusy = micReady;
      if (micReady) ++micId;
    }
    micLabel(micReady ? "返答待ち B: 停止" : "A: 録音 B: キャラ");
  }
}
void player(void*) {
  for (;;) {
    Audio item{};
    {
      Lock lock;
      if (!audio.empty() && !micRecording && !micStart) {
        item = audio.front(); audio.pop_front();
        playing = M5.Speaker.playWav(item.data, item.size, 1, 0, true);
      }
    }
    if (!item.data) { vTaskDelay(pdMS_TO_TICKS(10)); continue; }
    while (M5.Speaker.isPlaying()) vTaskDelay(pdMS_TO_TICKS(10));
    {
      Lock lock;
      playing = false;
      free(item.data);
    }
  }
}
struct Channel {
#ifdef XANGI_STOPWATCH_TAILNET
  microlink_tcp_socket_t* socket = nullptr;
#endif
  bool net = false;
  int read(uint8_t* out, size_t count, uint32_t timeout) {
#ifdef XANGI_STOPWATCH_TAILNET
    if (net) return microlink_tcp_recv(socket, out, count, timeout);
#endif
    uint32_t start = millis();
    while (!Serial.available() && millis() - start < timeout) delay(1);
    const size_t available = Serial.available();
    return Serial.read(out, std::min(count, available));
  }
  bool line(const String& value) {
#ifdef XANGI_STOPWATCH_TAILNET
    if (net) {
      String data = value + "\n";
      return microlink_tcp_send(socket, data.c_str(), data.length()) == ESP_OK;
    }
#endif
    Serial.println(value); return true;
  }
};
void updateButtons() {
  M5.update();
  const auto& touch = M5.Touch.getDetail();
  {
    Lock lock;
    bool wasRotating = screenRotation.active;
    bool consumed = screenRotation.update(touch.isPressed(), touch.x, touch.y, millis(),
                                         rotationReady);
    if (consumed) {
      bool finished = !touch.isPressed();
      if (finished && savedScreenAngle != screenRotation.angle) {
        if (settings.putFloat("screenAngle", screenRotation.angle)) savedScreenAngle = screenRotation.angle;
      }
      if (finished || !wasRotating || uint32_t(millis() - lastRotationDraw) >= 50) {
        lastRotationDraw = millis();
        if (dashboardView) drawDashboard();
        else if (faceShown) showFrame(lastFrame);
        else { nextBootDraw = 0; showBootScreen(); }
      }
    }
    if (touch.wasReleased() && !consumed) {
      int dx = touch.distanceX(), dy = touch.distanceY();
      ScreenRotation::toDisplayDelta(dx, dy, rotationReady ? screenRotation.angle : 0);
      int moved = canvasReady ? navigateDashboard(dx, dy, dashboardView, dashboardPage, dashboardPages()) : 0;
      if (moved) {
        if (dashboardView) drawDashboard();
        else { showFrame(lastFrame); nextBootDraw = 0; }
      } else if (touch.wasClicked() && std::abs(touch.distanceX()) < 20 && std::abs(touch.distanceY()) < 20 && !dashboardView && faceShown) {
        textVisible = !textVisible;
        settings.putBool("textVisible", textVisible);
        showFrame(lastFrame);
      }
    }
  }
  if (M5.BtnA.wasPressed()) {
    Lock lock;
    if (micButtons && !stopRequested && !conversationBusy) {
      if (micRecording) micFinish = true;
      else if (!micReady && !micStart) micStart = true;
    }
  }
  if (M5.BtnB.wasPressed()) {
    Lock lock;
    if (micRecording || micStart) {
      micCancel = true; micReady = false; micStart = false;
    } else if (conversationBusy || playing || !audio.empty() || stopRequested) {
      stopRequested = true; stopPending = true;
      micReady = false; micStart = false;
      stopAudio();
      micLabel("停止しました");
    } else {
      characterNextPending = true;
    }
  }
}
bool receive(Channel& io, uint8_t* data, size_t size) {
  size_t offset = 0;
  uint32_t last = millis();
  while (offset < size && millis() - last < 10000) {
    if (!io.net) updateButtons();
    int n = io.read(data + offset, std::min(size - offset, size_t(4096)), 50);
    if (n < 0) return false;
    if (n > 0) { offset += n; last = millis(); }
    vTaskDelay(pdMS_TO_TICKS(1));
  }
  return offset == size;
}
#ifdef XANGI_STOPWATCH_TAILNET
constexpr int WIFI_PROFILE_COUNT = 5;
uint32_t wifiRestartAt = 0;
String wifiKey(int slot, const char* suffix) { return "w" + String(slot) + suffix; }
String hexString(const String& value) {
  const char* digits = "0123456789abcdef"; String result;
  for (size_t i = 0; i < value.length(); ++i) { uint8_t c = value[i]; result += digits[c >> 4]; result += digits[c & 15]; }
  return result;
}
bool unhex(const String& value, String& result) {
  if (value.length() % 2) return false;
  auto digit = [](char c) -> int { if (c >= '0' && c <= '9') return c - '0'; if (c >= 'a' && c <= 'f') return c - 'a' + 10; return -1; };
  for (size_t i = 0; i < value.length(); i += 2) {
    int a = digit(value[i]), b = digit(value[i + 1]);
    if (a < 0 || b < 0 || !(a || b)) return false;
    result += char((a << 4) | b);
  }
  return true;
}
bool wifiBuiltIn(int slot) { return slot == 0 && XANGI_TAILNET_WIFI_SSID[0]; }
String wifiCredential(int slot, bool password) {
  String key = wifiKey(slot, "c");
  if (settings.isKey(key.c_str())) {
    String value = settings.getString(key.c_str(), ""), decoded;
    int comma = value.indexOf(',');
    if (comma >= 0) unhex(password ? value.substring(comma + 1) : value.substring(0, comma), decoded);
    return decoded;
  }
  if (slot == 0 && !settings.isKey(wifiKey(slot, "s").c_str())) return String(password ? XANGI_TAILNET_WIFI_PASSWORD : XANGI_TAILNET_WIFI_SSID);
  return settings.getString(wifiKey(slot, password ? "p" : "s").c_str(), "");
}
String wifiSSID(int slot) { return wifiCredential(slot, false); }
String wifiPassword(int slot) { return wifiCredential(slot, true); }

#endif
bool command(Channel& io, const String& line) {
#ifdef XANGI_STOPWATCH_TAILNET
  if (line.startsWith("WIFI_SETUP:")) {
    Lock lock;
    if (io.net) return io.line("{\"status\":\"error\",\"error\":\"USB required\"}");
    if (conversationBusy || micRecording || micReady || micStart || playing || !audio.empty())
      return io.line("{\"status\":\"error\",\"error\":\"device busy\"}");
    int comma = line.indexOf(',', 11); String ssid, password;
    if (comma < 0 || !unhex(line.substring(11, comma), ssid) || !unhex(line.substring(comma + 1), password) || ssid.isEmpty() || ssid.length() > 32 || password.length() > 63 || (password.length() > 0 && password.length() < 8))
      return io.line("{\"status\":\"error\",\"error\":\"invalid Wi-Fi credentials\"}");
    int slot = -1;
    for (int i = 0; i < WIFI_PROFILE_COUNT; ++i) {
      String saved = wifiSSID(i);
      if (saved == ssid) { slot = i; break; }
      if (saved.isEmpty() && slot < 0) slot = i;
    }
    if (slot < 0) return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi list full\"}");
    // One NVS string commits SSID and password together; legacy slots remain readable.
    if (!settings.putString(wifiKey(slot, "c").c_str(), line.substring(11)) || !settings.putUChar("wifiSlot", slot))
      return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi save failed\"}");
    wifiRestartAt = millis() + 1500;
    return io.line("{\"status\":\"ok\"}");
  }
  if (line == "WIFI_LIST") {
    Lock lock;
    String result = "{\"status\":\"ok\",\"usb_setup\":true,\"active\":" + String(settings.getUChar("wifiSlot", 0)) + ",\"profiles\":[";
    bool comma = false;
    for (int i = 0; i < WIFI_PROFILE_COUNT; ++i) {
      String ssid = wifiSSID(i); if (ssid.isEmpty()) continue;
      if (comma) result += ","; comma = true;
      result += "{\"id\":" + String(i) + ",\"ssid_hex\":\"" + hexString(ssid) + "\",\"built_in\":" + (wifiBuiltIn(i) ? "true" : "false") + "}";
    }
    return io.line(result + "]}");
  }
  if (line.startsWith("WIFI_RENAME:")) {
    Lock lock;
    // Rename only an inactive saved profile; retain its password in NVS.
    int comma = line.indexOf(',', 12);
    String value = line.substring(12, comma), ssid;
    if (comma != 13 || value.length() != 1 || value[0] < '1' || value[0] >= '0' + WIFI_PROFILE_COUNT || !unhex(line.substring(comma + 1), ssid) || ssid.isEmpty() || ssid.length() > 32)
      return io.line("{\"status\":\"error\",\"error\":\"invalid Wi-Fi rename\"}");
    int slot = value[0] - '0';
    if (wifiSSID(slot).isEmpty() || slot == settings.getUChar("wifiSlot", 0))
      return io.line("{\"status\":\"error\",\"error\":\"cannot rename missing or active Wi-Fi\"}");
    for (int i = 0; i < WIFI_PROFILE_COUNT; ++i) {
      if (i != slot && wifiSSID(i) == ssid)
        return io.line("{\"status\":\"error\",\"error\":\"SSID already saved\"}");
    }
    if (settings.putString(wifiKey(slot, "c").c_str(), hexString(ssid) + "," + hexString(wifiPassword(slot))) == 0)
      return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi save failed\"}");
    return io.line("{\"status\":\"ok\"}");
  }
  if (line.startsWith("WIFI_ADD:")) {
    Lock lock;
    int comma = line.indexOf(',', 9); String ssid, password;
    if (comma < 0 || !unhex(line.substring(9, comma), ssid) || !unhex(line.substring(comma + 1), password) || ssid.isEmpty() || ssid.length() > 32 || password.length() > 63 || (password.length() > 0 && password.length() < 8))
      return io.line("{\"status\":\"error\",\"error\":\"invalid Wi-Fi credentials\"}");
    int freeSlot = -1;
    for (int i = 0; i < WIFI_PROFILE_COUNT; ++i) {
      String saved = wifiSSID(i);
      if (saved == ssid) return io.line("{\"status\":\"error\",\"error\":\"SSID already saved\"}");
      if (saved.isEmpty() && freeSlot < 0) freeSlot = i;
    }
    if (freeSlot < 0) return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi list full\"}");
    // Password first; the SSID makes a complete profile visible.
    if (!password.isEmpty() && settings.putString(wifiKey(freeSlot, "p").c_str(), password) == 0)
      return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi save failed\"}");
    if (password.isEmpty()) settings.remove(wifiKey(freeSlot, "p").c_str());
    if (settings.putString(wifiKey(freeSlot, "s").c_str(), ssid) == 0)
      return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi save failed\"}");
    return io.line("{\"status\":\"ok\"}");
  }
  if (line.startsWith("WIFI_SELECT:") || line.startsWith("WIFI_DELETE:")) {
    Lock lock;
    String value = line.substring(12);
    if (value.length() != 1 || value[0] < '0' || value[0] >= '0' + WIFI_PROFILE_COUNT)
      return io.line("{\"status\":\"error\",\"error\":\"invalid Wi-Fi id\"}");
    int slot = value[0] - '0';
    if (wifiSSID(slot).isEmpty()) return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi not found\"}");
    if (line.startsWith("WIFI_DELETE:")) {
      if (wifiBuiltIn(slot) || slot == settings.getUChar("wifiSlot", 0)) return io.line("{\"status\":\"error\",\"error\":\"cannot delete active or built-in Wi-Fi\"}");
      if (!settings.remove(wifiKey(slot, settings.isKey(wifiKey(slot, "c").c_str()) ? "c" : "s").c_str())) return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi delete failed\"}");
      settings.remove(wifiKey(slot, "s").c_str());
      settings.remove(wifiKey(slot, "p").c_str());
      settings.remove("wifiLastAP");
    } else {
      if (micRecording || micReady || micStart || playing || !audio.empty()) return io.line("{\"status\":\"error\",\"error\":\"device busy\"}");
      if (settings.putUChar("wifiSlot", slot) == 0) return io.line("{\"status\":\"error\",\"error\":\"Wi-Fi save failed\"}");
      wifiRestartAt = millis() + 1500;
    }
    return io.line("{\"status\":\"ok\"}");
  }
#endif

  if (line.startsWith("CAPTION_INDEX:")) {
    Lock lock; captionIndex = line.substring(14).toInt();
    return io.line("{\"status\":\"ok\"}");
  }
  if (line.startsWith("CAPTION_MS:")) {
    Lock lock;
    captionPageMs = std::max(500L, std::min(30000L, line.substring(11).toInt()));
    return io.line("{\"status\":\"ok\"}");
  }
  if (line.startsWith("CAPTION:U:") || line.startsWith("CAPTION:A:")) {
    Lock lock;
    captionRole = line.substring(8, 9); captionLines.clear(); captionPage = 0;
    if (captionRole == "U") captionPageMs = 4000;
    String text = line.substring(10), row;
    int chars = 0;
    for (size_t i = 0; i < text.length();) {
      uint8_t c = text[i];
      size_t n = c < 0x80 ? 1 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
      if (i + n > text.length()) break;
      row += text.substring(i, i + n); i += n;
      if (++chars == 12) { captionLines.push_back(row); row = ""; chars = 0; }
    }
    if (row.length()) captionLines.push_back(row);
    nextCaption = millis() + captionPageMs;
    showFrame(lastFrame);
    return io.line("{\"status\":\"ok\"}");
  }
  if (line == "MIC_BUTTON:on" || line == "MIC_BUTTON:off") {
    Lock lock; micButtons = line.endsWith(":on");
    if (!micButtons) { micCancel = true; micReady = false; micStart = false; }
    if (!micButtons && conversationBusy && !stopRequested) micLabel("会話中 B: 停止");
    if (micButtons) { conversationBusy = false; stopRequested = false; micLabel("A: 録音 B: キャラ"); }
    return io.line("{\"status\":\"ok\"}");
  }
  if (line == "MIC_START") {
    Lock lock;
    if (!micButtons || micStart || micRecording || micReady || stopRequested || conversationBusy)
      return io.line("{\"status\":\"error\",\"error\":\"microphone busy or disabled\"}");
    micStart = true;
    return io.line("{\"status\":\"ok\"}");
  }
  if (line == "MIC_STOP" || line == "MIC_CANCEL" || line == "MIC_CLEAR") {
    Lock lock;
    if (line == "MIC_STOP") micFinish = true;
    else { micCancel = true; micReady = false; micStart = false; }
    return io.line("{\"status\":\"ok\"}");
  }
  if (line.startsWith("MIC_READ_B64:")) {
    Lock lock;
    int comma = line.indexOf(',');
    int offset = line.substring(13, comma).toInt(), count = line.substring(comma + 1).toInt();
    if (!micReady || comma < 0 || offset < 0 || count < 1 || count > 32768 || size_t(offset + count) > micCount * 2)
      return io.line("{\"status\":\"error\",\"error\":\"invalid microphone read\"}");
    std::vector<unsigned char> encoded(4 * ((count + 2) / 3) + 1);
    size_t length = 0;
    if (mbedtls_base64_encode(encoded.data(), encoded.size(), &length, reinterpret_cast<uint8_t*>(micSamples) + offset, count) != 0)
      return io.line("{\"status\":\"error\",\"error\":\"encoding failed\"}");
    encoded[length] = 0;
    return io.line(String("{\"status\":\"ok\",\"pcm\":\"") + reinterpret_cast<char*>(encoded.data()) + "\"}");
  }
  if (line.startsWith("MIC_READ:")) {
    Lock lock;
    int comma = line.indexOf(',');
    int offset = line.substring(9, comma).toInt();
    int count = line.substring(comma + 1).toInt();
    if (!micReady || comma < 0 || offset < 0 || count < 1 || size_t(count) > MIC_READ_MAX_BYTES || size_t(offset + count) > micCount * 2)
      return io.line("{\"status\":\"error\",\"error\":\"invalid microphone read\"}");
    String hex; hex.reserve(count * 2);
    const char* digits = "0123456789abcdef";
    const auto* data = reinterpret_cast<uint8_t*>(micSamples) + offset;
    for (int i = 0; i < count; ++i) { hex += digits[data[i] >> 4]; hex += digits[data[i] & 15]; }
    return io.line(String("{\"status\":\"ok\",\"pcm\":\"") + hex + "\"}");
  }

#ifdef XANGI_STOPWATCH_TAILNET
  if (line == "NET_STATUS") {
    wifi_country_t country{};
    bool countryReady = esp_wifi_get_country(&country) == ESP_OK;
    return io.line(String("{\"wifi_status\":") + int(WiFi.status()) + ",\"has_ip\":" + (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0,0,0,0) ? "true" : "false") + ",\"clock_ready\":" + (time(nullptr) >= 1700000000 ? "true" : "false") + ",\"tailnet_state\":" + (networkClient ? int(microlink_get_state(networkClient)) : 0) + ",\"peer_count\":" + (networkClient ? microlink_get_peer_count(networkClient) : 0) + ",\"server_connected\":" + (networkActive ? "true" : "false") + ",\"wifi_attempts\":" + wifiAttempts.load() + ",\"wifi_disconnect_reason\":" + int(wifiDisconnectReason.load()) + ",\"wifi_country_error\":" + wifiCountryError.load() + ",\"wifi_country_first\":" + (countryReady ? int(country.schan) : 0) + ",\"wifi_country_channels\":" + (countryReady ? int(country.nchan) : 0) + ",\"wifi_scan_hidden\":" + wifiScanHidden.load() + ",\"wifi_scan_channels\":" + wifiScanChannels.load() + ",\"wifi_saved_ap_seen\":" + (wifiSavedApSeen.load() ? "true" : "false") + ",\"wifi_saved_ap_auth\":" + wifiSavedApAuth.load() + ",\"wifi_saved_ap_channel\":" + wifiSavedApChannel.load() + ",\"wifi_cached_attempts\":" + wifiCachedAttempts.load() + ",\"wifi_radio_restarts\":" + wifiRadioRestarts.load() + ",\"wifi_scan_count\":" + wifiScanCount.load() + ",\"wifi_scan_channel\":" + wifiScanChannel.load() + ",\"wifi_scan_rssi\":" + wifiScanRssi.load() + ",\"tcp_attempts\":" + networkAttempts + "}");
  }
#endif
  if (line == "STATUS") {
    Lock lock;
    return io.line(String("{\"state\":\"ready\",\"version\":\"stopwatch-voice-0.8\",\"device\":\"stopwatch\",\"dashboard\":true,\"display_width\":466,\"display_height\":466,\"servo\":false,\"camera\":false,\"puzzle\":false,\"stack_led\":false,\"mic_button\":false,\"head_touch_avatar\":false,\"head_pet_sound\":false,\"caption\":true,\"caption_index\":true,\"mic_base64\":true,\"microphone\":true,\"character_button\":true,\"conversation_stop\":true,\"mic_read_max\":16384,\"playing\":") + (playing ? "true" : "false") + ",\"queued\":" + audio.size() + ",\"volume\":" + volume + ",\"battery_position\":\"" + batteryPosition + "\",\"text_visible\":" + (textVisible ? "true" : "false") + ",\"battery_percent\":" + batteryPercent + ",\"battery_charging\":" + (batteryCharging ? "true" : "false") + ",\"mic_recording\":" + (micRecording ? "true" : "false") + ",\"mic_ready\":" + (micReady ? "true" : "false") + ",\"mic_id\":" + micId + ",\"mic_bytes\":" + micCount * 2 + "}");
  }
  if (line.startsWith("DASH:")) {
    long size = line.substring(5).toInt();
    if (size <= 0 || size > 49152) return io.line("{\"status\":\"error\",\"error\":\"invalid dashboard size\"}");
    auto* data = static_cast<uint8_t*>(ps_malloc(size + 1));
    if (!data) return io.line("{\"status\":\"error\",\"error\":\"out of memory\"}");
    io.line("{\"status\":\"ready\"}");
    if (!receive(io, data, size)) { free(data); return false; }
    data[size] = 0;
    bool ok = acceptDashboard(data, size + 1); free(data);
    return io.line(ok ? "{\"status\":\"ok\"}" : "{\"status\":\"error\",\"error\":\"invalid dashboard\"}");
  }
  if (line == "AUDIO_STOP") {
    stopAudio();
    // Do not acknowledge until the speaker task has stopped accessing its buffer.
    uint32_t started = millis();
    while (M5.Speaker.isPlaying() && millis() - started < 2000) delay(1);
    if (M5.Speaker.isPlaying()) return io.line("{\"status\":\"error\",\"error\":\"speaker stop timeout\"}");
    return io.line("{\"status\":\"ok\",\"audio_stopped\":true}");
  }
  if (line.startsWith("WAV:") || line.startsWith("SIMG:") || line.startsWith("IMAGE:")) {
    bool wav = line.startsWith("WAV:");
    int slot = 0;
    long requested = 0;
    if (line.startsWith("SIMG:")) {
      int comma = line.indexOf(',');
      if (comma > 5) { slot = line.substring(5, comma).toInt(); requested = line.substring(comma + 1).toInt(); }
    } else requested = line.substring(line.indexOf(':') + 1).toInt();
    if (slot < 0 || slot >= 64 || requested <= 0 || size_t(requested) > (wav ? MAX_AUDIO : MAX_IMAGE))
      return io.line("{\"status\":\"error\",\"error\":\"invalid payload size or slot\"}");
    uint32_t receiveEpoch;
    {
      Lock lock;
      receiveEpoch = epoch;
      if (wav && stopRequested) return io.line("{\"status\":\"error\",\"error\":\"conversation stopped\"}");
      if (wav && (micRecording || micStart)) return io.line("{\"status\":\"error\",\"error\":\"microphone recording\"}");
      if (wav && audio.size() >= 2) return io.line("{\"status\":\"error\",\"error\":\"queue full\"}");
    }
    auto* data = static_cast<uint8_t*>(ps_malloc(requested));
    if (!data) return io.line("{\"status\":\"error\",\"error\":\"out of memory\"}");
    io.line("{\"status\":\"ready\"}");
    if (!receive(io, data, requested)) { free(data); io.line("{\"status\":\"error\",\"error\":\"receive timeout\"}"); return false; }
    Lock lock;
    if (receiveEpoch != epoch) { free(data); return io.line("{\"status\":\"error\",\"error\":\"transfer cancelled\"}"); }
    if (wav) {
      if (requested < 44 || memcmp(data, "RIFF", 4) || memcmp(data + 8, "WAVE", 4)) {
        free(data); return io.line("{\"status\":\"error\",\"error\":\"invalid WAV\"}");
      }
      audio.push_back({data, size_t(requested)});
    } else {
      size_t total = requested;
      for (int i = 0; i < 64; ++i) if (i != slot) total += frames[i].size();
      if (total > 800000) { free(data); return io.line("{\"status\":\"error\",\"error\":\"image cache full\"}"); }
      frames[slot].assign(data, data + requested); free(data);
      if (line.startsWith("IMAGE:")) showFrame(slot);
    }
    return io.line("{\"status\":\"ok\"}");
  }
  Lock lock;
  if (line.startsWith("VOLUME:")) {
    int next = constrain(line.substring(7).toInt(), 0, 255);
    if (next != volume) { volume = next; settings.putUChar("volume", volume); }
    M5.Speaker.setVolume(volume);
  }
  else if (line.startsWith("BATTERY_POSITION:")) {
    String next = line.substring(17);
    if (next != "right" && next != "left" && next != "center" && next != "hidden")
      return io.line("{\"status\":\"error\",\"error\":\"invalid battery position\"}");
    if (next != batteryPosition) {
      if (!settings.putString("batteryPos", next))
        return io.line("{\"status\":\"error\",\"error\":\"display save failed\"}");
      batteryPosition = next;
    }
    if (faceShown) showFrame(lastFrame);
    else nextBootDraw = 0;
  }
  else if (line.startsWith("SFRAME:")) showFrame(line.substring(7).toInt());
  else if (line.startsWith("SANIM:")) {
    interval = 0; animation.clear();
    int comma = line.indexOf(',');
    if (comma > 0) {
      int requested = line.substring(6, comma).toInt();
      while (comma > 0 && animation.size() < 16) {
        int end = line.indexOf(',', comma + 1);
        int slot = line.substring(comma + 1, end < 0 ? line.length() : end).toInt();
        if (slot < 0 || slot >= 64 || frames[slot].empty()) return io.line("{\"status\":\"error\",\"error\":\"missing frame\"}");
        animation.push_back(slot); comma = end;
      }
      interval = constrain(requested, 50, 5000); frameIndex = 0; nextFrame = millis();
    }
  }
  else if (line.startsWith("FACE:")) {
    interval = 0;
    if (canvasReady) {
      canvas.fillScreen(TFT_BLACK); canvas.setTextDatum(middle_center);
      canvas.setFont(&fonts::lgfxJapanGothic_40); canvas.setTextColor(TFT_WHITE);
      canvas.drawString("xangi-stopwatch", 233, 233); presentCanvas();
    } else {
      M5.Display.fillScreen(TFT_BLACK); M5.Display.setTextDatum(middle_center);
      M5.Display.setFont(&fonts::lgfxJapanGothic_40); M5.Display.drawString("xangi-stopwatch", 233, 233);
    }
  }
  else if (line == "MIC_BUTTON:off" || line == "HEADTOUCH_AVATAR:off" || line == "HEADPET_SOUND:off") {}
  else return io.line("{\"status\":\"error\",\"error\":\"unsupported command\"}");
  return io.line("{\"status\":\"ok\"}");
}
bool readLine(Channel& io, String& line) {
  { Lock lock;
    if (stopPending) {
      if (!io.line("{\"event\":\"conversation_stop\"}")) return false;
      stopPending = false;
    }
    if (characterNextPending) {
      if (!io.line("{\"event\":\"character_next\"}")) return false;
      characterNextPending = false;
    }
  }
  uint8_t c;
  int n = io.read(&c, 1, 20);
  if (n < 0) return false;
  if (n == 0) return true;
  if (c == '\n') { bool ok = command(io, line); line = ""; return ok; }
  if (c != '\r') { if (line.length() >= 4096) return false; line += char(c); }
  return true;
}
#ifdef XANGI_STOPWATCH_TAILNET
bool wifiReady() {
  return WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0);
}
void applyWifiCountry() {
  if (!XANGI_WIFI_COUNTRY_CODE[0]) return;
  if (strlen(XANGI_WIFI_COUNTRY_CODE) != 2) {
    wifiCountryError.store(ESP_ERR_INVALID_ARG);
    return;
  }
  wifi_country_t current{};
  if (esp_wifi_get_country(&current) == ESP_OK &&
      memcmp(current.cc, XANGI_WIFI_COUNTRY_CODE, 2) == 0 &&
      current.policy == WIFI_COUNTRY_POLICY_AUTO) {
    wifiCountryError.store(ESP_OK);
    return;
  }
  wifiCountryError.store(esp_wifi_set_country_code(XANGI_WIFI_COUNTRY_CODE, true));
}
WifiEndpoint loadWifiEndpoint(const String& ssid) {
  WifiEndpoint saved;
  Lock lock;
  if (settings.getBytesLength("wifiLastAP") != sizeof(saved) ||
      settings.getBytes("wifiLastAP", &saved, sizeof(saved)) != sizeof(saved) ||
      !saved.matches(ssid.c_str(), ssid.length())) return WifiEndpoint{};
  return saved;
}
void rememberWifiEndpoint(const String& ssid) {
  if (!wifiReady() || WiFi.SSID() != ssid) return;
  WifiEndpoint next;
  if (!next.assign(ssid.c_str(), ssid.length(), WiFi.BSSID(), WiFi.channel())) return;
  Lock lock;
  WifiEndpoint previous;
  if (settings.getBytesLength("wifiLastAP") == sizeof(previous) &&
      settings.getBytes("wifiLastAP", &previous, sizeof(previous)) == sizeof(previous) &&
      memcmp(&previous, &next, sizeof(next)) == 0) return;
  settings.putBytes("wifiLastAP", &next, sizeof(next));
}
void scanAndConnectWifi(const String& ssid, const String& password, bool passive) {
  // Stop outstanding reconnect attempts before scanning; the IDF rejects scans
  // while connecting. Never turn STA off or erase saved credentials.
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, false);
  vTaskDelay(pdMS_TO_TICKS(250));
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setScanTimeout(15000);
  int count = WiFi.scanNetworks(false, true, passive, passive ? 500 : 300);
  wifiScanCount.store(count);
  int best = -1;
  int32_t bestRssi = -128;
  WifiEndpoint previous = loadWifiEndpoint(ssid);
  bool previousValid = previous.matches(ssid.c_str(), ssid.length());
  int hidden = 0, channels = 0;
  wifiSavedApSeen.store(false); wifiSavedApAuth.store(-1); wifiSavedApChannel.store(0);
  for (int i = 0; i < count && i < 256; ++i) {
    int channel = WiFi.channel(i);
    if (channel >= 1 && channel <= 14) channels |= 1 << channel;
    bool unnamed = WiFi.SSID(i).length() == 0;
    if (unnamed) ++hidden;
    bool previousAp = previousValid && memcmp(previous.bssid, WiFi.BSSID(i), 6) == 0;
    if (previousAp) {
      wifiSavedApSeen.store(true); wifiSavedApAuth.store(WiFi.encryptionType(i));
      wifiSavedApChannel.store(channel);
    }
    // Only trust an unnamed AP when its address was authenticated previously
    // with this exact selected SSID; do not try arbitrary hidden networks.
    if ((WiFi.SSID(i) == ssid || (unnamed && previousAp)) && WiFi.RSSI(i) > bestRssi) {
      best = i;
      bestRssi = WiFi.RSSI(i);
    }
  }
  wifiScanHidden.store(hidden); wifiScanChannels.store(channels);
  // A directed probe can discover an AP that did not answer a wildcard probe.
  if (best < 0 && count >= 0) {
    WiFi.scanDelete();
    count = WiFi.scanNetworks(false, true, false, 300, 0, ssid.c_str());
    for (int i = 0; i < count && i < 256; ++i) {
      if (WiFi.SSID(i) == ssid && WiFi.RSSI(i) > bestRssi) {
        best = i;
        bestRssi = WiFi.RSSI(i);
      }
    }
  }
  uint8_t bssid[6] = {};
  int32_t channel = 0;
  if (best >= 0) {
    channel = WiFi.channel(best);
    memcpy(bssid, WiFi.BSSID(best), sizeof(bssid));
  }
  wifiScanChannel.store(channel);
  wifiScanRssi.store(best >= 0 ? bestRssi : -127);
  WiFi.scanDelete();
  // The task owns retries; an SDK reconnect must not race the next scan.
  if (best >= 0) WiFi.begin(ssid.c_str(), password.c_str(), channel, bssid);
  else WiFi.begin(ssid.c_str(), password.c_str());
}
void waitForWifi(const String& ssid, const String& password) {
  if (wifiReady()) return;
  WifiEndpoint saved = loadWifiEndpoint(ssid);
  bool cachedPending = saved.matches(ssid.c_str(), ssid.length());
  uint32_t retryDelay = 2000;
  unsigned missingAttempts = 0;
  while (!wifiReady()) {
    setBootStage("Wi-Fiに接続中");
    // Own retries here, including reasons the core does not retry and stalled
    // DHCP. Preserve the STA/netif once MicroLink has been initialized.
    // Before VPN initialization only, rebuild a stalled radio without erasing
    // credentials. MicroLink retains the STA netif once it has been started.
    if (!networkClient && missingAttempts >= 3) {
      WiFi.setAutoReconnect(false);
      WiFi.mode(WIFI_OFF);
      vTaskDelay(pdMS_TO_TICKS(250));
      WiFi.mode(WIFI_STA);
      applyWifiCountry();
      WiFi.setSleep(false);
      WiFi.setAutoReconnect(false);
      WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
      WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
      ++wifiRadioRestarts;
      missingAttempts = 0;
    }
    uint32_t disconnects = wifiDisconnectEvents.load();
    ++wifiAttempts;
    bool cached = cachedPending;
    cachedPending = false;
    if (cached) {
      WiFi.setAutoReconnect(false);
      WiFi.disconnect(false, false);
      vTaskDelay(pdMS_TO_TICKS(250));
      WiFi.setScanMethod(WIFI_FAST_SCAN);
      ++wifiCachedAttempts;
      WiFi.begin(ssid.c_str(), password.c_str(), saved.channel, saved.bssid);
    } else {
      scanAndConnectWifi(ssid, password, (wifiAttempts.load() % 2) == 0);
    }
    uint32_t started = millis();
    bool missing = false;
    while (!wifiReady() && uint32_t(millis() - started) < 45000) {
      // Preserve slow association/DHCP, but do not spend 45s on an AP the driver
      // has already reported missing. A link waiting for DHCP is left alone.
      if (wifiDisconnectEvents.load() != disconnects &&
          wifiDisconnectReason.load() == WIFI_REASON_NO_AP_FOUND && !WiFi.STA.connected()) {
        missing = true;
        break;
      }
      // A stale cached AP must not delay a fresh scan. A link awaiting DHCP
      // still receives the full connection window.
      if (cached && uint32_t(millis() - started) >= 8000 && !WiFi.STA.connected()) break;
      vTaskDelay(pdMS_TO_TICKS(250));
    }
    if (wifiReady()) break;
    if (missing) ++missingAttempts;
    else missingAttempts = 0;
    setBootStage("Wi-Fi再試行待ち・USBで確認可");
    started = millis();
    while (!wifiReady() && uint32_t(millis() - started) < retryDelay)
      vTaskDelay(pdMS_TO_TICKS(250));
    retryDelay = std::min(retryDelay * 2, uint32_t(missing ? 5000 : 30000));
  }
  rememberWifiEndpoint(ssid);
}
void networkTask(void*) {
  String ssid, password;
  { Lock lock; int slot = settings.getUChar("wifiSlot", 0); ssid = wifiSSID(slot); password = wifiPassword(slot); }
  if (ssid.isEmpty()) { setBootStage("USBでWi-Fiを設定してください"); vTaskDelete(nullptr); return; }
  if (!XANGI_TAILNET_AUTH_KEY[0] || !XANGI_TAILNET_SERVER[0]) { setBootStage("接続設定がありません"); vTaskDelete(nullptr); return; }
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
    // Ignore our own disconnect before retrying; preserve the AP's last reason.
    if (info.wifi_sta_disconnected.reason != WIFI_REASON_ASSOC_LEAVE) {
      wifiDisconnectReason.store(info.wifi_sta_disconnected.reason);
      ++wifiDisconnectEvents;
    }
  }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  // Credentials are already stored in Preferences; retries need not rewrite
  // the driver's flash configuration on every attempt.
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  applyWifiCountry();
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(false);
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  waitForWifi(ssid, password);
  setBootStage("時刻を合わせています");
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  while (time(nullptr) < 1700000000) {
    waitForWifi(ssid, password);
    setBootStage("時刻を合わせています");
    vTaskDelay(pdMS_TO_TICKS(250));
  }
  setBootStage("暗号化通信を準備中");
  const microlink_config_t config = {
    .auth_key = XANGI_TAILNET_AUTH_KEY,
    .device_name = microlink_default_device_name(),
    .enable_derp = true, .enable_stun = true, .enable_disco = true,
    .max_peers = CONFIG_ML_MAX_PEERS, .wifi_tx_power_dbm = 0,
    .priority_peer_ip = microlink_parse_ip(XANGI_TAILNET_SERVER),
    .disco_heartbeat_ms = 0, .stun_interval_ms = 0, .ctrl_watchdog_ms = 0,
  };
  auto* ml = microlink_init(&config);
  networkClient = ml;
  if (!ml || microlink_start(ml) != ESP_OK) { setBootStage("通信の初期化に失敗"); vTaskDelete(nullptr); return; }
  for (;;) {
    waitForWifi(ssid, password);
    if (!microlink_get_vpn_ip(ml)) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
    uint32_t ip = microlink_parse_ip(XANGI_TAILNET_SERVER);
    if (!ip) ip = microlink_resolve(ml, XANGI_TAILNET_SERVER);
    if (!ip) { vTaskDelay(pdMS_TO_TICKS(3000)); continue; }
    Channel io;
    io.net = true;
    setBootStage("サーバーに接続中");
    ++networkAttempts;
    io.socket = microlink_tcp_connect(ml, ip, XANGI_TAILNET_PORT, 15000);
    if (!io.socket) { vTaskDelay(pdMS_TO_TICKS(3000)); continue; }
    stopAudio();
    setBootStage("キャラクターを準備中");
    networkActive = true;
    io.line(String("{\"event\":\"stopwatch_connected\",\"device\":\"") + microlink_default_device_name() + "\",\"protocol\":3}");
    String line;
    while (wifiReady() && microlink_tcp_is_connected(io.socket) && readLine(io, line)) {}
    stopAudio();
    { Lock lock; micCancel = true; micReady = false; micStart = false; micButtons = false; }
    microlink_tcp_close(io.socket);
    networkActive = false;
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}
#endif
} // namespace
void setup() {
  // HWCDC defaults to 256 bytes; binary transfers arrive in larger bursts.
  Serial.setRxBufferSize(32768);
  Serial.begin(921600);
  auto config = M5.config();
  config.internal_mic = true;
  config.internal_spk = true;
  M5.begin(config);
  settings.begin("avatar", false);
  volume = settings.getUChar("volume", 25);
  batteryPosition = settings.getString("batteryPos", "right");
  if (batteryPosition != "left" && batteryPosition != "center" && batteryPosition != "hidden") batteryPosition = "right";
  textVisible = settings.getBool("textVisible", true);
  screenRotation.angle = ScreenRotation::normalize(settings.getFloat("screenAngle", settings.getFloat("avatarAngle", 0)));
  savedScreenAngle = screenRotation.angle;
  M5.Mic.end();
  auto micConfig = M5.Mic.config();
  micConfig.magnification = 4;
  M5.Mic.config(micConfig);
  M5.Speaker.begin();
  M5.Speaker.setVolume(volume);
  canvas.setColorDepth(16);
  canvas.setPsram(true);
  canvasReady = canvas.createSprite(466, 466) != nullptr;
  screenCanvas.setColorDepth(16);
  screenCanvas.setPsram(true);
  rotationReady = canvasReady && screenCanvas.createSprite(466, 466) != nullptr;
  canvas.setPivot(233, 233);
  guard = xSemaphoreCreateRecursiveMutex();
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  showBootScreen();
  micSamples = static_cast<int16_t*>(ps_malloc(MIC_RATE * MIC_MAX_SECONDS * sizeof(int16_t)));
  xTaskCreatePinnedToCore(microphone, "microphone", 4096, nullptr, 2, nullptr, 1);
  xTaskCreatePinnedToCore(player, "audio", 4096, nullptr, 2, nullptr, 1);
#ifdef XANGI_STOPWATCH_TAILNET
  xTaskCreatePinnedToCore(networkTask, "tailnet", 16384, nullptr, 1, nullptr, 0);
#else
  setBootStage("USB接続を待っています");
#endif
}
void loop() {
#ifdef XANGI_STOPWATCH_TAILNET
  { Lock lock; if (wifiRestartAt && int32_t(millis() - wifiRestartAt) >= 0) ESP.restart(); }
#endif
  showBootScreen();
  if (int32_t(millis() - nextBatteryRead) >= 0) {
    Lock lock;
    nextBatteryRead = millis() + 10000;
    int level = M5.Power.getBatteryLevel();
    batteryPercent = level < 0 ? -1 : std::min(100, level);
    batteryCharging = M5.Power.isCharging() == m5::Power_Class::is_charging;
    if (faceShown) showFrame(lastFrame);
  }
  updateButtons();
  { Lock lock; if (dashboardView && int32_t(millis() - dashboardNextDraw) >= 0) { drawDashboard(); dashboardNextDraw = millis() + (dashboardView == 1 && !multipleUsage ? 100 : 500); } }
  static Channel usb;
  static String line;
#ifdef XANGI_STOPWATCH_TAILNET
  // A separate USB parser never consumes microphone/button events destined for TCP.
  if (networkActive) {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\n') {
        if (line == "WIFI_LIST" || line == "NET_STATUS" || line.startsWith("WIFI_SETUP:") || line.startsWith("WIFI_DELETE:")) command(usb, line);
        else usb.line("{\"status\":\"error\",\"error\":\"USB Wi-Fi setup only while connected\"}");
        line = "";
      } else if (c != '\r') {
        if (line.length() < 4096) line += c;
        else line = "!overflow";
      }
    }
  } else
#endif
  if ((Serial.available() || characterNextPending || stopPending) && !readLine(usb, line)) {
    line = ""; stopAudio();
  }
  {
    Lock lock;
    if ((captionPage + 1) * 2 < captionLines.size() && int32_t(millis() - nextCaption) >= 0) {
      ++captionPage; nextCaption = millis() + captionPageMs; showFrame(lastFrame);
    }
    if (interval && !animation.empty() && int32_t(millis() - nextFrame) >= 0) {
      showFrame(animation[frameIndex++ % animation.size()]);
      nextFrame = millis() + interval;
    }
  }
  delay(2);
}
