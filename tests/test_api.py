from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import custom_components.showmo.api as API_MODULE
from custom_components.showmo.api import ShowMoApiClient
from pyshowmo.onvif import parse_pull_messages


@pytest.mark.asyncio
async def test_discover_devices_converts_pyshowmo_models(monkeypatch):
    class FakeDevice:
        def to_dict(self):
            return {"ip": "192.168.8.120", "serial": "sn-1", "onvif": True}

    monkeypatch.setattr(
        API_MODULE,
        "discover_devices",
        AsyncMock(return_value=[FakeDevice()]),
    )

    results = await ShowMoApiClient.discover_devices(subnet="192.168.8.0/24")

    assert results == [{"ip": "192.168.8.120", "serial": "sn-1", "onvif": True}]


@pytest.mark.asyncio
async def test_get_device_serial_delegates_to_pyshowmo(monkeypatch):
    client = ShowMoApiClient("192.168.8.120", 554, "admin", "123456")
    monkeypatch.setattr(
        "custom_components.showmo.pyshowmo.client.ShowMoClient.get_device_serial",
        AsyncMock(return_value="sn-406A8EFF7512"),
    )

    assert await client.get_device_serial() == "sn-406A8EFF7512"
    await client.close()


def test_parse_pull_messages_extracts_motion_notifications():
    notifications = parse_pull_messages(
        """<?xml version="1.0" encoding="UTF-8"?>
        <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
                    xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
                    xmlns:tt="http://www.onvif.org/ver10/schema">
          <s:Body>
            <wsnt:NotificationMessage>
              <wsnt:Topic>tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic>
              <wsnt:Message>
                <tt:Message>
                  <tt:Data>
                    <tt:SimpleItem Name="IsMotion" Value="true"/>
                  </tt:Data>
                </tt:Message>
              </wsnt:Message>
            </wsnt:NotificationMessage>
          </s:Body>
        </s:Envelope>"""
    )

    assert len(notifications) == 1
    assert notifications[0].topic == "tns1:RuleEngine/CellMotionDetector/Motion"
    assert notifications[0].motion is True
    assert notifications[0].data_items == {"IsMotion": "true"}


@pytest.mark.asyncio
async def test_async_create_subscription_and_pull_messages(monkeypatch):
    client = ShowMoApiClient("192.168.8.120", 554, "admin", "123456")
    monkeypatch.setattr(
        "custom_components.showmo.pyshowmo.client.ShowMoClient.create_pullpoint_subscription",
        AsyncMock(
            return_value=SimpleNamespace(
                address="http://192.168.8.120:8080/subscription"
            )
        ),
    )
    monkeypatch.setattr(
        "custom_components.showmo.pyshowmo.client.ShowMoClient.pull_messages",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    topic="tns1:RuleEngine/CellMotionDetector/Motion",
                    source_items={},
                    data_items={"IsMotion": "false"},
                    motion=False,
                )
            ]
        ),
    )

    assert (
        await client.async_create_pullpoint_subscription()
        == "http://192.168.8.120:8080/subscription"
    )
    assert await client.async_pull_messages("http://192.168.8.120:8080/subscription") == [
        {
            "topic": "tns1:RuleEngine/CellMotionDetector/Motion",
            "source_items": {},
            "data_items": {"IsMotion": "false"},
            "motion": False,
        }
    ]
    await client.close()


@pytest.mark.asyncio
async def test_async_unsubscribe_delegates_to_pyshowmo(monkeypatch):
    client = ShowMoApiClient("192.168.8.120", 554, "admin", "123456")
    unsubscribe = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "custom_components.showmo.pyshowmo.client.ShowMoClient.unsubscribe",
        unsubscribe,
    )

    assert (
        await client.async_unsubscribe("http://192.168.8.120:8080/subscription")
        is True
    )
    unsubscribe.assert_awaited_once_with(
        "http://192.168.8.120:8080/subscription"
    )
    await client.close()
