"""Browser tests with a simulated USB device; never writes physical hardware."""

import argparse
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from xangi_stopwatch.usb_wifi import create_setup_server

MOCK = r"""
window.device={profiles:[],active:0,connected:false,commands:[],error:null,cancel:false,capability:true};
const serial=new EventTarget();
serial.requestPort=async()=>{
 if(device.cancel)throw new DOMException('cancel','NotFoundError');
 let controller;
 const port={
 async open(){
  port.readable=new ReadableStream({start(c){controller=c;}});
  port.writable=new WritableStream({write(chunk){
   const cmd=new TextDecoder().decode(chunk).trim();device.commands.push(cmd);let reply;
   if(device.error)reply={status:'error',error:device.error};
   else if(cmd==='WIFI_LIST')reply={status:'ok',usb_setup:device.capability,profiles:device.profiles,active:device.active};
   else if(cmd==='NET_STATUS')reply={wifi_status:device.connected?3:6,has_ip:device.connected,server_connected:device.connected};
   else if(cmd.startsWith('WIFI_SETUP:')){const [ssid_hex,password]=cmd.slice(11).split(',');let p=device.profiles.find(p=>p.ssid_hex===ssid_hex);if(!p){p={id:device.profiles.length,ssid_hex,built_in:false};device.profiles.push(p);}device.active=p.id;device.connected=true;reply={status:'ok'};}
   else if(cmd.startsWith('WIFI_DELETE:')){device.profiles=device.profiles.filter(p=>p.id!==Number(cmd.split(':')[1]));reply={status:'ok'};}
   const line=new TextEncoder().encode('boot log\n'+JSON.stringify(reply)+'\n');
   controller.enqueue(line.slice(0,8));controller.enqueue(line.slice(8));
  }});
 },async close(){}, unplug(){controller.error(new Error('unplug'));const event=new Event('disconnect');Object.defineProperty(event,'port',{value:port});serial.dispatchEvent(event);}
 };
 window.mockPort=port;return port;
};
Object.defineProperty(navigator,'serial',{value:serial,configurable:true});
"""
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
server = create_setup_server()
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(MOCK)
        page.goto(f"http://127.0.0.1:{server.server_port}/")
        expect(page.locator("#ssid")).to_be_disabled()
        page.screenshot(path=str(args.output / "desktop-waiting.png"), full_page=True)
        page.click("#connect")
        expect(page.locator("#status")).to_contain_text("Wi-Fi未設定")
        page.fill("#ssid", "あ" * 11)
        page.fill("#password", "12345678")
        page.click("#save")
        expect(page.locator("#status")).to_contain_text("32バイト")
        assert not page.evaluate("device.commands.some(c=>c.startsWith('WIFI_SETUP:'))")
        page.fill("#ssid", "家のWi-Fi")
        page.click("#save")
        expect(page.locator("#status")).to_contain_text("保存しました")
        expect(page.locator("#password")).to_have_value("")
        expect(page.locator("#connect")).to_be_enabled()
        page.screenshot(path=str(args.output / "desktop-saved.png"), full_page=True)
        page.click("#connect")
        expect(page.locator("#status")).to_contain_text("サーバーともに接続済み")
        # Correct the same SSID instead of adding duplicates.
        page.click("#use")
        page.fill("#password", "corrected-password")
        page.click("#save")
        expect(page.locator("#status")).to_contain_text("保存しました")
        assert page.evaluate("device.profiles.length") == 1
        page.click("#connect")
        page.evaluate("device.error='Wi-Fi list full'")
        page.fill("#ssid", "extra")
        page.fill("#password", "12345678")
        page.click("#save")
        expect(page.locator("#status")).to_contain_text("5件")
        expect(page.locator("#password")).to_have_value("")
        page.evaluate("device.error=null;device.cancel=true")
        page.click("#connect")
        expect(page.locator("#status")).to_contain_text("キャンセル")
        page.evaluate("device.cancel=false;device.capability=false")
        page.click("#connect")
        expect(page.locator("#status")).to_contain_text("対応していません")
        page.evaluate("device.capability=true")
        page.click("#connect")
        expect(page.locator("#ssid")).to_be_enabled()
        page.evaluate("mockPort.unplug()")
        expect(page.locator("#status")).to_contain_text("切断")
        expect(page.locator("#connect")).to_be_enabled()
        page.set_viewport_size({"width": 375, "height": 812})
        page.click("#connect")
        expect(page.locator("#status")).to_contain_text("接続済み")
        page.screenshot(path=str(args.output / "mobile-connected.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        # Open network and labels containing markup stay plain text.
        page.fill("#ssid", "<b>open</b>")
        page.fill("#password", "")
        page.click("#save")
        expect(page.locator("#status")).to_contain_text("保存しました")
        page.click("#connect")
        assert page.locator("#profiles b").count() == 0
        expect(page.locator("#profiles")).to_contain_text("<b>open</b>")
        # Local file download is usable in Chromium's secure file context.
        file_page = browser.new_page()
        file_page.goto(Path("src/xangi_stopwatch/usb_wifi.html").resolve().as_uri())
        assert file_page.evaluate("isSecureContext && 'serial' in navigator")
        assert not errors, errors
        browser.close()
finally:
    server.shutdown()
    server.server_close()
print(
    "PASS: initial setup, invalid UTF-8 length, reset/reconnect, correction, capacity, cancel, old firmware, disconnect, mobile, open network, HTML escaping, file context"
)
