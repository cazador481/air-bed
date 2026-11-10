from datetime import timedelta

DOMAIN = "airpedic"
CONF_SWAP_SIDES = "swap_sides"
DEFAULT_SWAP_SIDES = False
# Polling holds the bed's only BLE connection for ~1 s; keep it infrequent so
# the phone app can still connect.
SCAN_INTERVAL = timedelta(minutes=5)
