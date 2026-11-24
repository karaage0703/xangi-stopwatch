import subprocess
import tempfile
from pathlib import Path

s = (
    Path(__file__).resolve().parents[1] / "firmware/examples/stopwatch/main/main.cpp"
).read_text()
f = s[s.index("void presentCanvas(") : s.index('#include "dashboard.h"')]
prefix = r"""
#include <cassert>
#include <string>
using String=std::string;
// Match Arduino's String(angle, decimals) used by the overlay.
struct Text: std::string {Text(float,int):std::string("37"){};};
#define String Text
constexpr int TFT_BLACK=0,TFT_CYAN=1,middle_center=0;
namespace fonts {int lgfxJapanGothic_24=24;}
struct {bool active=false;float angle=37;} screenRotation;
bool rotationReady=true;
bool micRecording=false;
int waveforms=0;
void drawMicWaveform(){waveforms++;}
constexpr int MIC_WAVEFORM_X=89,MIC_WAVEFORM_Y=282;
constexpr int MIC_WAVEFORM_WIDTH=288,MIC_WAVEFORM_HEIGHT=86;
struct MockDisplay {
 int clips=0,clears=0;
 void setClipRect(int x,int y,int w,int h){
   assert(x==MIC_WAVEFORM_X&&y==MIC_WAVEFORM_Y);
   assert(w==MIC_WAVEFORM_WIDTH&&h==MIC_WAVEFORM_HEIGHT);
   clips++;
 }
 void clearClipRect(){clears++;}
};
struct {MockDisplay Display;} M5;
struct Canvas {
 int fills=0,rotates=0,pushes=0,labels=0;Canvas* target=nullptr;
 void fillScreen(int){fills++;} void fillRoundRect(int,int,int,int,int,int){}
 void setFont(int*){} void setTextDatum(int){} void setTextColor(int){}
 void drawString(std::string,int,int){labels++;}
 void pushRotateZoom(Canvas* dst,int x,int y,float a,float,float){assert(x==233&&y==233&&a==screenRotation.angle);rotates++;target=dst;}
 void pushSprite(int,int){pushes++;}
}canvas,screenCanvas;
"""
test = """
int main() {
 presentCanvas();
 assert(canvas.rotates==1&&canvas.target==&screenCanvas&&screenCanvas.fills==1);
 assert(screenCanvas.pushes==1&&canvas.pushes==0&&waveforms==0);
 screenRotation.active=true;
 presentCanvas();
 assert(canvas.labels==1);
 screenRotation.angle=0;
 presentCanvas();
 assert(canvas.pushes==1&&canvas.rotates==2);
 rotationReady=false;
 screenRotation.angle=37;
 presentCanvas();
 assert(canvas.pushes==2&&canvas.rotates==2);

 micRecording=true;
 screenRotation.active=false;
 presentCanvas(true);
 assert(waveforms==1&&canvas.pushes==3&&M5.Display.clips==1&&M5.Display.clears==1);
 rotationReady=true;
 presentCanvas(true);
 assert(waveforms==2&&canvas.rotates==3&&M5.Display.clips==1);
 micRecording=false;
 presentCanvas();
 assert(waveforms==2&&canvas.rotates==4);
}
"""
with tempfile.TemporaryDirectory() as d:
    p = Path(d)
    (p / "t.cpp").write_text(prefix + f + test)
    subprocess.run(
        ["c++", "-std=c++17", str(p / "t.cpp"), "-o", str(p / "t")], check=True
    )
    subprocess.run([str(p / "t")], check=True)
print(
    "PASS: rotation, allocation fallback, and recording waveform composition and clipping"
)
