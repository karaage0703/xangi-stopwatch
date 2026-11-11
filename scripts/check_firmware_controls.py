"""Execute the firmware's actual button handler with a native C++ test device."""

import subprocess
import tempfile
from pathlib import Path

source = (
    Path(__file__).resolve().parents[1] / "firmware/examples/stopwatch/main/main.cpp"
).read_text()
handler = source[source.index("void updateButtons() {") : source.index("bool receive(")]
prefix = r"""
#include <cassert>
#include "rotation.h"
uint32_t tick=0; uint32_t millis(){return tick;}
ScreenRotation screenRotation; bool rotationReady=true;
float savedScreenAngle=0; uint32_t lastRotationDraw=0;
#include <deque>
#include <string>
struct Lock {};
struct Button { bool pressed=false; bool wasClicked(){return wasPressed();} bool wasPressed(){bool v=pressed;pressed=false;return v;} };
struct TouchDetail { bool down=false;int x=433,y=233;bool isPressed() const {return down;} bool pressed=false; bool wasReleased() const {return pressed;} bool wasClicked() const {return pressed;} int dx=0,dy=0; int distanceX() const {return dx;} int distanceY() const {return dy;} };
struct TouchMock { TouchDetail detail; TouchDetail getDetail(){auto v=detail;detail.pressed=false;return v;} };
bool canvasReady=true;int dashboardView=0,dashboardPage=0,nextBootDraw=0;
int dashboardPages(){return 3;} void drawDashboard(){}
#include "navigation.h"

struct Settings { int writes=0;float stored=0;size_t putFloat(const char*,float a){writes++;stored=a;return 4;} void putBool(const char*,bool){} } settings;
bool textVisible=true,faceShown=true;int lastFrame=0,redraws=0;
void showFrame(int){redraws++;} void showBootScreen(){redraws++;}
struct Device { TouchMock Touch; Button BtnA,BtnB;void update(){}; } M5;
bool micButtons=false,micRecording=false,micFinish=false,micReady=false,micStart=false,micCancel=false;
bool conversationBusy=false,playing=false,stopRequested=false,stopPending=false,characterNextPending=false;
std::deque<int> audio;int stopCount=0;std::string label;
void stopAudio(){stopCount++;audio.clear();playing=false;}
void micLabel(const char *s){label=s;}
"""
tests = r"""
int main(){
 M5.Touch.detail.pressed=true;updateButtons();assert(!textVisible&&redraws==1);
 updateButtons();assert(!textVisible&&redraws==1);
 M5.Touch.detail.pressed=true;updateButtons();assert(textVisible&&redraws==2);
 M5.Touch.detail.pressed=true;M5.Touch.detail.dx=-100;updateButtons();assert(dashboardView==1&&textVisible);
 M5.Touch.detail.pressed=true;M5.Touch.detail.dx=0;M5.Touch.detail.dy=-100;updateButtons();assert(dashboardPage==1);
 M5.Touch.detail.pressed=true;M5.Touch.detail.dx=100;M5.Touch.detail.dy=0;updateButtons();assert(dashboardView==0&&dashboardPage==0);
 M5.Touch.detail.dx=0;
 // Hold, rotate clockwise, release: no swipe/click, one persistent write.
 M5.Touch.detail.down=true;tick=100;updateButtons();
 tick=699;updateButtons();assert(!screenRotation.active);
 tick=700;updateButtons();assert(screenRotation.active);
 M5.Touch.detail.x=233;M5.Touch.detail.y=433;tick=760;updateButtons();
 assert(std::abs(screenRotation.angle-90)<0.01f&&settings.writes==0);
 M5.Touch.detail.down=false;M5.Touch.detail.pressed=true;M5.Touch.detail.dx=-200;updateButtons();
 assert(!screenRotation.active&&dashboardView==0&&textVisible&&settings.writes==1&&settings.stored==90);
 updateButtons();assert(settings.writes==1);
 screenRotation.angle=0;
 // Regular swipe remains navigation, including a pause after movement.
 M5.Touch.detail.down=true;M5.Touch.detail.x=433;M5.Touch.detail.y=233;tick=1000;updateButtons();
 M5.Touch.detail.x=330;tick=1100;updateButtons();tick=1800;updateButtons();assert(!screenRotation.active);
 M5.Touch.detail.down=false;M5.Touch.detail.pressed=true;M5.Touch.detail.dx=-103;updateButtons();assert(dashboardView==1);
 // Rotation also works on dashboards; allocation failure disables it.
 M5.Touch.detail.down=true;tick=2000;updateButtons();tick=2700;updateButtons();assert(screenRotation.active);
 M5.Touch.detail.down=false;updateButtons();dashboardView=0;rotationReady=false;
 M5.Touch.detail.down=true;tick=3000;updateButtons();tick=3700;updateButtons();assert(!screenRotation.active);
 M5.Touch.detail.down=false;updateButtons();rotationReady=true;
 // Wrapping across +/-180 degrees and moving through the centre never jumps.
 ScreenRotation r;r.update(true,33,234,0,true);r.update(true,33,234,600,true);
 r.update(true,33,232,650,true);assert(r.angle<1);
 float before=r.angle;r.update(true,233,233,700,true);r.update(true,433,233,750,true);assert(r.angle==before);
 r.update(true,233,433,800,true);assert(std::abs(r.angle-before-90)<0.01f);
 assert(r.update(false,0,0,850,true));assert(!r.update(false,0,0,900,true));
 // Navigation follows the screen axes for arbitrary rotation angles.
 int dx=0,dy=-100;ScreenRotation::toDisplayDelta(dx,dy,90);assert(dx==-100&&dy==0);
 int view=0,page=0;assert(navigateDashboard(dx,dy,view,page,3)==1&&view==1);
 dx=71;dy=-71;ScreenRotation::toDisplayDelta(dx,dy,45);assert(std::abs(dx)<=1&&dy==-100);
 assert(navigateDashboard(dx,dy,view,page,3)==2&&page==1);
 screenRotation.angle=90;dashboardView=0;M5.Touch.detail.pressed=true;M5.Touch.detail.dx=0;M5.Touch.detail.dy=-100;
 updateButtons();assert(dashboardView==1);dashboardView=0;
 // Long hold across millis wrap and invalid persisted values.
 ScreenRotation wrap;wrap.update(true,433,233,UINT32_MAX-300,true);wrap.update(true,433,233,300,true);assert(wrap.active);
 assert(ScreenRotation::normalize(-90)==270&&ScreenRotation::normalize(720)==0&&ScreenRotation::normalize(NAN)==0);
 micButtons=true;M5.BtnA.pressed=true;updateButtons();assert(micStart);
 micStart=false;micRecording=true;M5.BtnA.pressed=true;updateButtons();assert(micFinish);
 M5.BtnB.pressed=true;updateButtons();assert(micCancel&&!stopPending&&!characterNextPending);
 micRecording=false;micCancel=false;micReady=true;conversationBusy=true;
 M5.BtnB.pressed=true;updateButtons();assert(stopPending&&stopRequested&&!micReady&&stopCount==1&&!characterNextPending);
 M5.BtnA.pressed=true;updateButtons();assert(!micStart);
 // Another press while cancellation is pending must not switch characters.
 M5.BtnB.pressed=true;updateButtons();assert(stopCount==2&&!characterNextPending);
 // During playback, queued audio is discarded locally before any host response.
 stopRequested=false;stopPending=false;conversationBusy=false;playing=true;audio.push_back(1);
 M5.BtnB.pressed=true;updateButtons();assert(stopCount==3&&audio.empty()&&!playing&&stopPending);
 stopRequested=false;stopPending=false;M5.BtnB.pressed=true;updateButtons();assert(characterNextPending);
 return 0;
}
"""
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / "test.cpp").write_text(prefix + handler + tests)
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-I",
            str(
                Path(__file__).resolve().parents[1] / "firmware/examples/stopwatch/main"
            ),
            str(path / "test.cpp"),
            "-o",
            str(path / "test"),
        ],
        check=True,
    )
    subprocess.run([str(path / "test")], check=True)
print(
    "PASS: record/send, recording cancel, waiting/playback stop, repeated stop, idle character switch"
)
