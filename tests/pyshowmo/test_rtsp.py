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
