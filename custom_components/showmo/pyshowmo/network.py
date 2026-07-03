"""Network helpers for ShowMo cameras."""

from __future__ import annotations

import asyncio
import socket
from ipaddress import IPv4Network


def get_local_ip(target_host: str = "8.8.8.8", target_port: int = 80) -> str | None:
    """Return the outbound local IPv4 address."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target_host, target_port))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def get_local_subnet(local_ip: str | None = None) -> str | None:
    """Return the outbound /24 subnet for the given or detected IP."""
    effective_ip = local_ip or get_local_ip()
    if not effective_ip:
        return None

    parts = effective_ip.split(".")
    if len(parts) != 4:
        return None

    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


async def check_rtsp(ip: str, port: int = 554, timeout: float = 1.0) -> bool:
    """Check whether the RTSP port is reachable."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return False

    writer.close()
    await writer.wait_closed()
    return True


def iter_subnet_hosts(subnet: str) -> list[str]:
    """Expand a subnet into individual IPv4 host strings."""
    return [str(ip) for ip in IPv4Network(subnet, strict=False).hosts()]
