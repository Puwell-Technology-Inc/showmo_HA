"""Constants for ShowMo integration."""

DOMAIN = "showmo"

CONF_RTSP_URL = "rtsp_url"

DEFAULT_NAME = "Live"

MANUFACTURER = "ShowMo"
MODEL = "WinEye"

# PTZ service. The camera may advertise PTZ without implementing motion (fixed
# models answer ActionNotSupported); the service is kept for models that do.
SERVICE_PTZ = "ptz"

ATTR_MOVE_MODE = "move_mode"
ATTR_PAN = "pan"
ATTR_TILT = "tilt"
ATTR_ZOOM = "zoom"
ATTR_PRESET = "preset"
ATTR_CONTINUOUS_DURATION = "continuous_duration"

PTZ_MOVE_CONTINUOUS = "ContinuousMove"
PTZ_MOVE_STOP = "Stop"
PTZ_MOVE_GOTO_PRESET = "GotoPreset"
PTZ_MOVE_GOTO_HOME = "GotoHomePosition"
PTZ_MOVE_MODES = [
    PTZ_MOVE_CONTINUOUS,
    PTZ_MOVE_STOP,
    PTZ_MOVE_GOTO_PRESET,
    PTZ_MOVE_GOTO_HOME,
]
