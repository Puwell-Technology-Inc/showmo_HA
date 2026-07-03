from pyshowmo.onvif import (
    parse_device_information,
    parse_event_service_url,
    parse_pull_messages,
    parse_pullpoint_subscription,
    parse_ws_discovery_response,
)

DEVICE_INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body>
    <tds:GetDeviceInformationResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
      <tds:Manufacturer>puwell</tds:Manufacturer>
      <tds:Model>WIN2</tds:Model>
      <tds:FirmwareVersion>V5.32.2</tds:FirmwareVersion>
      <tds:SerialNumber>sn-406A8EFF7512</tds:SerialNumber>
      <tds:HardwareId>1.0</tds:HardwareId>
    </tds:GetDeviceInformationResponse>
  </s:Body>
</s:Envelope>"""

DISCOVERY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
    xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <s:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <a:EndpointReference>
          <a:Address>uuid:42313645-3646-4338-3245-393245343943</a:Address>
        </a:EndpointReference>
        <d:Types>tds:Device dn:NetworkVideoTransmitter</d:Types>
        <d:Scopes>onvif://www.onvif.org/hardware/puwell onvif://www.onvif.org/name/PW_406A8EFF7512</d:Scopes>
        <d:XAddrs>http://192.168.8.120:8080/onvif/device_service</d:XAddrs>
        <d:MetadataVersion>1</d:MetadataVersion>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </s:Body>
</s:Envelope>"""

CAPABILITIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
    xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <tds:GetCapabilitiesResponse>
      <tds:Capabilities>
        <tt:Events>
          <tt:XAddr>/onvif/events_service</tt:XAddr>
        </tt:Events>
      </tds:Capabilities>
    </tds:GetCapabilitiesResponse>
  </s:Body>
</s:Envelope>"""

PULLPOINT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
    xmlns:wsa5="http://www.w3.org/2005/08/addressing">
  <s:Body>
    <wsnt:CreatePullPointSubscriptionResponse>
      <wsnt:SubscriptionReference>
        <wsa5:Address>/onvif/subscriptions/1</wsa5:Address>
      </wsnt:SubscriptionReference>
      <wsnt:CurrentTime>2026-04-01T12:00:00Z</wsnt:CurrentTime>
      <wsnt:TerminationTime>2026-04-01T12:10:00Z</wsnt:TerminationTime>
    </wsnt:CreatePullPointSubscriptionResponse>
  </s:Body>
</s:Envelope>"""

PULL_MESSAGES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
    xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <wsnt:NotificationMessage>
      <wsnt:Topic>tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic>
      <wsnt:Message>
        <tt:Message>
          <tt:Source>
            <tt:SimpleItem Name="VideoSourceConfigurationToken" Value="VideoSourceToken"/>
          </tt:Source>
          <tt:Data>
            <tt:SimpleItem Name="State" Value="active"/>
          </tt:Data>
        </tt:Message>
      </wsnt:Message>
    </wsnt:NotificationMessage>
    <wsnt:NotificationMessage>
      <wsnt:Topic>tns1:Device/Trigger</wsnt:Topic>
      <wsnt:Message>
        <tt:Message>
          <tt:Data>
            <tt:SimpleItem Name="Other" Value="true"/>
          </tt:Data>
        </tt:Message>
      </wsnt:Message>
    </wsnt:NotificationMessage>
  </s:Body>
</s:Envelope>"""


def test_parse_device_information() -> None:
    info = parse_device_information(DEVICE_INFO_XML)

    assert info.manufacturer == "puwell"
    assert info.model == "WIN2"
    assert info.firmware_version == "V5.32.2"
    assert info.serial_number == "sn-406A8EFF7512"
    assert info.hardware_id == "1.0"


def test_parse_ws_discovery_response() -> None:
    matches = parse_ws_discovery_response(DISCOVERY_XML, "192.168.8.120", 3702)

    assert len(matches) == 1
    match = matches[0]
    assert match.ip == "192.168.8.120"
    assert match.onvif_url == "http://192.168.8.120:8080/onvif/device_service"
    assert match.endpoint == "uuid:42313645-3646-4338-3245-393245343943"
    assert match.onvif_port == 8080
    assert "tds:Device" in match.types


def test_parse_event_service_url() -> None:
    assert (
        parse_event_service_url(
            CAPABILITIES_XML,
            "http://192.168.8.120:8080/onvif/device_service",
        )
        == "http://192.168.8.120:8080/onvif/events_service"
    )


def test_parse_pullpoint_subscription() -> None:
    subscription = parse_pullpoint_subscription(
        PULLPOINT_XML,
        "http://192.168.8.120:8080/onvif/events_service",
    )

    assert subscription is not None
    assert subscription.address == "http://192.168.8.120:8080/onvif/subscriptions/1"
    assert subscription.current_time == "2026-04-01T12:00:00Z"
    assert subscription.termination_time == "2026-04-01T12:10:00Z"


def test_parse_pull_messages_handles_motion_and_non_motion_notifications() -> None:
    notifications = parse_pull_messages(PULL_MESSAGES_XML)

    assert len(notifications) == 2
    assert notifications[0].topic == "tns1:RuleEngine/CellMotionDetector/Motion"
    assert notifications[0].source_items == {
        "VideoSourceConfigurationToken": "VideoSourceToken"
    }
    assert notifications[0].data_items == {"State": "active"}
    assert notifications[0].motion is True
    assert notifications[1].topic == "tns1:Device/Trigger"
    assert notifications[1].motion is None
