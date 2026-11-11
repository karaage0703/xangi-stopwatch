#pragma once

// Copy this file to tailnet_secrets.h and fill in local credentials.
// tailnet_secrets.h is gitignored and must never be committed.
// Leave Wi-Fi empty; register it later in the USB Wi-Fi setup page.
#define XANGI_TAILNET_WIFI_SSID ""
#define XANGI_TAILNET_WIFI_PASSWORD ""

// Use a short-lived, reusable=false Tailscale auth key. After the first
// registration, MicroLink persists machine/WireGuard keys in NVS.
#define XANGI_TAILNET_AUTH_KEY "tskey-auth-..."

// DGX Spark peer name (MagicDNS short name or 100.x.y.z address) and the
// reverse-bridge listener port.
// A numeric 100.x address is recommended: MicroLink can reserve its peer slot
// before MagicDNS data has been fully populated.
#define XANGI_TAILNET_SERVER "100.x.y.z"
#define XANGI_TAILNET_PORT 18766

// Deployment country (ISO 3166-1 alpha-2, e.g. JP). Empty keeps SDK defaults.
#define XANGI_WIFI_COUNTRY_CODE ""
