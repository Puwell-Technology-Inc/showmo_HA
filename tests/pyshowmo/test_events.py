from pyshowmo.onvif import (
    parse_event_service_url,
    parse_pull_messages,
    parse_pullpoint_subscription,
)


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

SUBSCRIPTION_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
            <tt:SimpleItem Name="VideoSourceConfigurationToken" Value="profile_1"/>
          </tt:Source>
          <tt:Data>
            <tt:SimpleItem Name="IsMotion" Value="true"/>
          </tt:Data>
        </tt:Message>
      </wsnt:Message>
    </wsnt:NotificationMessage>
  </s:Body>
</s:Envelope>"""

PULL_MESSAGES_TOPIC_FALLBACK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <wsnt:NotificationMessage>
      <wsnt:Topic>tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic>
      <wsnt:Message>
        <tt:Message>
          <tt:Data>
            <tt:SimpleItem Name="Value" Value="inactive"/>
          </tt:Data>
        </tt:Message>
      </wsnt:Message>
    </wsnt:NotificationMessage>
  </s:Body>
</s:Envelope>"""


def test_parse_event_service_url_joins_relative_xaddr() -> None:
    assert (
        parse_event_service_url(
            CAPABILITIES_XML,
            "http://192.168.8.120:8080/onvif/device_service",
        )
        == "http://192.168.8.120:8080/onvif/events_service"
    )


def test_parse_pullpoint_subscription_joins_relative_address() -> None:
    subscription = parse_pullpoint_subscription(
        SUBSCRIPTION_XML,
        "http://192.168.8.120:8080/onvif/events_service",
    )

    assert subscription is not None
    assert subscription.address == "http://192.168.8.120:8080/onvif/subscriptions/1"
    assert subscription.current_time == "2026-04-01T12:00:00Z"
    assert subscription.termination_time == "2026-04-01T12:10:00Z"


def test_parse_pull_messages_extracts_motion_notification() -> None:
    notifications = parse_pull_messages(PULL_MESSAGES_XML)

    assert len(notifications) == 1
    assert notifications[0].topic == "tns1:RuleEngine/CellMotionDetector/Motion"
    assert notifications[0].source_items == {
        "VideoSourceConfigurationToken": "profile_1"
    }
    assert notifications[0].data_items == {"IsMotion": "true"}
    assert notifications[0].motion is True


def test_parse_pull_messages_uses_topic_to_infer_motion_state() -> None:
    notifications = parse_pull_messages(PULL_MESSAGES_TOPIC_FALLBACK_XML)

    assert len(notifications) == 1
    assert notifications[0].data_items == {"Value": "inactive"}
    assert notifications[0].motion is False
