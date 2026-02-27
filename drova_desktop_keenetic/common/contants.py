DROVA_CONFIG = "DROVA_CONFIG"

DROVA_SOCKET_LISTEN = "DROVA_SOCKET_LISTEN"

WINDOWS_HOST = "WINDOWS_HOST"
WINDOWS_LOGIN = "WINDOWS_LOGIN"
WINDOWS_PASSWORD = "WINDOWS_PASSWORD"

SHADOW_DEFENDER_PASSWORD = "SHADOW_DEFENDER_PASSWORD"
SHADOW_DEFENDER_DRIVES = "SHADOW_DEFENDER_DRIVES"

DROVA_WEB_PORT = "DROVA_WEB_PORT"
DROVA_WEB_USER = "DROVA_WEB_USER"
DROVA_WEB_PASSWORD = "DROVA_WEB_PASSWORD"

# Path to a JSON file where the DrovaPoll subprocess writes its startup diagnostic results.
# Set by WorkerManager when spawning a worker so the web server can read the results.
DROVA_STATUS_FILE = "DROVA_STATUS_FILE"

# OBS recording (all four vars are optional; recording is disabled when OBS_PATH is unset)
# OBS_PATH     – full path to obs64.exe on the Windows PC
#                Example: C:\Program Files\obs-studio\bin\64bit\obs64.exe
# OBS_PROFILE  – OBS profile name to activate at launch (passed as --profile flag)
# OBS_WS_PORT  – OBS WebSocket server port; defaults to 4455
# OBS_WS_PASSWORD – OBS WebSocket password (leave unset if auth is disabled in OBS)
#
# IMPORTANT: configure the OBS output path to a pre-mapped SMB network share (e.g. Z:\)
# so recordings survive Shadow Defender rollback on reboot.
OBS_PATH = "OBS_PATH"
OBS_PROFILE = "OBS_PROFILE"
OBS_WS_PORT = "OBS_WS_PORT"
OBS_WS_PASSWORD = "OBS_WS_PASSWORD"
