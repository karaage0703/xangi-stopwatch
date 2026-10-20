"""Exercise production DERP routing/cleanup against C network doubles."""

import subprocess
import tempfile
from pathlib import Path

source = (
    Path(__file__).resolve().parents[1]
    / "firmware/.deps/microlink/components/microlink/src/ml_derp.c"
).read_text()
start = source.index("static void derp_disconnect_conn(")
end = source.index("void ml_derp_tx_task(", start)
production = source[start:end]
prefix = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define ML_DERP_REGION 9
#define ML_DERP_HOST "dallas.example"
#define ML_DERP_PORT 443
#define ESP_OK 0
#define ESP_ERR_NOT_FOUND -1
typedef int esp_err_t;
typedef struct {bool connected;int sockfd,ssl,ssl_conf,entropy,ctr_drbg;uint16_t region;} ml_derp_conn_t;
typedef struct {int region_id,node_count;struct {bool stun_only;char hostname[64];int derp_port;} nodes[3];} ml_derp_region_t;
typedef struct {bool active;uint32_t vpn_ip;uint8_t public_key[32];uint16_t derp_region;} ml_peer_t;
typedef struct {ml_derp_conn_t derp;int derp_region_count,peer_count;
 ml_derp_region_t derp_regions[4];ml_peer_t peers[4];struct {uint32_t priority_peer_ip;} config;} microlink_t;
static uint64_t now;
static int connects,fail_connect,closes,frees;
static uint16_t connected_region;
static uint64_t ml_get_time_ms(void){return now;}
static void ml_close_sock(int fd){(void)fd;closes++;}
static void mbedtls_ssl_close_notify(int*p){(void)p;}
static void mbedtls_ssl_free(int*p){(void)p;frees++;}
static void mbedtls_ssl_config_free(int*p){(void)p;frees++;}
static void mbedtls_ctr_drbg_free(int*p){(void)p;frees++;}
static void mbedtls_entropy_free(int*p){(void)p;frees++;}
"""
tests = r"""
static esp_err_t derp_connect_region(microlink_t *m,ml_derp_conn_t *c,uint16_t region){
 const char *host=NULL;int port=0;connects++;
 if(!derp_region_endpoint(m,region,&host,&port)||fail_connect)return -1;
 assert(host&&port>0);connected_region=region;c->region=region;c->connected=true;c->sockfd=10;
 return ESP_OK;
}
int main(void){
 microlink_t m={0};m.derp.connected=true;m.derp.region=9;m.derp.sockfd=5;
 m.config.priority_peer_ip=0x64400001;m.peer_count=3;
 m.peers[0]=(ml_peer_t){.active=true,.vpn_ip=0x64400001,.public_key={1},.derp_region=2};
 m.peers[1]=(ml_peer_t){.active=true,.vpn_ip=0x64400002,.public_key={2},.derp_region=9};
 m.peers[2]=(ml_peer_t){.active=true,.vpn_ip=0x64400003,.public_key={3},.derp_region=4};
 m.derp_region_count=2;m.derp_regions[0].region_id=2;m.derp_regions[0].node_count=2;
 m.derp_regions[0].nodes[0].stun_only=true;strcpy(m.derp_regions[0].nodes[0].hostname,"stun.example");
 strcpy(m.derp_regions[0].nodes[1].hostname,"tokyo.example");m.derp_regions[0].nodes[1].derp_port=8443;
 m.derp_regions[1].region_id=4;m.derp_regions[1].node_count=1;
 strcpy(m.derp_regions[1].nodes[0].hostname,"new.example");
 ml_derp_conn_t out={.sockfd=-1};uint64_t retry=0;
 // The actual regression: Dallas home must not carry packets destined for Tokyo.
 assert(derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry)==&out);
 assert(connected_region==2&&connects==1&&m.derp.connected&&m.derp.region==9&&m.derp.sockfd==5);
 const char *host=NULL;int port=0;
 assert(derp_region_endpoint(&m,2,&host,&port)&&strcmp(host,"tokyo.example")==0&&port==8443);
 // Keep inbound session and reuse both routes without reconnecting.
 assert(derp_outbound_connection(&m,&out,m.peers[1].public_key,&retry)==&m.derp);
 assert(derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry)==&out&&connects==1);
 // Background discovery for other regions must not evict the server route.
 assert(!derp_outbound_connection(&m,&out,m.peers[2].public_key,&retry)&&connects==1&&out.connected);
 uint8_t unknown[32]={9};assert(!derp_outbound_connection(&m,&out,unknown,&retry));
 // A peer moving regions closes only outbound TLS and establishes its new region.
 m.peers[0].derp_region=4;
 assert(derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry)==&out);
 assert(connected_region==4&&connects==2&&closes==1&&m.derp.connected);
 // Failed handshakes retry after backoff without relying on coord/pings.
 derp_disconnect_conn(&out);fail_connect=1;now=100;
 assert(!derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry));
 assert(retry==10100&&connects==3);int freed=frees;
 now=101;assert(!derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry)&&connects==3);
 fail_connect=0;now=10100;m.derp.connected=false;
 assert(derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry)==&out&&connects==4);
 assert(frees==freed&&retry==0); // Home failure does not prevent outbound.
 // Unknown maps and zero region must never silently use Dallas.
 m.peers[0].derp_region=99;
 assert(!derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry));
 assert(!derp_region_endpoint(&m,99,&host,&port));
 m.peers[0].derp_region=0;assert(!derp_outbound_connection(&m,&out,m.peers[0].public_key,&retry));
 m.peers[0].active=false;assert(!derp_is_priority_destination(&m,m.peers[0].public_key));
 // Failed TLS still owns memory even when the socket has already closed.
 freed=frees;out.sockfd=-1;derp_disconnect_conn(&out);assert(frees==freed+4);
 assert(m.derp.sockfd==5); // Never close or substitute the home session.
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
    "PASS: cross-region routing, home preservation, reuse, region changes, retry, missing map, TLS cleanup"
)
