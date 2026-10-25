"""Run actual Wi-Fi firmware handlers against a native NVS/serial test double."""

import subprocess
import tempfile
from pathlib import Path

source = (
    Path(__file__).resolve().parents[1] / "firmware/examples/stopwatch/main/main.cpp"
).read_text()
helpers = source[
    source.index("constexpr int WIFI_PROFILE_COUNT") : source.index(
        "\n#endif\nbool command"
    )
]
handlers = source[
    source.index('  if (line.startsWith("WIFI_SETUP:"))') : source.index(
        '\n#endif\n\n  if (line.startsWith("CAPTION_INDEX:'
    )
]
prefix = r"""
#include <cassert>
#include <cstdint>
#include <map>
#include <string>
#include <deque>
struct String : std::string {
 using std::string::string;
 String() = default;
 String(const std::string& s): std::string(s) {}
 String(int n): std::string(std::to_string(n)) {}
 bool isEmpty() const { return empty(); }
 bool startsWith(const char* s) const { return rfind(s,0)==0; }
 int indexOf(char c,int start=0) const { auto p=find(c,start);return p==npos?-1:int(p); }
 String substring(int a) const { return substr(a); }
 String substring(int a,int b) const { return substr(a,b-a); }
};
struct Lock {};
struct Settings {
 std::map<std::string,String> data; uint8_t selected=0; bool fail=false;
 bool isKey(const char* k){return data.count(k);}
 String getString(const char* k,const char* fallback){return isKey(k)?data[k]:String(fallback);}
 size_t putString(const char* k,const String& v){if(fail)return 0;data[k]=v;return v.size();}
 uint8_t getUChar(const char*,int fallback){return selected;}
 size_t putUChar(const char*,int n){if(fail)return 0;selected=n;return 1;}
 bool remove(const char* k){return data.erase(k);}
} settings;
const char* XANGI_TAILNET_WIFI_SSID="";
const char* XANGI_TAILNET_WIFI_PASSWORD="";
uint32_t millis(){return 100;}
bool conversationBusy=false,micRecording=false,micReady=false,micStart=false,playing=false;
std::deque<int> audio;
struct Channel {bool net=false;String response;bool line(const String& s){response=s;return true;}};
"""
tests = r"""
int main(){
 Channel usb,net;net.net=true;
 auto setup=[&](const String& ssid,const String& password){command(usb,"WIFI_SETUP:"+hexString(ssid)+","+hexString(password));};
 assert(wifiSSID(0).isEmpty());command(usb,"WIFI_LIST");assert(usb.response.find("\"profiles\":[]")!=String::npos);
 setup("home","12345678");assert(settings.selected==0&&wifiSSID(0)=="home"&&wifiPassword(0)=="12345678"&&wifiRestartAt==1600);
 assert(usb.response.find("12345678")==String::npos);
 setup("home","new-password");assert(wifiPassword(0)=="new-password"&&settings.data.size()==1);
 setup("home","");assert(wifiPassword(0).isEmpty());
 settings.fail=true;setup("home","not-saved");assert(wifiPassword(0).isEmpty()&&usb.response.find("error")!=String::npos);settings.fail=false;
 command(net,"WIFI_SETUP:686f6d65,3132333435363738");assert(net.response.find("USB required")!=String::npos);
 conversationBusy=true;setup("busy","12345678");assert(usb.response.find("device busy")!=String::npos);conversationBusy=false;
 setup("invalid","short");assert(usb.response.find("invalid")!=String::npos);
 for(int i=1;i<5;i++)setup(String("network")+String(i),"12345678");
 setup("sixth","12345678");assert(usb.response.find("list full")!=String::npos);
 setup("home","updated-at-capacity");assert(wifiPassword(0)=="updated-at-capacity");
 // Legacy firmware profiles and embedded initial Wi-Fi remain readable.
 settings.data.clear();XANGI_TAILNET_WIFI_SSID="old-home";XANGI_TAILNET_WIFI_PASSWORD="old-password";
 settings.data["w1s"]="legacy";settings.data["w1p"]="legacy-pass";
 assert(wifiSSID(0)=="old-home"&&wifiPassword(1)=="legacy-pass");
 setup("legacy","new-password");assert(wifiSSID(1)=="legacy"&&wifiPassword(1)=="new-password");
 settings.selected=0;command(usb,"WIFI_DELETE:1");assert(wifiSSID(1).isEmpty());
 setup("old-home","corrected-password");assert(wifiBuiltIn(0)&&wifiPassword(0)=="corrected-password");
 // With no embedded Wi-Fi, the old ADD command can also use slot zero.
 settings.data.clear();XANGI_TAILNET_WIFI_SSID="";command(usb,"WIFI_ADD:686f6d65,3132333435363738");assert(wifiSSID(0)=="home");
 return 0;
}
"""
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / "test.cpp").write_text(
        prefix
        + helpers
        + "\nbool command(Channel& io,const String& line){\n"
        + handlers
        + "\nreturn false;}\n"
        + tests
    )
    subprocess.run(
        ["c++", "-std=c++17", str(path / "test.cpp"), "-o", str(path / "test")],
        check=True,
    )
    subprocess.run([str(path / "test")], check=True)
print(
    "PASS: first setup, update, open network, failed save, busy, validation, USB-only, capacity, legacy migration/deletion"
)
