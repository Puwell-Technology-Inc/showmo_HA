"""Constants shared by the pyshowmo package."""

from __future__ import annotations

ONVIF_DEVICE_SERVICE_PATH = "/onvif/device_service"
ONVIF_PTZ_SERVICE_PATH = "/onvif/ptz"
ONVIF_MEDIA_SERVICE_PATH = "/onvif/media"
WS_DISCOVERY_MULTICAST_ADDR = "239.255.255.250"
WS_DISCOVERY_MULTICAST_PORT = 3702
COMMON_SNAPSHOT_PATHS = (
    "/onvif/snapshot",
    "/snapshot.jpg",
    "/image.jpg",
    "/cgi-bin/snapshot.cgi",
)

# WS-* namespaces used to build authenticated ONVIF requests.
WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
WSA_NS = "http://www.w3.org/2005/08/addressing"
WSA_ANONYMOUS = "http://www.w3.org/2005/08/addressing/anonymous"
WSSE_PASSWORD_DIGEST_TYPE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
WSSE_BASE64_ENCODING = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"

# WS-Addressing action URIs for the ONVIF event operations. Real cameras route
# SOAP 1.2 event calls by this action, so it must be sent both as the wsa:Action
# header and the Content-Type "action" parameter.
ONVIF_ACTION_CREATE_PULLPOINT = (
    "http://www.onvif.org/ver10/events/wsdl/EventPortType/CreatePullPointSubscriptionRequest"
)
ONVIF_ACTION_PULL_MESSAGES = (
    "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
)
ONVIF_ACTION_UNSUBSCRIBE = (
    "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/UnsubscribeRequest"
)

XML_NAMESPACES = {
    "a": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "tev": "http://www.onvif.org/ver10/events/wsdl",
    "tptz": "http://www.onvif.org/ver20/ptz/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
    "wsa5": "http://www.w3.org/2005/08/addressing",
    "wsnt": "http://docs.oasis-open.org/wsn/b-2",
}

ONVIF_GET_DEVICE_INFO_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body>
    <GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/>
  </s:Body>
</s:Envelope>"""

# SOAP body fragments wrapped by ``build_soap_envelope`` (which supplies the
# envelope, namespace declarations, and WS-Security/WS-Addressing headers).
ONVIF_CREATE_PULLPOINT_INNER = (
    "<tev:CreatePullPointSubscription>"
    "<tev:InitialTerminationTime>PT10M</tev:InitialTerminationTime>"
    "</tev:CreatePullPointSubscription>"
)
ONVIF_UNSUBSCRIBE_INNER = "<wsnt:Unsubscribe/>"
ONVIF_GET_PROFILES_INNER = "<trt:GetProfiles/>"
