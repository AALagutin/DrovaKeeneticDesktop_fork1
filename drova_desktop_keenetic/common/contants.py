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

# Optional: path to a compiled AutoHotkey script on the Windows PC that launches OBS.
# If set, PatchWindowsSettings will execute it via PsExec after explorer is restarted.
# Example: C:\Users\user\Desktop\start_obs.exe
OBS_AHK_SCRIPT = "OBS_AHK_SCRIPT"
