# ShowMo for Home Assistant

Home Assistant integration for **ShowMo / WinEye** ONVIF IP cameras.

## Features

- **Live view** — RTSP is restreamed to low-latency WebRTC by Home Assistant's bundled go2rtc.
- **Snapshots** — still images via the camera's HTTP endpoint.
- **Automatic discovery** — ONVIF WS-Discovery plus a local subnet scan.
- **Device info** — manufacturer, model, and serial number over ONVIF.
- **Motion detection** — an ONVIF PullPoint motion `binary_sensor`, exposed only when the camera firmware actually implements ONVIF events.
- **PTZ** — a `showmo.ptz` service (continuous move, stop, presets, home) for models with real pan/tilt/zoom.

### Known limitations

- **Motion** requires the camera to genuinely implement the ONVIF event service. Some models advertise it but do not implement it; on those the motion sensor is not created (rather than sitting permanently unavailable).
- **PTZ** on fixed-lens models returns "not supported" — the service call is logged and ignored.

## Requirements

- Home Assistant 2024.11 or newer recommended (the bundled go2rtc enables low-latency WebRTC live view).
- The camera reachable on the local network (RTSP on 554, ONVIF/HTTP on 8080).

## Installation (HACS custom repository)

1. HACS → three-dot menu → **Custom repositories**.
2. Repository: `https://github.com/Puwell-Technology-Inc/showmo_HA`, category: **Integration**.
3. Install **ShowMo**, then restart Home Assistant.

## Configuration

1. **Settings → Devices & Services → Add Integration → ShowMo**.
2. Choose **Scan Network** (auto-discovery) or **Manual Entry** (enter the RTSP URL, e.g. `rtsp://192.168.1.120/live0_0.sdp`).
3. Provide the camera username/password (commonly `admin`).

If you later change the camera's password (for example in the ShowMo app), Home Assistant prompts you to re-authenticate — enter the new credentials and everything (history, automations, dashboards) stays intact. Other settings can be changed anytime via the integration's **Reconfigure** option.

## PTZ service

Call `showmo.ptz` on the camera entity (Developer Tools → Actions):

```yaml
action: showmo.ptz
target:
  entity_id: camera.your_showmo_camera
data:
  move_mode: ContinuousMove   # or Stop / GotoPreset / GotoHomePosition
  pan: 0.5                     # -1 … 1 (ContinuousMove only)
  continuous_duration: 0.5     # seconds before auto-stop (0 = no auto-stop)
```

## License

Copyright © 2026 Puwell Technology Inc.

This project is licensed under the [GNU General Public License v3.0](LICENSE): you may use, modify, and redistribute it, but derivative works must remain open source under the same license and retain attribution.
