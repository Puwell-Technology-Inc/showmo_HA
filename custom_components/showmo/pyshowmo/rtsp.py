"""RTSP helpers for ShowMo cameras."""

from __future__ import annotations

from urllib.parse import urlparse


def parse_rtsp_url(rtsp_url: str) -> tuple[str, int, str | None, str | None, str]:
    """Parse RTSP URL and extract host, port, embedded credentials, and path."""
    parsed = urlparse(rtsp_url)
    host = parsed.hostname or ""
    port = parsed.port or 554
    embedded_user = parsed.username
    embedded_pass = parsed.password

    clean_path = parsed.path
    if parsed.query:
        clean_path += f"?{parsed.query}"

    return host, port, embedded_user, embedded_pass, clean_path


def build_rtsp_url_with_credentials(
    host: str,
    port: int,
    path: str,
    username: str,
    password: str,
) -> str:
    """Build RTSP URL with credentials embedded."""
    if not path.startswith("/"):
        path = f"/{path}"

    if port == 554:
        return f"rtsp://{username}:{password}@{host}{path}"
    return f"rtsp://{username}:{password}@{host}:{port}{path}"


def build_rtsp_url_without_credentials(host: str, port: int, path: str) -> str:
    """Build RTSP URL without credentials."""
    if not path.startswith("/"):
        path = f"/{path}"

    if port == 554:
        return f"rtsp://{host}{path}"
    return f"rtsp://{host}:{port}{path}"


def build_default_rtsp_path(main_stream: bool = True) -> str:
    """Return the default ShowMo RTSP path."""
    return "/live0_0.sdp" if main_stream else "/live0_1.sdp"
