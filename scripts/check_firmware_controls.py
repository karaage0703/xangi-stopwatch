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
#include <deque>
#include <string>
struct Lock {};
struct Button { bool pressed=false; bool wasClicked(){return wasPressed();} bool wasPressed(){bool v=pressed;pressed=false;return v;} };
struct TouchDetail { bool pressed=false; bool wasReleased() const {return pressed;} bool wasClicked() const {return pressed;} int dx=0,dy=0; int distanceX() const {return dx;} int distanceY() const {return dy;} };
struct TouchMock { TouchDetail detail; TouchDetail getDetail(){auto v=detail;detail.pressed=false;return v;} };
bool canvasReady=true;int dashboardView=0,dashboardPage=0,nextBootDraw=0;
int dashboardPages(){return 3;} void drawDashboard(){}
#include "navigation.h"

struct Settings { void putBool(const char*,bool){} } settings;
bool textVisible=true,faceShown=true;int lastFrame=0,redraws=0;
void showFrame(int){redraws++;}
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
