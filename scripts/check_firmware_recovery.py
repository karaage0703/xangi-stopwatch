"""Compile the actual patched C recovery functions against test doubles (requires cc)."""

import subprocess
import tempfile
from pathlib import Path

base = (
    Path(__file__).resolve().parents[1]
    / "firmware/.deps/microlink/components/microlink/src"
)


def function(file, name):
    s = (base / file).read_text()
    start = s.index("void " + name + "(")
    a = s.index("{", start)
    depth = 1
    i = a + 1
    while depth:
        depth += (s[i] == "{") - (s[i] == "}")
        i += 1
    return s[start:i]


prefix = r"""
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
typedef int nvs_handle_t;
#define ESP_OK 0
#define NVS_READWRITE 0
#define NVS_NAMESPACE "microlink"
#define ML_EVT_DERP_CONNECTED 1
#define pdTRUE 1
#define ESP_LOGI(...) ((void)0)
#define TAG "test"
typedef struct {void *data;} ml_derp_tx_item_t;
typedef struct {uint32_t vpn_ip;int events,derp_tx_queue; struct {bool connected;int sockfd,ssl,ssl_conf,ctr_drbg,entropy;} derp;} microlink_t;
static int frees,closes,clears,writes;static uint32_t saved;
int nvs_open(const char*a,int b,int*c){*c=1;return 0;}
int nvs_get_u32(int a,const char*b,uint32_t*c){*c=saved;return saved?0:1;}
int nvs_set_u32(int a,const char*b,uint32_t c){saved=c;writes++;return 0;}
void nvs_commit(int a){} void nvs_close(int a){}
void xEventGroupClearBits(int a,int b){clears++;}
void mbedtls_ssl_close_notify(int*p){}
void mbedtls_ssl_free(int*p){frees++;}
void mbedtls_ssl_config_free(int*p){frees++;}
void mbedtls_ctr_drbg_free(int*p){frees++;}
void mbedtls_entropy_free(int*p){frees++;}
void ml_close_sock(int a){closes++;}
int xQueueReceive(int a,ml_derp_tx_item_t*b,int c){return 0;}
"""
main = r"""
int main(void){
 microlink_t m={0};m.derp.sockfd=-1;
 ml_derp_disconnect(&m);assert(frees==4&&closes==0&&clears==1);
 m.derp.sockfd=4;m.derp.connected=true;
 ml_derp_disconnect(&m);assert(frees==8&&closes==1&&!m.derp.connected&&m.derp.sockfd==-1);
 ml_cache_vpn_ip(&m,0xc0a83235);assert(writes==0&&m.vpn_ip==0);
 ml_cache_vpn_ip(&m,0x64400001);assert(writes==1&&m.vpn_ip==0x64400001);
 ml_cache_vpn_ip(&m,0x64400001);assert(writes==1);
 ml_cache_vpn_ip(&m,0x64400002);assert(writes==2&&saved==0x64400002);
 return 0;
}
"""
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    (p / "test.c").write_text(
        prefix
        + function("ml_derp.c", "ml_derp_disconnect")
        + function("microlink.c", "ml_cache_vpn_ip")
        + main
    )
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Werror=implicit-function-declaration",
            str(p / "test.c"),
            "-o",
            str(p / "test"),
        ],
        check=True,
    )
    subprocess.run([str(p / "test")], check=True)
print(
    "PASS: production C cleanup after failed/connected TLS; VPN cache range, first save, unchanged/changed address"
)
