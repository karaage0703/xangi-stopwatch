"""Run the firmware drawing code on a desktop canvas and emit SVG previews.

Uses sample data. Font metrics are approximate; physical touch/FPS need hardware.
"""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
header = (ROOT / "firmware/examples/stopwatch/main/dashboard.h").read_text()
# Keep the actual renderer; the JSON parser is compiled by PlatformIO.
renderer = (
    header[: header.index("String jsonText(")]
    + header[header.index("int dashboardPages()") :]
)
prefix = r"""
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <cassert>
#include "navigation.h"
struct String: std::string {
 using std::string::string;
 String():std::string(){} String(const std::string&s):std::string(s){}
 String(int n):std::string(std::to_string(n)){} String(unsigned n):std::string(std::to_string(n)){}
 void remove(int n){resize(n);}
};
template<class A,class B,class C> A constrain(A v,B low,C high){return std::max(A(low),std::min(A(high),v));}
unsigned fakeNow=5000;unsigned millis(){return fakeNow;}
constexpr int middle_center=0,top_left=1,top_right=2;
constexpr unsigned TFT_WHITE=0xffff;
namespace fonts { int lgfxJapanGothic_16=16,lgfxJapanGothic_20=20,lgfxJapanGothic_24=24,lgfxJapanGothic_40=40; }
String escape(String s){String out;for(char c:s){if(c=='&')out+="&amp;";else if(c=='<')out+="&lt;";else if(c=='>')out+="&gt;";else out+=c;}return out;}
String color(unsigned c){std::ostringstream o;o<<"rgb("<<((c>>11)&31)*255/31<<","<<((c>>5)&63)*255/63<<","<<(c&31)*255/31<<")";return o.str();}
struct Canvas {
 int font=20,datum=0;unsigned ink=TFT_WHITE;
 void setFont(int*p){font=*p;}void setTextColor(unsigned c){ink=c;}void setTextDatum(int d){datum=d;}
 int textWidth(const String&s){float w=0;for(unsigned char c:s)if((c&0xc0)!=0x80)w+=c<128?font*0.55f:font;return int(w);}
 void fillRect(int x,int y,int w,int h,unsigned c){std::cout<<"<rect x='"<<x<<"' y='"<<y<<"' width='"<<w<<"' height='"<<h<<"' fill='"<<color(c)<<"'/>\n";}
 void fillRoundRect(int x,int y,int w,int h,int r,unsigned c){std::cout<<"<rect x='"<<x<<"' y='"<<y<<"' width='"<<w<<"' height='"<<h<<"' rx='"<<r<<"' fill='"<<color(c)<<"'/>\n";}
 void fillCircle(int x,int y,int r,unsigned c){std::cout<<"<circle cx='"<<x<<"' cy='"<<y<<"' r='"<<r<<"' fill='"<<color(c)<<"'/>\n";}
 void fillScreen(unsigned c){fillRect(0,0,466,466,c);}
 void drawFastVLine(int x,int y,int h,unsigned c){fillRect(x,y,1,h,c);}
 void drawString(String s,int x,int y){std::cout<<"<text x='"<<x<<"' y='"<<(y+(datum==middle_center?font*0.35:font*0.88))<<"' text-anchor='"<<(datum==middle_center?"middle":datum==top_right?"end":"start")<<"' font-size='"<<font<<"' fill='"<<color(ink)<<"'>"<<escape(s)<<"</text>\n";}
 void pushSprite(int,int){}
} canvas;
bool canvasReady=true;
"""
suffix = r"""
int main(int argc,char**argv){
 int view=0,page=0;assert(navigateDashboard(-90,3,view,page,3)==1&&view==1);
 assert(navigateDashboard(2,-90,view,page,3)==2&&page==1);
 assert(navigateDashboard(5,5,view,page,3)==0&&page==1);
 assert(navigateDashboard(90,2,view,page,3)==1&&view==0&&page==0);
 assert(navigateDashboard(90,0,view,page,3)==1&&view==2);
 assert(navigateDashboard(-90,0,view,page,3)==1&&view==0);
 assert(navigateDashboard(-90,0,view,page,3)==1&&view==1);
 assert(navigateDashboard(-90,0,view,page,3)==1&&view==2);
 assert(navigateDashboard(-90,0,view,page,3)==1&&view==0);
 dashboardView=argc>1?atoi(argv[1]):1;
 multipleUsage=argc>2;
 dashboardReceived=true;dashboardAt=5000;usageError=tasksError=false;dashboardBackend="codex";
 DashboardRow u;u.name="Codex";u.detail="共通枠 / 5時間";u.used=42;u.pace=55;u.reset=135;usageRows.push_back(u);
 u.detail="共通枠 / 週間";u.used=28;u.pace=40;usageRows.push_back(u);
 u.name="GitHub Copilot";u.detail="Premium requests";u.used=12;u.pace=-1;usageRows.push_back(u);usageTotal=3;
 DashboardRow t;t.name="StopWatchの画面を実装";t.detail="スワイプ・利用量表示を検証中";t.state="tool実行中";t.active=true;t.seconds=184;workingRows.push_back(t);
 t.name="調査レポートの確認";t.detail="結果を確認してください";t.state="結果確認待ち";t.active=false;t.seconds=-1;workingRows.push_back(t);
 t.name="明日の予定を整理";t.detail="次の入力を待っています";t.state="入力待ち";workingRows.push_back(t);
 workingTotal=3;runningTotal=1;
 std::cout<<"<svg xmlns='http://www.w3.org/2000/svg' width='466' height='466' viewBox='0 0 466 466'><defs><clipPath id='round'><circle cx='233' cy='233' r='233'/></clipPath></defs><g clip-path='url(#round)' font-family='Noto Sans CJK JP,sans-serif'>\n";
 drawDashboard();std::cout<<"</g></svg>";
}
"""
output = ROOT / "dist/dashboard-preview"
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / "preview.cpp").write_text(prefix + renderer + suffix)
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-I",
            str(ROOT / "firmware/examples/stopwatch/main"),
            str(path / "preview.cpp"),
            "-o",
            str(path / "preview"),
        ],
        check=True,
    )
    for name, args in [
        ("water", ["1"]),
        ("bars", ["1", "multiple"]),
        ("tasks", ["2"]),
    ]:
        data = subprocess.check_output([str(path / "preview"), *args])
        (output / f"{name}.svg").write_bytes(data)
print(f"PASS: native navigation and firmware renderer; previews: {output}")
