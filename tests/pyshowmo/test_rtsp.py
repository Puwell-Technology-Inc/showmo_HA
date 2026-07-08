from urllib.parse import urlparse

from pyshowmo.rtsp import (
    build_default_rtsp_path,
    build_rtsp_url_with_credentials,
    build_rtsp_url_without_credentials,
    parse_rtsp_url,
)


def test_parse_rtsp_url_with_credentials_and_query() -> None:
    host, port, user, password, path = parse_rtsp_url(
        "rtsp://admin:123456@192.168.8.120:8554/live0_0.sdp?foo=bar"
    )

    assert host == "192.168.8.120"
    assert port == 8554
    assert user == "admin"
    assert password == "123456"
    assert path == "/live0_0.sdp?foo=bar"


def test_build_rtsp_urls() -> None:
    assert build_rtsp_url_with_credentials(
        "192.168.8.120", 554, "/live0_0.sdp", "admin", "123456"
    ) == "rtsp://admin:123456@192.168.8.120/live0_0.sdp"
    assert build_rtsp_url_without_credentials(
        "192.168.8.120", 554, "/live0_0.sdp"
    ) == "rtsp://192.168.8.120/live0_0.sdp"
    assert build_default_rtsp_path() == "/live0_0.sdp"


def test_build_rtsp_url_encodes_special_character_credentials() -> None:
    # Password with reserved characters must not corrupt authority parsing.
    password = "p/a?s#s@w :d"
    url = build_rtsp_url_with_credentials(
        "192.168.8.120", 8554, "/live0_0.sdp", "ad@min", password
    )

    # Encoding keeps the authority parseable: reserved chars in the userinfo no
    # longer leak into host/port/path (which is what corrupted ffmpeg parsing).
    parsed = urlparse(url)
    assert parsed.hostname == "192.168.8.120"
    assert parsed.port == 8554
    assert parsed.path == "/live0_0.sdp"


def test_rtsp_credentials_round_trip_through_parse() -> None:
    # build (encode) then parse (decode) must round-trip to the plaintext.
    username = "ad@min"
    password = "p/a?s#s@w :d"
    url = build_rtsp_url_with_credentials(
        "192.168.8.120", 554, "/live0_0.sdp", username, password
    )

    host, port, embedded_user, embedded_pass, path = parse_rtsp_url(url)
    assert host == "192.168.8.120"
    assert port == 554
    assert embedded_user == username
    assert embedded_pass == password
    assert path == "/live0_0.sdp"


def test_parse_rtsp_url_decodes_percent_encoded_credentials() -> None:
    host, port, user, password, path = parse_rtsp_url(
        "rtsp://ad%40min:p%40ss%2Fw@192.168.8.120/live0_0.sdp"
    )

    assert host == "192.168.8.120"
    assert port == 554
    assert user == "ad@min"
    assert password == "p@ss/w"
    assert path == "/live0_0.sdp"
