"""ONVIF parsing and request helpers for ShowMo cameras."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape as xml_escape
import xml.etree.ElementTree as ET

import aiohttp

from .constants import (
    ONVIF_ACTION_CREATE_PULLPOINT,
    ONVIF_ACTION_PULL_MESSAGES,
    ONVIF_ACTION_UNSUBSCRIBE,
    ONVIF_CREATE_PULLPOINT_INNER,
    ONVIF_DEVICE_SERVICE_PATH,
    ONVIF_GET_DEVICE_INFO_BODY,
    ONVIF_GET_PROFILES_INNER,
    ONVIF_UNSUBSCRIBE_INNER,
    WSA_ANONYMOUS,
    WSA_NS,
    WSSE_BASE64_ENCODING,
    WSSE_NS,
    WSSE_PASSWORD_DIGEST_TYPE,
    WSU_NS,
    XML_NAMESPACES,
)
from .models import DeviceInfo, DiscoveredDevice, OnvifNotification, PullPointSubscription

SOAP_CONTENT_TYPE = "application/soap+xml; charset=utf-8"
MOTION_TOPIC_MARKERS = ("motion", "cellmotiondetector")
MOTION_ITEM_NAMES = ("ismotion", "motion", "state", "logicalstate", "active")


def _local_name(tag: str) -> str:
    """Return the local part of an XML tag."""
    return tag.rsplit("}", 1)[-1]


def _bool_from_text(value: str | None) -> bool | None:
    """Parse a permissive ONVIF-style boolean string."""
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"true", "1", "on", "yes", "active"}:
        return True
    if normalized in {"false", "0", "off", "no", "inactive"}:
        return False
    return None


def _is_motion_topic(topic: str | None) -> bool:
    """Return whether the topic path looks like motion detection."""
    if not topic:
        return False

    topic_lower = topic.lower()
    return any(marker in topic_lower for marker in MOTION_TOPIC_MARKERS)


def _extract_simple_items(parent: ET.Element) -> dict[str, str]:
    """Extract tt:SimpleItem Name/Value pairs from an element subtree."""
    items: dict[str, str] = {}
    for item in parent.iter():
        if _local_name(item.tag) != "SimpleItem":
            continue

        name = item.attrib.get("Name")
        value = item.attrib.get("Value")
        if name and value is not None:
            items[name] = value

    return items


def _infer_motion_state(topic: str | None, data_items: dict[str, str]) -> bool | None:
    """Infer the motion state from topic and ONVIF message data."""
    for key, value in data_items.items():
        if key.lower() not in MOTION_ITEM_NAMES:
            continue
        motion = _bool_from_text(value)
        if motion is not None:
            return motion

    if not _is_motion_topic(topic):
        return None

    for value in data_items.values():
        motion = _bool_from_text(value)
        if motion is not None:
            return motion

    return None


def build_ws_security(username: str | None, password: str | None) -> str:
    """Build a WS-Security UsernameToken header with a PasswordDigest.

    Returns an empty string when no credentials are supplied. Real ShowMo/WinEye
    firmware rejects the Media, PTZ and Events services unless this header is
    present, even when HTTP Basic auth is also sent.
    """
    if not username and not password:
        return ""

    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = os.urandom(16)
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + (password or "").encode()).digest()
    ).decode()

    return (
        f'<wsse:Security s:mustUnderstand="1" xmlns:wsse="{WSSE_NS}" xmlns:wsu="{WSU_NS}">'
        "<wsse:UsernameToken>"
        f"<wsse:Username>{xml_escape(username or '')}</wsse:Username>"
        f'<wsse:Password Type="{WSSE_PASSWORD_DIGEST_TYPE}">{digest}</wsse:Password>'
        f'<wsse:Nonce EncodingType="{WSSE_BASE64_ENCODING}">'
        f"{base64.b64encode(nonce).decode()}</wsse:Nonce>"
        f"<wsu:Created>{created}</wsu:Created>"
        "</wsse:UsernameToken>"
        "</wsse:Security>"
    )


def build_soap_envelope(
    body_inner: str,
    *,
    username: str | None = None,
    password: str | None = None,
    action: str | None = None,
    to: str | None = None,
) -> str:
    """Wrap an operation fragment in a SOAP 1.2 envelope.

    A WS-Security header is added whenever credentials are supplied. When an
    ``action`` is given a WS-Addressing header (To/Action/MessageID/ReplyTo) is
    added as well; ONVIF event operations are dispatched by this action.
    """
    header_parts: list[str] = []

    if action is not None:
        message_id = "urn:uuid:" + os.urandom(16).hex()
        # ``to`` is camera-supplied for pull/unsubscribe (the subscription
        # reference URL), so it may carry ``&`` in a query string and must be
        # escaped to keep the request XML well-formed.
        header_parts.append(
            f'<wsa:To s:mustUnderstand="1">{xml_escape(to or WSA_ANONYMOUS)}</wsa:To>'
        )
        header_parts.append(
            f'<wsa:Action s:mustUnderstand="1">{xml_escape(action)}</wsa:Action>'
        )
        header_parts.append(f"<wsa:MessageID>{message_id}</wsa:MessageID>")
        header_parts.append(
            f"<wsa:ReplyTo><wsa:Address>{WSA_ANONYMOUS}</wsa:Address></wsa:ReplyTo>"
        )

    security = build_ws_security(username, password)
    if security:
        header_parts.append(security)

    header = f"<s:Header>{''.join(header_parts)}</s:Header>" if header_parts else ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
        ' xmlns:tds="http://www.onvif.org/ver10/device/wsdl"'
        ' xmlns:tev="http://www.onvif.org/ver10/events/wsdl"'
        ' xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"'
        ' xmlns:trt="http://www.onvif.org/ver10/media/wsdl"'
        ' xmlns:tt="http://www.onvif.org/ver10/schema"'
        f' xmlns:wsa="{WSA_NS}"'
        ' xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2">'
        f"{header}<s:Body>{body_inner}</s:Body></s:Envelope>"
    )


def is_soap_fault(xml_text: str) -> bool:
    """Return whether a SOAP response is a fault (or is unparseable)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return True

    return any(_local_name(element.tag) == "Fault" for element in root.iter())


async def send_onvif_request(
    session: aiohttp.ClientSession,
    url: str,
    body: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
    action: str | None = None,
) -> tuple[int, str] | None:
    """Send an ONVIF SOAP request and return the HTTP status and body."""
    auth = None
    if username or password:
        auth = aiohttp.BasicAuth(username or "", password or "")

    content_type = SOAP_CONTENT_TYPE
    if action:
        content_type = f'{SOAP_CONTENT_TYPE}; action="{action}"'

    try:
        async with session.post(
            url,
            data=body,
            auth=auth,
            headers={"Content-Type": content_type},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            response_text = await response.text()
    except (TimeoutError, aiohttp.ClientError):
        return None
    except (UnicodeDecodeError, LookupError):
        # Non-UTF-8 bodies or an unknown declared charset (e.g. GBK firmware
        # without a valid charset header) must not escape the "return None"
        # contract that every caller relies on to detect failure.
        return None

    return response.status, response_text


def parse_device_information(xml_text: str) -> DeviceInfo:
    """Parse ONVIF GetDeviceInformation SOAP response."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return DeviceInfo()

    info: dict[str, str] = {}
    for field in (
        "Manufacturer",
        "Model",
        "FirmwareVersion",
        "SerialNumber",
        "HardwareId",
    ):
        element = root.find(f".//tds:{field}", XML_NAMESPACES)
        if element is not None and element.text:
            info[field.lower()] = element.text.strip()

    return DeviceInfo(
        manufacturer=info.get("manufacturer"),
        model=info.get("model"),
        firmware_version=info.get("firmwareversion"),
        serial_number=info.get("serialnumber"),
        hardware_id=info.get("hardwareid"),
    )


def _safe_onvif_url_for_source(
    xaddrs: list[str],
    source_ip: str,
) -> tuple[str, int]:
    """Return an ONVIF device-service URL bound to the WS-Discovery source IP.

    WS-Discovery ProbeMatch responses are unauthenticated: any host on the LAN
    can answer a probe and put an arbitrary XAddr (even an off-network URL) in
    the reply, which would otherwise cause credentials to be sent to a host the
    attacker controls. Only accept an advertised XAddr when it uses http(s) and
    its host matches the UDP source IP; otherwise fall back to a conservative
    ``http://{source_ip}:{port}/onvif/device_service`` using the advertised port
    (or 80) so probing stays pinned to the responder.
    """
    for addr in xaddrs:
        parsed = urlparse(addr)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.hostname == source_ip:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return addr, port

    # No XAddr is bound to the responder: derive the port from the first
    # http(s) XAddr if present, otherwise default to 80.
    port = 80
    for addr in xaddrs:
        parsed = urlparse(addr)
        if parsed.scheme in ("http", "https") and parsed.port is not None:
            port = parsed.port
            break
    return f"http://{source_ip}:{port}{ONVIF_DEVICE_SERVICE_PATH}", port


def parse_ws_discovery_response(
    xml_text: str,
    source_ip: str,
    source_port: int,
) -> list[DiscoveredDevice]:
    """Parse WS-Discovery ProbeMatch responses."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    matches: list[DiscoveredDevice] = []

    for probe_match in root.findall(".//d:ProbeMatch", XML_NAMESPACES):
        endpoint = probe_match.findtext(
            "./a:EndpointReference/a:Address",
            default="",
            namespaces=XML_NAMESPACES,
        ).strip()
        types_text = probe_match.findtext(
            "./d:Types",
            default="",
            namespaces=XML_NAMESPACES,
        ).strip()
        scopes_text = probe_match.findtext(
            "./d:Scopes",
            default="",
            namespaces=XML_NAMESPACES,
        ).strip()
        xaddrs_text = probe_match.findtext(
            "./d:XAddrs",
            default="",
            namespaces=XML_NAMESPACES,
        ).strip()
        metadata_version = probe_match.findtext(
            "./d:MetadataVersion",
            default="",
            namespaces=XML_NAMESPACES,
        ).strip()

        xaddrs = [addr for addr in xaddrs_text.split() if addr]
        # Pin the probed URL to the source IP so a spoofed XAddr cannot
        # redirect credentialed requests to an attacker-controlled host.
        service_url, onvif_port = _safe_onvif_url_for_source(xaddrs, source_ip)

        matches.append(
            DiscoveredDevice(
                ip=source_ip,
                onvif_url=service_url,
                endpoint=endpoint or None,
                ws_port=source_port,
                onvif_port=onvif_port,
                types=[item for item in types_text.split() if item],
                scopes=[item for item in scopes_text.split() if item],
                xaddrs=xaddrs,
                metadata_version=metadata_version or None,
            )
        )

    return matches


def parse_service_url(xml_text: str, base_url: str, category: str) -> str | None:
    """Parse an ONVIF service XAddr for a capability category.

    ``category`` is the local element name published under the capabilities
    document, e.g. ``Events``, ``PTZ`` or ``Media``.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    for element in root.iter():
        if _local_name(element.tag) != category:
            continue
        for child in element.iter():
            if _local_name(child.tag) == "XAddr" and child.text:
                xaddr = child.text.strip()
                if xaddr:
                    return urljoin(base_url, xaddr)

    return None


def parse_event_service_url(xml_text: str, base_url: str) -> str | None:
    """Parse the ONVIF Events service XAddr from a GetCapabilities response."""
    return parse_service_url(xml_text, base_url, "Events")


def parse_first_profile_token(xml_text: str) -> str | None:
    """Return the first media profile token from a GetProfiles response."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    for element in root.iter():
        if _local_name(element.tag) == "Profiles":
            token = element.attrib.get("token")
            if token:
                return token

    return None


def parse_pullpoint_subscription(
    xml_text: str,
    base_url: str,
) -> PullPointSubscription | None:
    """Parse a PullPoint subscription address from CreatePullPointSubscription."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    address = root.findtext(
        ".//wsnt:SubscriptionReference/wsa5:Address",
        default="",
        namespaces=XML_NAMESPACES,
    ).strip()
    if not address:
        return None

    return PullPointSubscription(
        address=urljoin(base_url, address),
        current_time=root.findtext(
            ".//wsnt:CurrentTime",
            default=None,
            namespaces=XML_NAMESPACES,
        ),
        termination_time=root.findtext(
            ".//wsnt:TerminationTime",
            default=None,
            namespaces=XML_NAMESPACES,
        ),
    )


def parse_pull_messages(xml_text: str) -> list[OnvifNotification]:
    """Parse motion-related information from PullMessages responses."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    notifications: list[OnvifNotification] = []

    for notification in root.iter():
        if _local_name(notification.tag) != "NotificationMessage":
            continue

        topic = None
        source_items: dict[str, str] = {}
        data_items: dict[str, str] = {}

        for child in notification:
            local_name = _local_name(child.tag)
            if local_name == "Topic":
                topic = (child.text or "").strip() or None
            elif local_name == "Message":
                for message_part in child.iter():
                    part_name = _local_name(message_part.tag)
                    if part_name == "Source":
                        source_items.update(_extract_simple_items(message_part))
                    elif part_name == "Data":
                        data_items.update(_extract_simple_items(message_part))

        notifications.append(
            OnvifNotification(
                topic=topic,
                source_items=source_items,
                data_items=data_items,
                motion=_infer_motion_state(topic, data_items),
            )
        )

    return notifications


async def check_onvif_url(
    session: aiohttp.ClientSession,
    url: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> DiscoveredDevice | None:
    """Check whether the given ONVIF device service URL is reachable.

    Credentials are sent last: the endpoint is first probed anonymously so the
    camera password is never sprayed onto a host that has not proven itself to
    be an ONVIF service. Credentials are only replayed when the anonymous probe
    is challenged with 401 (a real ONVIF endpoint asking for auth). If the
    anonymous probe already returns 200, the credentials are not sent at all.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    if not parsed.hostname:
        return None

    # Anonymous probe first: do not disclose credentials until the endpoint
    # behaves like a real ONVIF service.
    result = await send_onvif_request(
        session=session,
        url=url,
        body=ONVIF_GET_DEVICE_INFO_BODY,
        timeout=timeout,
    )
    if result is None:
        return None
    response_status, response_text = result

    if response_status not in (200, 401):
        return None

    # Only replay credentials when the endpoint challenged the anonymous
    # probe with 401; a 200 means the device answered without auth.
    if response_status == 401 and (username or password):
        auth_result = await send_onvif_request(
            session=session,
            url=url,
            body=ONVIF_GET_DEVICE_INFO_BODY,
            username=username,
            password=password,
            timeout=timeout,
        )
        if auth_result is not None:
            auth_status, auth_text = auth_result
            if auth_status in (200, 401):
                response_status, response_text = auth_status, auth_text

    device_info = parse_device_information(response_text)
    return DiscoveredDevice(
        ip=parsed.hostname,
        onvif_url=url,
        onvif_port=parsed.port or (443 if parsed.scheme == "https" else 80),
        status=response_status,
        onvif=True,
        auth_required=response_status == 401,
        manufacturer=device_info.manufacturer,
        model=device_info.model,
        serial=device_info.serial_number,
        firmware=device_info.firmware_version,
        hardware_id=device_info.hardware_id,
        device_info=device_info,
    )


async def check_onvif(
    session: aiohttp.ClientSession,
    ip: str,
    port: int = 8080,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> DiscoveredDevice | None:
    """Check ONVIF on a host/port pair."""
    return await check_onvif_url(
        session,
        f"http://{ip}:{port}{ONVIF_DEVICE_SERVICE_PATH}",
        username=username,
        password=password,
        timeout=timeout,
    )


def _build_get_capabilities_body(category: str) -> str:
    """Build a GetCapabilities request for a single capability category."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        "<s:Body>"
        '<tds:GetCapabilities xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
        f"<tds:Category>{category}</tds:Category>"
        "</tds:GetCapabilities>"
        "</s:Body></s:Envelope>"
    )


async def get_service_url(
    session: aiohttp.ClientSession,
    device_service_url: str,
    category: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> str | None:
    """Return an ONVIF service URL for a capability category via GetCapabilities.

    Device management (GetCapabilities) is accepted with HTTP Basic alone on
    ShowMo firmware, so no WS-Security header is required here.
    """
    result = await send_onvif_request(
        session=session,
        url=device_service_url,
        body=_build_get_capabilities_body(category),
        username=username,
        password=password,
        timeout=timeout,
    )
    if result is None:
        return None

    status, response_text = result
    if status != 200:
        return None

    return parse_service_url(response_text, device_service_url, category)


async def get_event_service_url(
    session: aiohttp.ClientSession,
    device_service_url: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> str | None:
    """Return the ONVIF Events service URL from device capabilities."""
    return await get_service_url(
        session=session,
        device_service_url=device_service_url,
        category="Events",
        username=username,
        password=password,
        timeout=timeout,
    )


async def create_pullpoint_subscription(
    session: aiohttp.ClientSession,
    event_service_url: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 10.0,
) -> PullPointSubscription | None:
    """Create an ONVIF PullPoint subscription."""
    body = build_soap_envelope(
        ONVIF_CREATE_PULLPOINT_INNER,
        username=username,
        password=password,
        action=ONVIF_ACTION_CREATE_PULLPOINT,
        to=event_service_url,
    )
    result = await send_onvif_request(
        session=session,
        url=event_service_url,
        body=body,
        username=username,
        password=password,
        timeout=timeout,
        action=ONVIF_ACTION_CREATE_PULLPOINT,
    )
    if result is None:
        return None

    status, response_text = result
    if status != 200 or is_soap_fault(response_text):
        return None

    return parse_pullpoint_subscription(response_text, event_service_url)


async def pull_messages(
    session: aiohttp.ClientSession,
    subscription_url: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 70.0,
    message_limit: int = 10,
    pull_timeout: str = "PT60S",
) -> list[OnvifNotification] | None:
    """Pull ONVIF event messages from an existing subscription."""
    inner = (
        "<tev:PullMessages>"
        f"<tev:Timeout>{pull_timeout}</tev:Timeout>"
        f"<tev:MessageLimit>{message_limit}</tev:MessageLimit>"
        "</tev:PullMessages>"
    )
    body = build_soap_envelope(
        inner,
        username=username,
        password=password,
        action=ONVIF_ACTION_PULL_MESSAGES,
        to=subscription_url,
    )
    result = await send_onvif_request(
        session=session,
        url=subscription_url,
        body=body,
        username=username,
        password=password,
        timeout=timeout,
        action=ONVIF_ACTION_PULL_MESSAGES,
    )
    if result is None:
        return None

    status, response_text = result
    if status != 200 or is_soap_fault(response_text):
        return None

    return parse_pull_messages(response_text)


async def unsubscribe(
    session: aiohttp.ClientSession,
    subscription_url: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """Best-effort unsubscribe for a PullPoint subscription."""
    body = build_soap_envelope(
        ONVIF_UNSUBSCRIBE_INNER,
        username=username,
        password=password,
        action=ONVIF_ACTION_UNSUBSCRIBE,
        to=subscription_url,
    )
    result = await send_onvif_request(
        session=session,
        url=subscription_url,
        body=body,
        username=username,
        password=password,
        timeout=timeout,
        action=ONVIF_ACTION_UNSUBSCRIBE,
    )
    if result is None:
        return False

    status, response_text = result
    return status == 200 and not is_soap_fault(response_text)


async def get_first_profile_token(
    session: aiohttp.ClientSession,
    media_service_url: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 10.0,
) -> str | None:
    """Return the first media profile token (needed for PTZ operations)."""
    body = build_soap_envelope(
        ONVIF_GET_PROFILES_INNER,
        username=username,
        password=password,
    )
    result = await send_onvif_request(
        session=session,
        url=media_service_url,
        body=body,
        username=username,
        password=password,
        timeout=timeout,
    )
    if result is None:
        return None

    status, response_text = result
    if status != 200 or is_soap_fault(response_text):
        return None

    return parse_first_profile_token(response_text)


async def _send_ptz_command(
    session: aiohttp.ClientSession,
    ptz_service_url: str,
    body_inner: str,
    username: str | None,
    password: str | None,
    timeout: float,
) -> bool:
    """Send a WS-Security authenticated PTZ command and report success."""
    body = build_soap_envelope(body_inner, username=username, password=password)
    result = await send_onvif_request(
        session=session,
        url=ptz_service_url,
        body=body,
        username=username,
        password=password,
        timeout=timeout,
    )
    if result is None:
        return False

    status, response_text = result
    return status == 200 and not is_soap_fault(response_text)


async def ptz_continuous_move(
    session: aiohttp.ClientSession,
    ptz_service_url: str,
    profile_token: str,
    pan: float = 0.0,
    tilt: float = 0.0,
    zoom: float = 0.0,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """Issue an ONVIF ContinuousMove at the given pan/tilt/zoom velocities."""
    inner = (
        "<tptz:ContinuousMove>"
        f"<tptz:ProfileToken>{xml_escape(profile_token)}</tptz:ProfileToken>"
        "<tptz:Velocity>"
        f'<tt:PanTilt x="{pan}" y="{tilt}"/>'
        f'<tt:Zoom x="{zoom}"/>'
        "</tptz:Velocity>"
        "</tptz:ContinuousMove>"
    )
    return await _send_ptz_command(
        session, ptz_service_url, inner, username, password, timeout
    )


async def ptz_stop(
    session: aiohttp.ClientSession,
    ptz_service_url: str,
    profile_token: str,
    pan_tilt: bool = True,
    zoom: bool = True,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """Stop any ongoing ONVIF PTZ movement."""
    inner = (
        "<tptz:Stop>"
        f"<tptz:ProfileToken>{xml_escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:PanTilt>{'true' if pan_tilt else 'false'}</tptz:PanTilt>"
        f"<tptz:Zoom>{'true' if zoom else 'false'}</tptz:Zoom>"
        "</tptz:Stop>"
    )
    return await _send_ptz_command(
        session, ptz_service_url, inner, username, password, timeout
    )


async def ptz_goto_preset(
    session: aiohttp.ClientSession,
    ptz_service_url: str,
    profile_token: str,
    preset_token: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """Move the camera to a stored PTZ preset."""
    inner = (
        "<tptz:GotoPreset>"
        f"<tptz:ProfileToken>{xml_escape(profile_token)}</tptz:ProfileToken>"
        f"<tptz:PresetToken>{xml_escape(preset_token)}</tptz:PresetToken>"
        "</tptz:GotoPreset>"
    )
    return await _send_ptz_command(
        session, ptz_service_url, inner, username, password, timeout
    )


async def ptz_goto_home(
    session: aiohttp.ClientSession,
    ptz_service_url: str,
    profile_token: str,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """Move the camera to its PTZ home position."""
    inner = (
        "<tptz:GotoHomePosition>"
        f"<tptz:ProfileToken>{xml_escape(profile_token)}</tptz:ProfileToken>"
        "</tptz:GotoHomePosition>"
    )
    return await _send_ptz_command(
        session, ptz_service_url, inner, username, password, timeout
    )
