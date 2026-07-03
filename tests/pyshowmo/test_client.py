from unittest.mock import AsyncMock

import pytest

from pyshowmo.exceptions import AuthenticationError
from pyshowmo.client import ShowMoClient
from pyshowmo.models import DeviceInfo, OnvifNotification, PullPointSubscription


@pytest.mark.asyncio
async def test_get_snapshot_uses_working_snapshot_endpoint():
    class FakeResponse:
        def __init__(self, status: int, body: bytes, content_type: str) -> None:
            self.status = status
            self._body = body
            self.headers = {"Content-Type": content_type}

        async def read(self) -> bytes:
            return self._body

    class FakeRequestContextManager:
        def __init__(self, response: FakeResponse) -> None:
            self._response = response

        async def __aenter__(self) -> FakeResponse:
            return self._response

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, auth=None, timeout=None):  # noqa: ANN001
            del auth, timeout
            self.urls.append(url)
            if url.endswith("/onvif/snapshot"):
                response = FakeResponse(200, b"\xff\xd8test", "image/jpeg")
            else:
                response = FakeResponse(404, b"", "text/plain")
            return FakeRequestContextManager(response)

        async def close(self) -> None:
            return None

    fake_session = FakeSession()
    showmo = ShowMoClient(
        host="127.0.0.1",
        port=554,
        username="admin",
        password="123456",
    )
    showmo._session = fake_session

    snapshot = await showmo.get_snapshot(preferred_ports=(554,))
    await showmo.close()

    assert snapshot is not None
    url, image = snapshot
    assert url.endswith("/onvif/snapshot")
    assert image.startswith(b"\xff\xd8")
    assert fake_session.urls == ["http://127.0.0.1:554/onvif/snapshot"]


@pytest.mark.asyncio
async def test_get_device_information_raises_authentication_error(monkeypatch):
    showmo = ShowMoClient("192.168.8.120", 554, "admin", "123456")
    monkeypatch.setattr(
        "pyshowmo.client.check_onvif",
        AsyncMock(
            return_value=type(
                "Result",
                (),
                {
                    "auth_required": True,
                    "device_info": DeviceInfo(),
                },
            )()
        ),
    )

    with pytest.raises(AuthenticationError):
        await showmo.get_device_information()

    await showmo.close()


@pytest.mark.asyncio
async def test_get_event_service_url_probes_ports_and_caches(monkeypatch):
    showmo = ShowMoClient("192.168.8.120", 554, "admin", "123456")
    get_event_service_url = AsyncMock(
        side_effect=[
            None,
            "http://192.168.8.120:80/onvif/events_service",
        ]
    )
    monkeypatch.setattr("pyshowmo.client.get_event_service_url", get_event_service_url)

    assert (
        await showmo.get_event_service_url()
        == "http://192.168.8.120:80/onvif/events_service"
    )
    assert (
        await showmo.get_event_service_url()
        == "http://192.168.8.120:80/onvif/events_service"
    )
    assert get_event_service_url.await_count == 2

    await showmo.close()


@pytest.mark.asyncio
async def test_create_pullpoint_subscription_delegates(monkeypatch):
    showmo = ShowMoClient("192.168.8.120", 554, "admin", "123456")
    monkeypatch.setattr(
        showmo,
        "get_event_service_url",
        AsyncMock(return_value="http://192.168.8.120:8080/onvif/events_service"),
    )
    create_subscription = AsyncMock(
        return_value=PullPointSubscription(
            address="http://192.168.8.120:8080/onvif/subscriptions/1"
        )
    )
    monkeypatch.setattr(
        "pyshowmo.client.create_pullpoint_subscription",
        create_subscription,
    )

    subscription = await showmo.create_pullpoint_subscription()

    assert subscription is not None
    assert subscription.address == "http://192.168.8.120:8080/onvif/subscriptions/1"
    create_subscription.assert_awaited_once()
    await showmo.close()


@pytest.mark.asyncio
async def test_pull_messages_delegates(monkeypatch):
    showmo = ShowMoClient("192.168.8.120", 554, "admin", "123456")
    pull_messages = AsyncMock(
        return_value=[
            OnvifNotification(
                topic="tns1:RuleEngine/CellMotionDetector/Motion",
                motion=True,
            )
        ]
    )
    monkeypatch.setattr("pyshowmo.client.pull_messages", pull_messages)

    notifications = await showmo.pull_messages(
        "http://192.168.8.120:8080/onvif/subscriptions/1"
    )

    assert notifications is not None
    assert notifications[0].motion is True
    pull_messages.assert_awaited_once()
    await showmo.close()


@pytest.mark.asyncio
async def test_ptz_continuous_move_resolves_context_and_delegates(monkeypatch):
    showmo = ShowMoClient("192.168.8.120", 554, "admin", "123456")
    monkeypatch.setattr(
        "pyshowmo.client.get_service_url",
        AsyncMock(return_value="http://192.168.8.120:8080/onvif/ptz"),
    )
    monkeypatch.setattr(
        "pyshowmo.client.onvif_get_first_profile_token",
        AsyncMock(return_value="FixedProfile001"),
    )
    move = AsyncMock(return_value=True)
    monkeypatch.setattr("pyshowmo.client.onvif_ptz_continuous_move", move)

    assert await showmo.ptz_continuous_move(pan=0.5) is True

    move.assert_awaited_once()
    kwargs = move.await_args.kwargs
    assert kwargs["profile_token"] == "FixedProfile001"
    assert kwargs["ptz_service_url"] == "http://192.168.8.120:8080/onvif/ptz"
    assert kwargs["pan"] == 0.5
    await showmo.close()


@pytest.mark.asyncio
async def test_ptz_returns_false_when_profile_token_missing(monkeypatch):
    showmo = ShowMoClient("192.168.8.120", 554, "admin", "123456")
    monkeypatch.setattr(
        "pyshowmo.client.get_service_url",
        AsyncMock(return_value="http://192.168.8.120:8080/onvif/ptz"),
    )
    monkeypatch.setattr(
        "pyshowmo.client.onvif_get_first_profile_token",
        AsyncMock(return_value=None),
    )
    stop = AsyncMock(return_value=True)
    monkeypatch.setattr("pyshowmo.client.onvif_ptz_stop", stop)

    assert await showmo.ptz_stop() is False
    stop.assert_not_awaited()
    await showmo.close()


@pytest.mark.asyncio
async def test_unsubscribe_delegates(monkeypatch):
    showmo = ShowMoClient("192.168.8.120", 554, "admin", "123456")
    unsubscribe = AsyncMock(return_value=True)
    monkeypatch.setattr("pyshowmo.client.unsubscribe", unsubscribe)

    assert (
        await showmo.unsubscribe("http://192.168.8.120:8080/onvif/subscriptions/1")
        is True
    )
    unsubscribe.assert_awaited_once()
    await showmo.close()
