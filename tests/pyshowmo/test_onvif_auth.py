"""Tests for WS-Security / WS-Addressing ONVIF requests and PTZ commands.

These guard the real-hardware findings: ShowMo/WinEye firmware rejects the
Events/Media/PTZ services unless a WS-Security UsernameToken is present, routes
event operations by their WS-Addressing action, and answers unsupported calls
with a SOAP fault (HTTP 200) that must be treated as failure.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pyshowmo.onvif import (
    build_soap_envelope,
    build_ws_security,
    create_pullpoint_subscription,
    is_soap_fault,
    parse_first_profile_token,
    parse_service_url,
    ptz_continuous_move,
    ptz_stop,
)


CAPABILITIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
    xmlns:tt="http://www.onvif.org/ver10/schema">
  <soap:Body>
    <tds:GetCapabilitiesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
      <tds:Capabilities>
        <tt:Events><tt:XAddr>http://cam:8080/onvif/events</tt:XAddr></tt:Events>
        <tt:Media><tt:XAddr>http://cam:8080/onvif/media</tt:XAddr></tt:Media>
        <tt:PTZ><tt:XAddr>http://cam:8080/onvif/ptz</tt:XAddr></tt:PTZ>
      </tds:Capabilities>
    </tds:GetCapabilitiesResponse>
  </soap:Body>
</soap:Envelope>"""

PROFILES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
    xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
    xmlns:tt="http://www.onvif.org/ver10/schema">
  <soap:Body>
    <trt:GetProfilesResponse>
      <trt:Profiles token="FixedProfile001" fixed="true">
        <tt:Name>FixedProfile01</tt:Name>
      </trt:Profiles>
    </trt:GetProfilesResponse>
  </soap:Body>
</soap:Envelope>"""

FAULT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
    xmlns:ter="http://www.onvif.org/ver10/error">
  <soap:Body>
    <soap:Fault>
      <soap:Code><soap:Value>soap:Sender</soap:Value>
        <soap:Subcode><soap:Value>ter:UnknownAction</soap:Value></soap:Subcode>
      </soap:Code>
      <soap:Reason><soap:Text xml:lang="en">Unknown Action</soap:Text></soap:Reason>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>"""

PTZ_OK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
    xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
  <soap:Body><tptz:ContinuousMoveResponse/></soap:Body>
</soap:Envelope>"""

SUBSCRIPTION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
    xmlns:wsa5="http://www.w3.org/2005/08/addressing">
  <s:Body>
    <wsnt:CreatePullPointSubscriptionResponse>
      <wsnt:SubscriptionReference>
        <wsa5:Address>http://cam:8080/onvif/subscriptions/1</wsa5:Address>
      </wsnt:SubscriptionReference>
    </wsnt:CreatePullPointSubscriptionResponse>
  </s:Body>
</s:Envelope>"""


class FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class RecordingSession:
    """Captures POST calls and returns a canned response."""

    def __init__(self, status: int, body: str) -> None:
        self._status = status
        self._body = body
        self.calls: list[dict] = []

    def post(self, url, data=None, auth=None, headers=None, timeout=None):  # noqa: ANN001
        self.calls.append({"url": url, "data": data, "headers": headers or {}})
        return FakeResponse(self._status, self._body)


def test_build_ws_security_contains_username_token() -> None:
    header = build_ws_security("admin", "123456")
    assert "<wsse:Security" in header
    assert "<wsse:Username>admin</wsse:Username>" in header
    assert "PasswordDigest" in header
    assert "<wsse:Nonce" in header
    assert "<wsu:Created>" in header


def test_build_ws_security_is_empty_without_credentials() -> None:
    assert build_ws_security(None, None) == ""


def test_build_soap_envelope_adds_addressing_and_security() -> None:
    envelope = build_soap_envelope(
        "<tev:CreatePullPointSubscription/>",
        username="admin",
        password="123456",
        action="urn:action:Create",
        to="http://cam:8080/onvif/events",
    )
    assert 'xmlns:s="http://www.w3.org/2003/05/soap-envelope"' in envelope
    assert "<wsa:Action" in envelope and "urn:action:Create" in envelope
    assert "<wsa:To" in envelope and "http://cam:8080/onvif/events" in envelope
    assert "<wsa:MessageID>" in envelope
    assert "<wsse:Security" in envelope
    assert "<tev:CreatePullPointSubscription/>" in envelope


def test_build_soap_envelope_escapes_camera_supplied_to() -> None:
    # The subscription-reference URL comes from the camera and may carry `&`.
    envelope = build_soap_envelope(
        "<tev:PullMessages/>",
        username="admin",
        password="pw",
        action="urn:action:Pull",
        to="http://cam:8080/onvif/subscription?idx=1&tok=2",
    )
    assert "idx=1&amp;tok=2" in envelope
    # Must stay well-formed XML despite the raw ampersand in `to`.
    ET.fromstring(envelope)


def test_build_soap_envelope_without_action_has_no_addressing() -> None:
    envelope = build_soap_envelope(
        "<trt:GetProfiles/>", username="admin", password="123456"
    )
    assert "<wsa:Action" not in envelope
    assert "<wsse:Security" in envelope


def test_is_soap_fault() -> None:
    assert is_soap_fault(FAULT_XML) is True
    assert is_soap_fault(SUBSCRIPTION_XML) is False
    assert is_soap_fault("not xml <<<") is True


def test_parse_service_url_for_each_category() -> None:
    base = "http://cam:8080/onvif/device_service"
    assert parse_service_url(CAPABILITIES_XML, base, "Events") == "http://cam:8080/onvif/events"
    assert parse_service_url(CAPABILITIES_XML, base, "Media") == "http://cam:8080/onvif/media"
    assert parse_service_url(CAPABILITIES_XML, base, "PTZ") == "http://cam:8080/onvif/ptz"


def test_parse_first_profile_token() -> None:
    assert parse_first_profile_token(PROFILES_XML) == "FixedProfile001"
    assert parse_first_profile_token("<empty/>") is None


@pytest.mark.asyncio
async def test_create_pullpoint_subscription_sends_ws_security_and_action() -> None:
    session = RecordingSession(200, SUBSCRIPTION_XML)
    subscription = await create_pullpoint_subscription(
        session=session,
        event_service_url="http://cam:8080/onvif/events",
        username="admin",
        password="123456",
    )

    assert subscription is not None
    assert subscription.address == "http://cam:8080/onvif/subscriptions/1"

    call = session.calls[0]
    assert "<wsse:Security" in call["data"]
    assert "CreatePullPointSubscription" in call["data"]
    assert 'action="' in call["headers"]["Content-Type"]


@pytest.mark.asyncio
async def test_create_pullpoint_subscription_returns_none_on_soap_fault() -> None:
    session = RecordingSession(200, FAULT_XML)
    subscription = await create_pullpoint_subscription(
        session=session,
        event_service_url="http://cam:8080/onvif/device_service",
        username="admin",
        password="123456",
    )
    assert subscription is None


@pytest.mark.asyncio
async def test_ptz_continuous_move_posts_profile_token_and_succeeds() -> None:
    session = RecordingSession(200, PTZ_OK_XML)
    ok = await ptz_continuous_move(
        session=session,
        ptz_service_url="http://cam:8080/onvif/ptz",
        profile_token="FixedProfile001",
        pan=0.5,
        username="admin",
        password="123456",
    )

    assert ok is True
    body = session.calls[0]["data"]
    assert "<tptz:ContinuousMove>" in body
    assert "<tptz:ProfileToken>FixedProfile001</tptz:ProfileToken>" in body
    assert 'x="0.5"' in body
    assert "<wsse:Security" in body


@pytest.mark.asyncio
async def test_ptz_command_returns_false_on_fault() -> None:
    session = RecordingSession(200, FAULT_XML)
    ok = await ptz_stop(
        session=session,
        ptz_service_url="http://cam:8080/onvif/ptz",
        profile_token="FixedProfile001",
        username="admin",
        password="123456",
    )
    assert ok is False
