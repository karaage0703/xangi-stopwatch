"""Render actual avatar/battery/caption code with the bundled default avatar."""

import ast
import subprocess
import tempfile
from pathlib import Path

from xangi_stopwatch.faces import default_faces

root = Path(__file__).resolve().parents[1]
out = root / "dist/dashboard-preview"
module = ast.parse((root / "scripts/render_dashboard_preview.py").read_text())
prefix = next(
    ast.literal_eval(n.value)
    for n in module.body
    if isinstance(n, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "prefix" for t in n.targets)
)
source = (root / "firmware/examples/stopwatch/main/main.cpp").read_text()
battery = source[
    source.index("template<class Display> void drawBattery") : source.index(
        "void showBootScreen()"
    )
]
frame = source[
    source.index("void showFrame(int slot)") : source.index("void stopAudio()")
]

encoded = default_faces()["closed"]
methods = r"""
 void drawRoundRect(int x,int y,int w,int h,int r,unsigned c){std::cout<<"<rect x='"<<x<<"' y='"<<y<<"' width='"<<w<<"' height='"<<h<<"' rx='"<<r<<"' fill='none' stroke='"<<color(c)<<"' stroke-width='1'/>\n";}
 void fillTriangle(int x1,int y1,int x2,int y2,int x3,int y3,unsigned c){std::cout<<"<polygon points='"<<x1<<","<<y1<<" "<<x2<<","<<y2<<" "<<x3<<","<<y3<<"' fill='"<<color(c)<<"'/>\n";}
 void drawJpg(const uint8_t*,size_t,int,int,int,int,int,int,float,float,int){std::cout<<"<image width='466' height='466' href='data:image/jpeg;base64,IMAGE_DATA'/>\n";}
""".replace("IMAGE_DATA", encoded)
prefix = prefix.replace(
    " void remove(int n)",
    " String(size_t n):std::string(std::to_string(n)){} void remove(int n)",
)
prefix = prefix.replace(
    " void pushSprite(int,int){}", methods + " void pushSprite(int,int){}"
)
prefix = prefix.replace(
    "lgfxJapanGothic_24=24,", "lgfxJapanGothic_24=24,lgfxJapanGothic_28=28,"
)
globals = r"""
constexpr unsigned TFT_BLACK=0,TFT_GREEN=0x07e0,TFT_YELLOW=0xffe0;
String batteryPosition="right",voiceLabel="A: 録音 B: キャラ",captionRole;
int batteryPercent=85,lastFrame=0,dashboardView=0,captionIndex=0;
bool batteryCharging=true,faceShown=true,textVisible=true;
std::vector<uint8_t> frames[64];std::vector<String> captionLines;size_t captionPage=0;
struct Device { Canvas Display; } M5;
"""
main = r"""
int main(int argc, char**argv){
 if(argc>1){textVisible=false;captionRole="A";captionLines.push_back("サンプルのセリフ");}
 frames[0].push_back(1);
 std::cout<<"<svg xmlns='http://www.w3.org/2000/svg' width='466' height='466' viewBox='0 0 466 466'><defs><clipPath id='round'><circle cx='233' cy='233' r='233'/></clipPath></defs><g clip-path='url(#round)' font-family='Noto Sans CJK JP,sans-serif'>";
 showFrame(0);std::cout<<"</g></svg>";
}
"""
with tempfile.TemporaryDirectory() as temp:
    p = Path(temp)
    (p / "render.cpp").write_text(prefix + globals + battery + frame + main)
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-I",
            str(root / "firmware/examples/stopwatch/main"),
            str(p / "render.cpp"),
            "-o",
            str(p / "render"),
        ],
        check=True,
    )
    svg = subprocess.check_output([str(p / "render")])
    (out / "xangi-default-overlay.svg").write_bytes(svg)
    hidden = subprocess.check_output([str(p / "render"), "hidden"])
    assert "サンプルのセリフ" in hidden.decode()
    assert "85%" not in hidden.decode() and "A: 録音" not in hidden.decode()
    (out / "avatar-caption-only.svg").write_bytes(hidden)
print("Generated from actual showFrame/drawBattery; sample battery 85%, charging, idle")
