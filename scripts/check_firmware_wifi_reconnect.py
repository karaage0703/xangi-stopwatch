"""Exercise the actual firmware retry loop with a simulated radio and clock."""

import argparse
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path)
args = parser.parse_args()
source = (
    args.source
    or Path(__file__).resolve().parents[1] / "firmware/examples/stopwatch/main/main.cpp"
).read_text()
if "bool wifiReady()" in source:
    helpers = source[
        source.index("bool wifiReady()") : source.index("void networkTask(void*)")
    ]
else:
    # Run the same assertions against the previous firmware's initial loop.
    start = source.index('  setBootStage("Wi-Fiに接続中");\n  while (WiFi.status()')
    end = source.index('  setBootStage("時刻を合わせています");', start)
    helpers = (
        "void waitForWifi(const String& ssid, const String& password) {\n"
        + source[start:end]
        + "}\n"
    )

prefix = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
using String = std::string;
constexpr int WL_CONNECTED = 3, WIFI_STA = 1, WIFI_OFF = 0;
constexpr int WIFI_REASON_NO_AP_FOUND = 201, WIFI_ALL_CHANNEL_SCAN = 1, WIFI_CONNECT_AP_BY_SIGNAL = 1, WIFI_FAST_SCAN = 0;
void* networkClient = nullptr;
const char* XANGI_WIFI_COUNTRY_CODE="";
constexpr int ESP_OK=0,ESP_ERR_INVALID_ARG=258,WIFI_COUNTRY_POLICY_AUTO=0;
struct wifi_country_t {char cc[3];uint8_t schan,nchan;int policy;};
wifi_country_t radioCountry={{'0','1',0},1,11,0};
int countryWrites=0;
std::atomic<int> wifiCountryError{0};
int esp_wifi_get_country(wifi_country_t* out) {*out=radioCountry;return 0;}
int esp_wifi_set_country_code(const char* code,bool automatic) {
 assert(automatic);++countryWrites;
 radioCountry={{code[0],code[1],0},1,14,0};return 0;
}
struct Lock {};
struct Storage {
 std::vector<uint8_t> bytes; int writes=0; bool fail=false;
 size_t getBytesLength(const char*) { return bytes.size(); }
 size_t getBytes(const char*,void* dst,size_t n) { size_t count=std::min(n,bytes.size());std::memcpy(dst,bytes.data(),count);return count; }
 size_t putBytes(const char*,const void* src,size_t n) { if(fail)return 0;const auto* p=static_cast<const uint8_t*>(src);bytes.assign(p,p+n);++writes;return n; }
} settings;
std::atomic<uint32_t> wifiDisconnectEvents{0}, wifiRadioRestarts{0}, wifiCachedAttempts{0};
std::atomic<uint8_t> wifiDisconnectReason{0};
uint32_t clockMs = 0;
std::atomic<uint32_t> wifiAttempts{0};
std::atomic<int32_t> wifiScanCount{-3}, wifiScanChannel{0}, wifiScanRssi{-127};
std::atomic<int32_t> wifiScanHidden{0}, wifiScanChannels{0}, wifiSavedApAuth{-1}, wifiSavedApChannel{0};
std::atomic<bool> wifiSavedApSeen{false};
uint32_t millis() { return clockMs; }
uint32_t elapsed = 0;
void vTaskDelay(uint32_t ms) { clockMs += ms; elapsed += ms; assert(elapsed < 1000000); }
#define pdMS_TO_TICKS(ms) (ms)
void setBootStage(const char*) {}
struct IPAddress {
 int value;
 IPAddress(int a, int b, int c, int d): value(a+b+c+d) {}
 bool operator!=(const IPAddress& other) const { return value != other.value; }
};
struct AP { String ssid; int32_t rssi, channel; uint8_t bssid[6]; };
struct Radio {
 std::vector<AP> broad, directed, passiveAPs, cache;
 bool autoreconnect = false, pinned = false;
 int scans = 0, scanFailure = 0, selectedChannel = 0;
 bool earlyFailure=false, staleMissing=false;
 int failureReported=-1;
 std::vector<bool> passiveModes;
 struct Link { bool associated=false; bool connected() { return associated; } } STA;
 void setScanMethod(int) {} void setSortMethod(int) {}
 void setScanTimeout(uint32_t ms) { assert(ms == 15000); }
 int scanNetworks(bool async, bool hidden, bool passive=false, uint32_t ms=300,
                  uint8_t channel=0, const char* ssid=nullptr) {
   assert(!autoreconnect && !async && hidden && channel==0);
   assert(ms==(passive?500:300)); passiveModes.push_back(passive);
   ++scans; cache = ssid ? directed : (passive ? passiveAPs : broad);
   return scanFailure ? scanFailure : int(cache.size());
 }
 void scanDelete() { cache.clear(); }
 int encryptionType(int) { return 3; }
 String SSID(int i) { return cache.at(i).ssid; }
 int32_t RSSI(int i) { return cache.at(i).rssi; }
 int32_t channel(int i) { return cache.at(i).channel; }
 uint8_t* BSSID(int i) { return cache.at(i).bssid; }
 uint8_t* BSSID() { static uint8_t mac[6]={42,0,0,0,0,1};return mac; }
 int32_t channel() { return selectedChannel?selectedChannel:6; }
 String SSID() { return "hotspot"; }
 void begin(const char* ssid, const char* password, int32_t channel, uint8_t* bssid) {
   assert(channel > 0 && bssid[0] == 42 && cache.empty());
   selectedChannel=channel; pinned=true; begin(ssid,password);
 }

 uint32_t started = 0, ipDelay = 1000, linkDelay = 1000;
 int begins = 0, succeedOn = 1, offCycles = 0;
 bool starting = false;
 std::vector<uint32_t> beginTimes;
 int status() {
   STA.associated=starting && begins>=succeedOn && uint32_t(clockMs-started)>=linkDelay;
   if(starting && uint32_t(clockMs-started)>=1000 && failureReported!=begins &&
      ((earlyFailure && begins<succeedOn) || (staleMissing && STA.associated))) {
     wifiDisconnectReason=WIFI_REASON_NO_AP_FOUND; ++wifiDisconnectEvents; failureReported=begins;
   }
   return STA.associated ? WL_CONNECTED : 0;
 }
 IPAddress localIP() { return status() == WL_CONNECTED &&
   uint32_t(clockMs-started) >= ipDelay ? IPAddress(10,0,0,1) : IPAddress(0,0,0,0); }
 void begin(const char* ssid, const char* password) {
   assert(std::string(ssid)=="hotspot" && std::string(password)=="password");
   started = clockMs; starting = true; ++begins; beginTimes.push_back(elapsed);
 }
 void disconnect(bool off, bool erase) {
   assert(!erase); if (off) ++offCycles; starting = false;
 }
 void mode(int mode) { if(mode==WIFI_OFF) { ++offCycles; starting=false; } } void setSleep(bool) {} void setAutoReconnect(bool enabled) { autoreconnect = enabled; }
} WiFi;
void reset(uint32_t clock = 0) {
 WiFi = Radio{}; wifiAttempts=0; clockMs=clock; elapsed=0;
 wifiDisconnectEvents=0;wifiDisconnectReason=0;wifiRadioRestarts=0;wifiCachedAttempts=0;networkClient=nullptr;settings=Storage{};XANGI_WIFI_COUNTRY_CODE="";radioCountry={{'0','1',0},1,11,0};countryWrites=0;wifiCountryError=0;
}
"""
tests = r"""
int main() {
 reset(); waitForWifi("hotspot", "password");
 assert(WiFi.begins == 1 && elapsed <= 1500);
 // An established link must be preserved without a new association.
 waitForWifi("hotspot", "password"); assert(WiFi.begins == 1);
 // Slow hotspot startup and DHCP must get more than the former 20s window.
 reset(); WiFi.linkDelay = 35000; WiFi.ipDelay = 40000;
 waitForWifi("hotspot", "password"); assert(WiFi.begins == 1 && elapsed >= 40000 && elapsed <= 40250 && WiFi.offCycles == 0);
 reset(); WiFi.ipDelay = 35000;
 waitForWifi("hotspot", "password"); assert(elapsed >= 35000 && elapsed <= 35250 && WiFi.begins == 1);
 // The AP appears later, including an auth failure not retried by the core.
 reset(); WiFi.succeedOn = 7; waitForWifi("hotspot", "password");
 assert(WiFi.begins == 7);
 const uint32_t gaps[] = {47250, 49250, 53250, 61250, 75250, 75250};
 for (int i=0; i<6; ++i) assert(WiFi.beginTimes[i+1]-WiFi.beginTimes[i] == gaps[i]);
 // Drop after a successful session; the same saved credentials recover it.
 WiFi.starting = false; waitForWifi("hotspot", "password"); assert(WiFi.begins == 8);
 // Scan results choose the strongest matching SSID, never a stronger stranger.
 reset(); WiFi.broad={{"other",-10,1,{10}}, {"hotspot",-70,6,{42}}, {"hotspot",-40,11,{42}}};
 waitForWifi("hotspot", "password");
 assert(WiFi.pinned && WiFi.selectedChannel==11 && WiFi.scans==1 && wifiScanCount==3);
 assert(wifiScanChannel==11 && wifiScanRssi==-40);
 // A directed probe is tried when the wildcard scan misses the AP.
 reset(); WiFi.broad={{"other",-10,1,{10}}}; WiFi.directed={{"hotspot",-30,6,{42}}};
 waitForWifi("hotspot", "password"); assert(WiFi.pinned && WiFi.scans==2 && wifiScanChannel==6);
 // Scan failure keeps SSID-based connection available, rather than blocking it.
 reset(); WiFi.scanFailure=-2; waitForWifi("hotspot", "password");
 assert(!WiFi.pinned && WiFi.scans==1 && wifiScanCount==-2 && wifiScanChannel==0);
 // A definitive AP-missing event triggers a new scan without a 45s wait.
 reset(); WiFi.earlyFailure=true;WiFi.succeedOn=7;
 waitForWifi("hotspot","password");
 assert(WiFi.begins==7 && elapsed<60000 && wifiRadioRestarts==2 && WiFi.offCycles==2);
 assert(!WiFi.autoreconnect);
 assert(WiFi.passiveModes.at(0)==false && WiFi.passiveModes.at(2)==true);
 // An AP that does not answer active probes can be selected on a passive scan.
 reset();WiFi.earlyFailure=true;WiFi.succeedOn=2;
 WiFi.passiveAPs={{"hotspot",-50,6,{42}}};
 waitForWifi("hotspot","password");assert(WiFi.begins==2 && WiFi.pinned && WiFi.selectedChannel==6);
 // Once MicroLink owns a netif, retries must leave the radio/netif alive.
 reset();networkClient=reinterpret_cast<void*>(1);WiFi.earlyFailure=true;WiFi.succeedOn=7;
 waitForWifi("hotspot","password");assert(wifiRadioRestarts==0 && WiFi.offCycles==0 && elapsed<60000);
 // A historical missing event must never cancel a live link waiting on DHCP.
 reset();WiFi.staleMissing=true;WiFi.ipDelay=35000;
 waitForWifi("hotspot","password");assert(WiFi.begins==1 && elapsed>=35000);
 // Cache is learned from a successful connection, survives reboot, skips scan.
 reset();waitForWifi("hotspot","password");assert(settings.writes==1);
 auto saved=settings.bytes;reset();settings.bytes=saved;
 waitForWifi("hotspot","password");assert(wifiCachedAttempts==1 && WiFi.scans==0 && WiFi.begins==1 && settings.writes==0);
 // A stale endpoint must fall back to discovery, once per recovery episode.
 reset();settings.bytes=saved;WiFi.earlyFailure=true;WiFi.succeedOn=2;
 waitForWifi("hotspot","password");assert(wifiCachedAttempts==1 && WiFi.scans>0 && WiFi.begins==2);
 // A cached link with slow DHCP is not cancelled by the 8s association budget.
 reset();settings.bytes=saved;WiFi.ipDelay=35000;
 waitForWifi("hotspot","password");assert(WiFi.begins==1 && elapsed>=35000);
 // A hung cache attempt without a terminal event times out and discovers APs.
 reset();settings.bytes=saved;WiFi.succeedOn=2;
 waitForWifi("hotspot","password");assert(WiFi.begins==2 && elapsed<15000 && wifiCachedAttempts==1);
 // Corrupt/foreign-SSID caches are ignored without changing credentials.
 WifiEndpoint endpoint;uint8_t mac[6]={42,0,0,0,0,1};
 assert(endpoint.assign("other",5,mac,6));
 reset();settings.bytes.assign(reinterpret_cast<uint8_t*>(&endpoint),reinterpret_cast<uint8_t*>(&endpoint)+sizeof(endpoint));
 waitForWifi("hotspot","password");assert(wifiCachedAttempts==0 && WiFi.scans>0);
 reset();settings.bytes={1,2,3};waitForWifi("hotspot","password");assert(wifiCachedAttempts==0);
 assert(!endpoint.assign("hotspot",7,mac,0));
 assert(endpoint.assign("hotspot",7,mac,6));endpoint.version=9;assert(!endpoint.matches("hotspot",7));
 endpoint.version=1;endpoint.length=33;assert(!endpoint.matches("hotspot",33));
 mac[0]=43;assert(!endpoint.assign("hotspot",7,mac,6));
 // A previously authenticated AP with a hidden SSID and changed channel is
 // identified by its cached BSSID; unrelated hidden APs are never selected.
 reset();settings.bytes=saved;WiFi.earlyFailure=true;WiFi.succeedOn=2;
 WiFi.passiveAPs={{"",-10,1,{44,0,0,0,0,1}}, {"",-50,11,{42,0,0,0,0,1}}};
 waitForWifi("hotspot","password");
 assert(WiFi.selectedChannel==11 && wifiSavedApSeen && wifiSavedApChannel==11 && wifiScanHidden==2);
 assert((wifiScanChannels & (1<<11)) && wifiSavedApAuth==3);
 // Cache write failure must not prevent normal network use.
 reset();settings.fail=true;waitForWifi("hotspot","password");assert(WiFi.begins==1 && settings.bytes.empty());
 // Country is optional, preserves IEEE 802.11d, skips unchanged writes,
 // and is restored after startup-only radio recovery.
 reset();applyWifiCountry();assert(countryWrites==0);
 XANGI_WIFI_COUNTRY_CODE="JP";applyWifiCountry();assert(countryWrites==1 && radioCountry.nchan==14);
 applyWifiCountry();assert(countryWrites==1);
 XANGI_WIFI_COUNTRY_CODE="J";applyWifiCountry();assert(wifiCountryError==ESP_ERR_INVALID_ARG && countryWrites==1);
 // millis() wrap must not skip the timeout or spin forever.
 reset(UINT32_MAX - 10000); WiFi.succeedOn = 2;
 waitForWifi("hotspot", "password"); assert(WiFi.begins == 2 && elapsed >= 48250 && elapsed <= 48500);
}
"""
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    endpoint_header = (
        Path(__file__).resolve().parents[1]
        / "firmware/examples/stopwatch/main/wifi_endpoint.h"
    ).read_text()
    (path / "wifi_endpoint.h").write_text(endpoint_header)
    (path / "test.cpp").write_text(
        prefix + '\n#include "wifi_endpoint.h"\n' + helpers + tests
    )
    subprocess.run(
        ["c++", "-std=c++17", str(path / "test.cpp"), "-o", str(path / "test")],
        check=True,
    )
    subprocess.run([str(path / "test")], check=True, cwd=path)
print(
    "PASS: slow AP/DHCP, delayed AP, bounded backoff, link loss, timer wrap, scan selection/directed probe/failure, early missing recovery, passive scan, netif/DHCP preservation, endpoint cache/save/reuse/fallback/corruption/write-failure, hidden cached AP, deployment country"
)
