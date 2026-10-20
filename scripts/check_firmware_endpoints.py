"""Native regression test for the production endpoint parser (requires cc)."""

import subprocess
import tempfile
from pathlib import Path

source = (
    Path(__file__).resolve().parents[1]
    / "firmware/.deps/microlink/components/microlink/src/ml_coord.c"
).read_text()
start = source.index("static void parse_peer_endpoints_for_network(")
end = source.index("\nstatic void parse_peer_endpoints(", start)
production = source[start:end]
prefix = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define ML_MAX_ENDPOINTS 8
typedef struct cJSON {const char *valuestring;struct cJSON *next,*child;} cJSON;
#define cJSON_ArrayForEach(e,a) for(e=(a)->child;e;e=e->next)
typedef struct {struct {uint32_t ip;uint16_t port;bool is_ipv6;} endpoints[8];int endpoint_count;} ml_peer_update_t;
"""
tests = r"""
static void parse(ml_peer_update_t *u,const char **strings,int count,uint32_t local,uint32_t mask){
 cJSON entries[32]={0},array={0};assert(count<=32);
 for(int i=0;i<count;i++){entries[i].valuestring=strings[i];entries[i].next=i+1<count?&entries[i+1]:NULL;}
 array.child=count?entries:NULL;parse_peer_endpoints_for_network(u,&array,local,mask);
}
int main(void){
 const char *many[]={"203.0.113.1:4000","203.0.113.1:5000","[2001:db8::1]:41641",
 "172.17.0.1:41641","172.18.0.1:41641","172.19.0.1:41641","172.20.0.1:41641",
 "172.21.0.1:41641","172.22.0.1:41641","172.23.0.1:41641","172.24.0.1:41641",
 "172.25.0.1:41641","172.26.0.1:41641","172.27.0.1:41641","172.28.0.1:41641",
 "192.168.10.2:41641","[2001:db8::2]:41641"};
 ml_peer_update_t u={0};
 parse(&u,many,17,0xc0a80a35,0xffffff00);
 assert(u.endpoint_count==8);assert(u.endpoints[0].ip==0xc0a80a02);assert(u.endpoints[0].port==41641);
 // The first two persisted candidates now include the same-LAN endpoint.
 assert(u.endpoints[1].ip==0xcb007101);
 const char *bad[]={"999.1.1.1:80","192.168.10.2:65536","192.168.10.2:0",
 "192.168.10.2:80suffix","[::1]:80","0.0.0.0:80",NULL,
 "192.168.10.2:80","192.168.10.2:80","192.168.10.3:81"};
 parse(&u,bad,10,0xc0a80a35,0xffffff00);assert(u.endpoint_count==2);
 assert(u.endpoints[0].ip==0xc0a80a02&&u.endpoints[1].ip==0xc0a80a03);
 parse(&u,many,17,0,0);assert(u.endpoint_count==8&&u.endpoints[0].ip==0xcb007101);
 parse(&u,many,0,0,0);assert(u.endpoint_count==0);
 // Match actual interface netmask, not an assumed /24.
 const char *wide[]={"203.0.113.1:80","192.168.20.2:81"};
 parse(&u,wide,2,0xc0a80a35,0xffff0000);assert(u.endpoints[0].ip==0xc0a81402);
 return 0;
}
"""
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / "test.c").write_text(prefix + production + tests)
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(path / "test.c"),
            "-o",
            str(path / "test"),
        ],
        check=True,
    )
    subprocess.run([str(path / "test")], check=True)
print(
    "PASS: late LAN endpoint retained; duplicates/invalid endpoints rejected; empty and non-/24 networks"
)

# Exercise the actual NVS entry construction, including restart readback.
nvs_source = (
    Path(__file__).resolve().parents[1]
    / "firmware/.deps/microlink/components/microlink/src/ml_peer_nvs.c"
).read_text()
structures = nvs_source[
    nvs_source.index("/* Compact peer storage") : nvs_source.index(
        "static nvs_handle_t"
    )
]
save = nvs_source[
    nvs_source.index("esp_err_t ml_peer_nvs_save(") : nvs_source.index(
        "int ml_peer_nvs_load_all("
    )
]
nvs_prefix = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define ML_NVS_MAX_PEERS 16
#define ESP_ERR_INVALID_STATE -1
#define ESP_OK 0
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
typedef int esp_err_t;
typedef struct {uint32_t vpn_ip;uint8_t public_key[32],disco_key[32];uint16_t derp_region;
 struct {uint32_t ip;uint16_t port;bool is_ipv6;} endpoints[8];int endpoint_count;
 bool has_direct_path;uint32_t best_ip;uint16_t best_port;char hostname[64];} ml_peer_t;
"""
nvs_test = r"""
int main(void){
 ml_peer_t p={0};p.vpn_ip=0x64400001;strcpy(p.hostname,"test");
 p.endpoints[0].ip=0xcb007101;p.endpoints[0].port=4000;
 p.endpoints[1].ip=0xcb007102;p.endpoints[1].port=5000;p.endpoint_count=2;
 p.has_direct_path=true;p.best_ip=0xc0a80a02;p.best_port=41641;
 assert(ml_peer_nvs_save(&p)==0);
 // A simulated restart reads the flushed data, not live best_ip state.
 assert(persisted.entries[0].endpoint_count==2);
 assert(persisted.entries[0].endpoints[0].ip==p.best_ip);
 assert(persisted.entries[0].endpoints[1].ip==0xcb007101);
 p.endpoints[0].ip=p.best_ip;p.endpoints[0].port=p.best_port;
 assert(ml_peer_nvs_save(&p)==0);assert(persisted.count==1);
 assert(persisted.entries[0].endpoints[1].ip==0xcb007102); // no duplicate
 p.has_direct_path=false;assert(ml_peer_nvs_save(&p)==0);
 assert(persisted.entries[0].endpoints[0].ip==p.endpoints[0].ip);
 assert(ml_peer_nvs_save(NULL)==ESP_ERR_INVALID_STATE);
 return 0;
}
"""
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / "test.c").write_text(
        nvs_prefix
        + structures
        + "static bool s_initialized=true;static peer_nvs_table_t table,persisted;"
        + "static peer_nvs_table_t *s_table=&table;"
        + "static int flush_table(void){persisted=*s_table;return 0;}\n"
        + save
        + nvs_test
    )
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(path / "test.c"),
            "-o",
            str(path / "test"),
        ],
        check=True,
    )
    subprocess.run([str(path / "test")], check=True)
print(
    "PASS: verified direct endpoint persisted first; duplicates skipped; readback survives loss of live state"
)
