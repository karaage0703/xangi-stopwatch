"""Device/protocol limits shared with firmware and host runtime defaults.

Protocol limits must stay aligned with firmware/examples/stopwatch/main/main.cpp.
Transport addresses and credentials belong in config.json, not in this module.
"""

# Device and payload limits (bytes, Hz, seconds unless otherwise named).
DISPLAY_WIDTH = 466
DISPLAY_HEIGHT = 466
MAX_IMAGE_BYTES = 100_000
MAX_AUDIO_BYTES = 600_000
MIN_SAMPLE_RATE_HZ = 8_000
MAX_SAMPLE_RATE_HZ = 48_000
PCM_SAMPLE_BYTES = 2
MAX_AUDIO_SECONDS = 30
MAX_PENDING_JOBS = 2
MAX_VOLUME = 255

# Ownership and playback policy.
OWNER_TTL_SECONDS = 45
WATCH_INTERVAL_SECONDS = 0.2
PLAYBACK_GRACE_SECONDS = 15
JOB_HISTORY_LIMIT = 128
MOUTH_FRAME_INTERVAL_MS = 160

# USB CDC baud does not throttle USB bursts: pacing prevents RX overflow.
USB_BAUD_RATE = 921_600
USB_READ_TIMEOUT_SECONDS = 0.5
USB_WRITE_TIMEOUT_SECONDS = 10
USB_RECONNECT_SECONDS = 1
USB_CHUNK_BYTES = 1024
USB_CHUNK_INTERVAL_SECONDS = 0.015
TCP_CHUNK_BYTES = 4096
TCP_ACCEPT_TIMEOUT_SECONDS = 0.5
TCP_READ_TIMEOUT_SECONDS = 15
COMMAND_TIMEOUT_SECONDS = 12
MAX_REPLY_BYTES = 65536

# Managed HTTP and Tailnet defaults.
HTTP_BIND_HOST = "127.0.0.1"
MAX_HTTP_BODY_BYTES = 900_000  # Includes base64 expansion and JSON overhead.
HTTP_READ_TIMEOUT_SECONDS = 10
DEFAULT_TAILNET_PORT = 18766
TAILNET_CIDR = "100.64.0.0/10"
CONFIG_RELATIVE_PATH = ".xangi/xangi-stopwatch/config.json"
