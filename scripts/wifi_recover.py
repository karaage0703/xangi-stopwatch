"""Select a saved Wi-Fi over USB when the device cannot reach the network."""

import argparse
import time

from xangi_stopwatch.transport import Transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="StopWatch USB serial port")
    parser.add_argument("--profile", type=int, choices=range(5), required=True)
    args = parser.parse_args()
    transport = Transport()
    try:
        transport.start_usb(args.port)
        deadline = time.monotonic() + 5
        while not transport.is_connected:
            if time.monotonic() >= deadline:
                raise RuntimeError("StopWatch USB connection timed out")
            time.sleep(0.1)
        # USB CDC may accept writes before its receive path is ready after open.
        # Verify both directions before issuing a command that reboots the device.
        time.sleep(1)
        profiles = transport.request("WIFI_LIST")["profiles"]
        if args.profile not in {p["id"] for p in profiles}:
            raise ValueError("The requested Wi-Fi profile is not saved")
        transport.request(f"WIFI_SELECT:{args.profile}")
        print(
            "Wi-Fi selection accepted. StopWatch will restart; reconnection is not yet verified."
        )
    finally:
        transport.close()


if __name__ == "__main__":
    main()
