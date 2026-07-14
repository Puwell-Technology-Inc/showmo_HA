from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.showmo.api import AuthenticationError, DiscoveryError
from custom_components.showmo import config_flow as config_flow_module
from custom_components.showmo.const import CONF_RTSP_URL, DEFAULT_NAME, DOMAIN

from pytest_homeassistant_custom_component.common import MockConfigEntry


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
RECONFIGURE_SOURCE = "reconfigure"


@pytest.fixture(autouse=True)
def _bypass_manifest_dependencies():
    """Keep config flow tests focused on flow logic, not stream/av imports."""
    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        AsyncMock(return_value=None),
    ):
        yield


@pytest.fixture(autouse=True)
def _accept_credentials_by_default():
    """Pass the media-service credential check unless a test overrides it.

    Every validation path calls ShowMoApiClient.check_credentials, which
    would otherwise hit the network. Rejection is exercised explicitly in
    test_manual_flow_rejects_wrong_password_via_credential_check.
    """
    with patch.object(
        config_flow_module.ShowMoApiClient,
        "check_credentials",
        AsyncMock(return_value=True),
    ):
        yield


DISCOVERED_DEVICE = {
    "ip": "192.168.8.120",
    "onvif": True,
    "onvif_url": "http://192.168.8.120:8080/onvif/device_service",
    "manufacturer": "puwell",
    "model": "WIN2",
    "serial": "sn-406A8EFF7512",
    "firmware": "V5.32.2",
    "hardware_id": "1.0",
    "suggested_rtsp_url": "rtsp://192.168.8.120/live0_0.sdp",
}

MANUAL_INPUT = {
    CONF_NAME: "",
    CONF_RTSP_URL: "rtsp://192.168.8.120/live0_0.sdp",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "123456",
}


async def _start_manual_flow(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "manual"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    return result


async def _start_scan_flow(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "scan"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    return result


async def test_user_menu_offers_scan_and_manual(hass) -> None:
    """The initial flow should expose both setup paths."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["scan", "manual"]


async def test_scan_flow_creates_entry_after_device_confirmation(hass) -> None:
    """Scan flow should discover, confirm, and create an entry."""
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_local_subnet",
            return_value="192.168.8.0/24",
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "discover_devices",
            AsyncMock(return_value=[DISCOVERED_DEVICE]),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(return_value=DISCOVERED_DEVICE["serial"]),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] is FlowResultType.MENU

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "scan"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "scan"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "admin", CONF_PASSWORD: "123456"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "pick_device"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"device": "0"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm_device"
        assert result["description_placeholders"]["serial"] == DISCOVERED_DEVICE["serial"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MANUAL_INPUT,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"] == {
        CONF_NAME: DEFAULT_NAME,
        CONF_RTSP_URL: MANUAL_INPUT[CONF_RTSP_URL],
        CONF_USERNAME: MANUAL_INPUT[CONF_USERNAME],
        CONF_PASSWORD: MANUAL_INPUT[CONF_PASSWORD],
        "host": "192.168.8.120",
        "port": 554,
        "path": "/live0_0.sdp",
        "serial": DISCOVERED_DEVICE["serial"],
        "manufacturer": DISCOVERED_DEVICE["manufacturer"],
        "model": DISCOVERED_DEVICE["model"],
        "firmware": DISCOVERED_DEVICE["firmware"],
    }


async def test_scan_flow_blank_credentials_fall_back_to_factory_default(hass) -> None:
    """Leaving scan credentials blank should probe with the factory default admin/123456."""
    discover = AsyncMock(return_value=[DISCOVERED_DEVICE])
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_local_subnet",
            return_value="192.168.8.0/24",
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "discover_devices",
            discover,
        ),
    ):
        result = await _start_scan_flow(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "", CONF_PASSWORD: ""},
        )

    assert result["step_id"] == "pick_device"
    assert discover.await_args.kwargs["username"] == "admin"
    assert discover.await_args.kwargs["password"] == "123456"


async def test_manual_flow_rejects_wrong_password_via_credential_check(hass) -> None:
    """A wrong password must fail validation even though device info is anonymous.

    Real WinEye firmware answers GetDeviceInformation without auth, so only
    the media-service credential check can catch a bad password.
    """
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "check_credentials",
            AsyncMock(side_effect=AuthenticationError("ONVIF credentials rejected")),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(return_value=DISCOVERED_DEVICE["serial"]),
        ),
    ):
        result = await _start_manual_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MANUAL_INPUT,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_manual_flow_rejects_invalid_rtsp_url(hass) -> None:
    """Manual flow should reject malformed RTSP URLs before I/O."""
    result = await _start_manual_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            **MANUAL_INPUT,
            CONF_RTSP_URL: "http://192.168.8.120/live0_0.sdp",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {CONF_RTSP_URL: "invalid_rtsp_url"}


async def test_manual_flow_recovers_after_invalid_rtsp_url(hass) -> None:
    """Manual flow should recover after the user fixes invalid RTSP input."""
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(return_value=DISCOVERED_DEVICE["serial"]),
        ),
    ):
        result = await _start_manual_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                **MANUAL_INPUT,
                CONF_RTSP_URL: "http://192.168.8.120/live0_0.sdp",
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"
        assert result["errors"] == {CONF_RTSP_URL: "invalid_rtsp_url"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MANUAL_INPUT,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_manual_flow_maps_authentication_error_to_invalid_auth(hass) -> None:
    """Manual flow should surface ONVIF auth failures as invalid_auth."""
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(side_effect=AuthenticationError("bad credentials")),
        ),
    ):
        result = await _start_manual_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MANUAL_INPUT,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_manual_flow_maps_connection_failure_to_cannot_connect(hass) -> None:
    """Manual flow should surface failed reachability checks as cannot_connect."""
    with patch.object(
        config_flow_module.ShowMoApiClient,
        "test_connection",
        AsyncMock(return_value=False),
    ):
        result = await _start_manual_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MANUAL_INPUT,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_manual_flow_aborts_when_serial_is_already_configured(hass) -> None:
    """Manual flow should reject duplicate devices by serial."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DISCOVERED_DEVICE["serial"])
    entry.add_to_hass(hass)

    with patch.object(
        config_flow_module.ShowMoApiClient,
        "get_device_serial",
        AsyncMock(return_value=DISCOVERED_DEVICE["serial"]),
    ), patch.object(
        config_flow_module.ShowMoApiClient,
        "test_connection",
        AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] is FlowResultType.MENU

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "manual"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MANUAL_INPUT,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_scan_flow_reports_discovery_failure(hass) -> None:
    """Scan flow should surface discovery errors on the scan step."""
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_local_subnet",
            return_value="192.168.8.0/24",
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "discover_devices",
            AsyncMock(side_effect=DiscoveryError("boom")),
        ),
    ):
        result = await _start_scan_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "admin", CONF_PASSWORD: "123456"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    assert result["errors"] == {"base": "discovery_failed"}


async def test_scan_flow_maps_authentication_error_to_invalid_auth(hass) -> None:
    """Scan flow should surface ONVIF auth failures as invalid_auth."""
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_local_subnet",
            return_value="192.168.8.0/24",
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "discover_devices",
            AsyncMock(side_effect=AuthenticationError("bad credentials")),
        ),
    ):
        result = await _start_scan_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "admin", CONF_PASSWORD: "123456"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_scan_flow_reports_no_cameras_found(hass) -> None:
    """Scan flow should report when discovery returns no ONVIF cameras."""
    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_local_subnet",
            return_value="192.168.8.0/24",
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "discover_devices",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await _start_scan_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "admin", CONF_PASSWORD: "123456"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    assert result["errors"] == {"base": "no_cameras_found"}


async def test_scan_flow_rejects_invalid_selected_device(hass) -> None:
    """Scan flow should stay on pick_device when the selected index is invalid."""
    flow = config_flow_module.ShowMoConfigFlow()
    flow.hass = hass
    flow._discovered_devices = [DISCOVERED_DEVICE]
    result = await flow.async_step_pick_device(user_input={"device": "9"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_device"
    assert result["errors"] == {"base": "invalid_device"}


def _fake_update_reload_and_abort_factory(hass, entry):
    """Build a stand-in for async_update_reload_and_abort that mutates the entry."""

    def _fake_update_reload_and_abort(flow, updated_entry, **kwargs):
        hass.config_entries.async_update_entry(
            entry=updated_entry,
            # Reauth updates only credentials and passes no title.
            title=kwargs.get("title", updated_entry.title),
            data=kwargs["data"],
        )
        return flow.async_abort(reason=kwargs["reason"])

    return _fake_update_reload_and_abort


async def test_reconfigure_updates_existing_entry(hass) -> None:
    """Reconfigure should update entry data for the same camera and abort OK."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        unique_id="old-serial",
        data={
            CONF_NAME: "Front Door",
            CONF_RTSP_URL: "rtsp://192.168.8.120/live0_0.sdp",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "123456",
            "host": "192.168.8.120",
            "port": 554,
            "path": "/live0_0.sdp",
            "serial": "old-serial",
            "manufacturer": "puwell",
            "model": "WIN2",
            "firmware": "V5.32.2",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            # Same physical camera (same serial), only IP/credentials changed.
            AsyncMock(return_value="old-serial"),
        ),
        patch.object(
            config_flow_module.ShowMoConfigFlow,
            "async_update_reload_and_abort",
            autospec=True,
            side_effect=_fake_update_reload_and_abort_factory(hass, entry),
        ) as mock_update_reload_and_abort,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": RECONFIGURE_SOURCE,
                "entry_id": entry.entry_id,
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_NAME: "Garage",
                CONF_RTSP_URL: "rtsp://192.168.8.121/live0_0.sdp",
                CONF_USERNAME: "viewer",
                CONF_PASSWORD: "secret",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    mock_update_reload_and_abort.assert_called_once()
    assert entry.title == "Garage"
    assert entry.unique_id == "old-serial"
    assert entry.data == {
        CONF_NAME: "Garage",
        CONF_RTSP_URL: "rtsp://192.168.8.121/live0_0.sdp",
        CONF_USERNAME: "viewer",
        CONF_PASSWORD: "secret",
        "host": "192.168.8.121",
        "port": 554,
        "path": "/live0_0.sdp",
        "serial": "old-serial",
        "manufacturer": "puwell",
        "model": "WIN2",
        "firmware": "V5.32.2",
    }


async def test_reconfigure_preserves_serial_when_probe_returns_none(hass) -> None:
    """A transient serial fetch failure must keep the stored serial, not None."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        unique_id="old-serial",
        data={
            CONF_NAME: "Front Door",
            CONF_RTSP_URL: "rtsp://192.168.8.120/live0_0.sdp",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "123456",
            "host": "192.168.8.120",
            "port": 554,
            "path": "/live0_0.sdp",
            "serial": "old-serial",
            "manufacturer": "puwell",
            "model": "WIN2",
            "firmware": "V5.32.2",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(return_value=None),
        ),
        patch.object(
            config_flow_module.ShowMoConfigFlow,
            "async_update_reload_and_abort",
            autospec=True,
            side_effect=_fake_update_reload_and_abort_factory(hass, entry),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": RECONFIGURE_SOURCE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_NAME: "Front Door",
                CONF_RTSP_URL: "rtsp://192.168.8.121/live0_0.sdp",
                CONF_USERNAME: "admin",
                CONF_PASSWORD: "123456",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["serial"] == "old-serial"
    assert entry.unique_id == "old-serial"


async def test_reconfigure_aborts_on_different_device(hass) -> None:
    """Reconfigure pointed at a different camera should abort as wrong_device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        unique_id="old-serial",
        data={
            CONF_NAME: "Front Door",
            CONF_RTSP_URL: "rtsp://192.168.8.120/live0_0.sdp",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "123456",
            "host": "192.168.8.120",
            "port": 554,
            "path": "/live0_0.sdp",
            "serial": "old-serial",
            "manufacturer": "puwell",
            "model": "WIN2",
            "firmware": "V5.32.2",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(return_value="new-serial"),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": RECONFIGURE_SOURCE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_NAME: "Garage",
                CONF_RTSP_URL: "rtsp://192.168.8.121/live0_0.sdp",
                CONF_USERNAME: "viewer",
                CONF_PASSWORD: "secret",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    # The entry must be left untouched when the camera identity mismatches.
    assert entry.unique_id == "old-serial"
    assert entry.data["serial"] == "old-serial"
    assert entry.data["host"] == "192.168.8.120"


async def test_reconfigure_reports_connection_failure(hass) -> None:
    """Reconfigure should stay on the form when validation cannot connect."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        unique_id="old-serial",
        data={
            CONF_NAME: "Front Door",
            CONF_RTSP_URL: "rtsp://192.168.8.120/live0_0.sdp",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "123456",
            "host": "192.168.8.120",
            "port": 554,
            "path": "/live0_0.sdp",
            "serial": "old-serial",
        },
    )
    entry.add_to_hass(hass)

    with patch.object(
        config_flow_module.ShowMoApiClient,
        "test_connection",
        AsyncMock(return_value=False),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": RECONFIGURE_SOURCE,
                "entry_id": entry.entry_id,
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_NAME: "Garage",
                CONF_RTSP_URL: "rtsp://192.168.8.121/live0_0.sdp",
                CONF_USERNAME: "viewer",
                CONF_PASSWORD: "secret",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_maps_authentication_error_to_invalid_auth(hass) -> None:
    """Reconfigure should surface ONVIF auth failures as invalid_auth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        unique_id="old-serial",
        data={
            CONF_NAME: "Front Door",
            CONF_RTSP_URL: "rtsp://192.168.8.120/live0_0.sdp",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "123456",
            "host": "192.168.8.120",
            "port": 554,
            "path": "/live0_0.sdp",
            "serial": "old-serial",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(side_effect=AuthenticationError("bad credentials")),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": RECONFIGURE_SOURCE,
                "entry_id": entry.entry_id,
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_NAME: "Garage",
                CONF_RTSP_URL: "rtsp://192.168.8.121/live0_0.sdp",
                CONF_USERNAME: "viewer",
                CONF_PASSWORD: "secret",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "invalid_auth"}


def _build_reauth_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        unique_id="sn-406A8EFF7512",
        data={
            CONF_NAME: "Front Door",
            CONF_RTSP_URL: "rtsp://192.168.8.120/live0_0.sdp",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "123456",
            "host": "192.168.8.120",
            "port": 554,
            "path": "/live0_0.sdp",
            "serial": "sn-406A8EFF7512",
            "manufacturer": "puwell",
            "model": "WIN2",
            "firmware": "V5.32.2",
        },
    )


async def _start_reauth_flow(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    return result


async def test_reauth_updates_credentials_only(hass) -> None:
    """Reauth should replace the stored credentials and keep everything else."""
    entry = _build_reauth_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(return_value="sn-406A8EFF7512"),
        ),
        patch.object(
            config_flow_module.ShowMoConfigFlow,
            "async_update_reload_and_abort",
            autospec=True,
            side_effect=_fake_update_reload_and_abort_factory(hass, entry),
        ),
    ):
        result = await _start_reauth_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "admin", CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_USERNAME] == "admin"
    assert entry.data[CONF_PASSWORD] == "new-secret"
    # Everything but the credentials is untouched.
    assert entry.title == "Front Door"
    assert entry.data[CONF_RTSP_URL] == "rtsp://192.168.8.120/live0_0.sdp"
    assert entry.data["serial"] == "sn-406A8EFF7512"
    assert entry.data["model"] == "WIN2"


async def test_reauth_maps_authentication_error_to_invalid_auth(hass) -> None:
    """Wrong new credentials should re-show the form with invalid_auth."""
    entry = _build_reauth_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(side_effect=AuthenticationError("bad credentials")),
        ),
    ):
        result = await _start_reauth_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "admin", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == "123456"


async def test_reauth_aborts_on_different_device(hass) -> None:
    """Reauth must not adopt credentials that belong to another camera."""
    entry = _build_reauth_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(
            config_flow_module.ShowMoApiClient,
            "test_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            config_flow_module.ShowMoApiClient,
            "get_device_serial",
            AsyncMock(return_value="sn-DIFFERENT"),
        ),
    ):
        result = await _start_reauth_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USERNAME: "admin", CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_PASSWORD] == "123456"


def _schema_field(schema, key: str):
    """Return the validator for a marker whose schema key matches ``key``."""
    for marker, validator in schema.schema.items():
        if marker.schema == key:
            return validator
    raise AssertionError(f"{key} not found in schema")


@pytest.mark.parametrize(
    "builder",
    [config_flow_module._build_manual_schema, config_flow_module._build_scan_schema],
)
def test_password_field_uses_password_selector(builder):
    """The password field should render masked; username stays plain text."""
    from homeassistant.helpers.selector import TextSelector, TextSelectorType

    schema = builder()
    password = _schema_field(schema, CONF_PASSWORD)
    assert isinstance(password, TextSelector)
    assert password.config["type"] == TextSelectorType.PASSWORD.value

    username = _schema_field(schema, CONF_USERNAME)
    assert username is str
