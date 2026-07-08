"""Config flow for ShowMo integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    AuthenticationError,
    DiscoveryError,
    ShowMoApiClient,
    build_default_rtsp_path,
    build_rtsp_url_without_credentials,
    parse_rtsp_url,
)
from .const import (
    CONF_RTSP_URL,
    DEFAULT_NAME,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

ConfigFlowResult = FlowResult

CONF_DEVICE = "device"


def _build_manual_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the manual entry schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(
                CONF_RTSP_URL, default=defaults.get(CONF_RTSP_URL) or "rtsp://"
            ): str,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
        }
    )


def _build_scan_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the scan schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
        }
    )


def _truncate_label_part(value: str | None, limit: int) -> str:
    """Trim a long label part for dropdown readability."""
    if not value:
        return ""
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"


def _format_device_label(device: dict[str, Any]) -> str:
    """Format a short, readable device label."""
    manufacturer = _truncate_label_part(device.get("manufacturer") or "Unknown", 18)
    model = _truncate_label_part(device.get("model") or "Camera", 22)
    ip = device.get("ip", "unknown")
    serial = (device.get("serial") or "").strip()

    parts = [f"{manufacturer} {model}".strip(), ip]
    if serial:
        parts.append(f"S/N {serial[-8:]}")

    return " · ".join(part for part in parts if part)


def _build_device_options(
    devices: list[dict[str, Any]],
) -> dict[str, str]:
    """Build form options for discovered devices."""
    options: dict[str, str] = {}
    for index, device in enumerate(devices):
        options[str(index)] = _format_device_label(device)
    return options


def _log_flow_exception(message: str, err: Exception) -> None:
    """Log config flow exceptions consistently."""
    _LOGGER.warning("%s: %s", message, err)
    _LOGGER.debug("%s", message, exc_info=err)


class ShowMoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ShowMo."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._discovered_devices: list[dict[str, Any]] = []
        self._manual_defaults: dict[str, Any] = {}
        self._selected_device: dict[str, Any] | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["scan", "manual"],
        )

    async def async_step_scan(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Scan the local subnet for candidate cameras."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # A blank field means "use the factory default" — fall back per field
            # so a user who only changed the password can still leave username blank.
            username = user_input.get(CONF_USERNAME, "").strip() or DEFAULT_USERNAME
            password = user_input.get(CONF_PASSWORD, "") or DEFAULT_PASSWORD
            subnet = ShowMoApiClient.get_local_subnet()
            if subnet is None:
                errors["base"] = "cannot_determine_subnet"
            else:
                try:
                    devices = await ShowMoApiClient.discover_devices(
                        timeout=3.0,
                        subnet=subnet,
                        username=username,
                        password=password,
                    )
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                    devices = []
                except (DiscoveryError, aiohttp.ClientError, OSError, TimeoutError, ValueError) as err:
                    _log_flow_exception("Camera discovery failed", err)
                    errors["base"] = "discovery_failed"
                    devices = []
                except Exception as err:  # pragma: no cover - defensive guard
                    _LOGGER.exception("Unexpected camera discovery failure")
                    errors["base"] = "unknown"
                    devices = []

                if "base" not in errors:
                    devices = [device for device in devices if device.get("onvif")]
                    devices.sort(key=lambda item: item.get("ip", ""))

                    if not devices:
                        errors["base"] = "no_cameras_found"
                    else:
                        self._discovered_devices = devices
                        self._manual_defaults = {
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                        }
                        return await self.async_step_pick_device()

        defaults = user_input or {
            CONF_USERNAME: self._manual_defaults.get(CONF_USERNAME, ""),
            CONF_PASSWORD: self._manual_defaults.get(CONF_PASSWORD, ""),
        }
        return self.async_show_form(
            step_id="scan",
            data_schema=_build_scan_schema(defaults),
            errors=errors,
        )

    async def async_step_pick_device(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Let the user choose a discovered camera."""
        errors: dict[str, str] = {}

        if not self._discovered_devices:
            return await self.async_step_scan()

        if user_input is not None:
            try:
                self._selected_device = self._discovered_devices[int(user_input[CONF_DEVICE])]
            except (IndexError, TypeError, ValueError) as err:
                _log_flow_exception("Invalid discovered device selection", err)
                errors["base"] = "invalid_device"
            else:
                return await self.async_step_confirm_device()

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): vol.In(
                        _build_device_options(self._discovered_devices)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_confirm_device(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the selected device summary before manual confirmation."""
        if self._selected_device is None:
            return await self.async_step_pick_device()

        selected = self._selected_device

        if user_input is not None:
            suggested_rtsp_url = selected.get("suggested_rtsp_url") or (
                build_rtsp_url_without_credentials(
                    selected["ip"],
                    554,
                    build_default_rtsp_path(),
                )
            )
            default_name = " ".join(
                part
                for part in (
                    selected.get("manufacturer"),
                    selected.get("model"),
                )
                if part
            ).strip() or DEFAULT_NAME

            self._manual_defaults = {
                CONF_NAME: default_name,
                CONF_RTSP_URL: suggested_rtsp_url,
                CONF_USERNAME: self._manual_defaults.get(CONF_USERNAME, ""),
                CONF_PASSWORD: self._manual_defaults.get(CONF_PASSWORD, ""),
            }
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="confirm_device",
            data_schema=vol.Schema({}),
            description_placeholders={
                "manufacturer": selected.get("manufacturer") or "Unknown",
                "model": selected.get("model") or "Unknown",
                "ip": selected.get("ip") or "Unknown",
                "serial": selected.get("serial") or "Unavailable",
                "firmware": selected.get("firmware") or "Unavailable",
                "hardware_id": selected.get("hardware_id") or "Unavailable",
                "onvif_url": selected.get("onvif_url") or "Unavailable",
            },
        )

    async def async_step_manual(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle manual camera entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            result, errors = await self._async_finish_user_step(user_input)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="manual",
            data_schema=_build_manual_schema(
                self._manual_defaults if user_input is None else user_input
            ),
            errors=errors,
        )

    async def _async_finish_user_step(
        self,
        user_input: dict[str, Any],
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        """Validate user input and create the config entry."""
        errors: dict[str, str] = {}

        rtsp_url = user_input[CONF_RTSP_URL].strip()
        username = user_input[CONF_USERNAME].strip()
        password = user_input[CONF_PASSWORD]
        name = user_input.get(CONF_NAME, "").strip() or DEFAULT_NAME

        if not rtsp_url.startswith("rtsp://"):
            errors[CONF_RTSP_URL] = "invalid_rtsp_url"
            return None, errors

        host, port, embedded_user, embedded_pass, path = parse_rtsp_url(rtsp_url)
        if not host:
            errors[CONF_RTSP_URL] = "invalid_rtsp_url"
            return None, errors

        if embedded_user and not username:
            username = embedded_user
        if embedded_pass and not password:
            password = embedded_pass

        if not username or not password:
            errors["base"] = "invalid_auth"
            return None, errors

        session = async_get_clientsession(self.hass)
        client = ShowMoApiClient(
            host=host,
            port=port,
            username=username,
            password=password,
            session=session,
        )

        try:
            if not await client.test_connection():
                errors["base"] = "cannot_connect"
                return None, errors

            serial = await client.get_device_serial()
        except AuthenticationError:
            errors["base"] = "invalid_auth"
            return None, errors
        except (aiohttp.ClientError, OSError, TimeoutError, ValueError) as err:
            _log_flow_exception("Camera validation failed", err)
            errors["base"] = "cannot_connect"
            return None, errors
        except Exception as err:  # pragma: no cover - defensive guard
            _LOGGER.exception("Unexpected camera validation failure")
            errors["base"] = "unknown"
            return None, errors

        if serial:
            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_configured()
        else:
            _LOGGER.warning(
                "Could not fetch serial for %s. Duplicate detection is limited.",
                build_rtsp_url_without_credentials(host, port, path),
            )

        device = self._selected_device or {}
        return (
            self.async_create_entry(
                title=name,
                data={
                    CONF_NAME: name,
                    CONF_RTSP_URL: rtsp_url,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    "host": host,
                    "port": port,
                    "path": path,
                    "serial": serial,
                    "manufacturer": device.get("manufacturer"),
                    "model": device.get("model"),
                    "firmware": device.get("firmware"),
                },
            ),
            errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reconfigure_failed")

        errors: dict[str, str] = {}

        if user_input is not None:
            rtsp_url = user_input[CONF_RTSP_URL].strip()
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            name = user_input.get(CONF_NAME, "").strip() or DEFAULT_NAME

            if not rtsp_url.startswith("rtsp://"):
                errors[CONF_RTSP_URL] = "invalid_rtsp_url"
            else:
                host, port, embedded_user, embedded_pass, path = parse_rtsp_url(
                    rtsp_url
                )

                if not host:
                    errors[CONF_RTSP_URL] = "invalid_rtsp_url"
                else:
                    if embedded_user and not username:
                        username = embedded_user
                    if embedded_pass and not password:
                        password = embedded_pass

                    if not username or not password:
                        errors["base"] = "invalid_auth"
                    else:
                        session = async_get_clientsession(self.hass)
                        client = ShowMoApiClient(
                            host=host,
                            port=port,
                            username=username,
                            password=password,
                            session=session,
                        )
                        serial = entry.data.get("serial")
                        try:
                            if not await client.test_connection():
                                errors["base"] = "cannot_connect"
                            else:
                                serial = await client.get_device_serial()
                        except AuthenticationError:
                            errors["base"] = "invalid_auth"
                        except (aiohttp.ClientError, OSError, TimeoutError, ValueError) as err:
                            _log_flow_exception("Camera reconfigure validation failed", err)
                            errors["base"] = "cannot_connect"
                        except Exception as err:  # pragma: no cover - defensive guard
                            _LOGGER.exception("Unexpected reconfigure validation failure")
                            errors["base"] = "unknown"
                        else:
                            if errors:
                                return self.async_show_form(
                                    step_id="reconfigure",
                                    data_schema=_build_manual_schema(user_input),
                                    errors=errors,
                                )
                            return self.async_update_reload_and_abort(
                                entry,
                                title=name,
                                data={
                                    CONF_NAME: name,
                                    CONF_RTSP_URL: rtsp_url,
                                    CONF_USERNAME: username,
                                    CONF_PASSWORD: password,
                                    "host": host,
                                    "port": port,
                                    "path": path,
                                    "serial": serial,
                                    "manufacturer": entry.data.get("manufacturer"),
                                    "model": entry.data.get("model"),
                                    "firmware": entry.data.get("firmware"),
                                },
                                reason="reconfigure_successful",
                            )

        defaults = {
            CONF_NAME: entry.data.get(CONF_NAME, ""),
            CONF_RTSP_URL: entry.data.get(CONF_RTSP_URL, ""),
            CONF_USERNAME: entry.data.get(CONF_USERNAME, ""),
            CONF_PASSWORD: entry.data.get(CONF_PASSWORD, ""),
        }

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_manual_schema(
                defaults if user_input is None else user_input
            ),
            errors=errors,
        )
