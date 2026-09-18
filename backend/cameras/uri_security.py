from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from urllib.parse import urlsplit


BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "kubernetes.default",
    "kubernetes.default.svc",
    "0.0.0.0",
}

SSRF_SCHEMES = {"rtsp", "http", "https"}

_DNS_TIMEOUT_SECONDS = 1.0
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")

_RESOLVER_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="campex-ssrf-resolver")


class SourceURIValidationError(ValueError):
    """Raised when a camera source URI fails security validation."""


def validate_camera_source_uri(source_type: str, source_uri: str) -> str:
    if not source_uri or not source_uri.strip():
        raise SourceURIValidationError("Source URI must not be empty.")

    source_type = (source_type or "").strip().lower()

    if source_type == "webcam":
        return _validate_webcam_uri(source_uri)

    if source_type == "video_file":
        return _validate_local_video_uri(source_uri)

    if source_type in {"rtsp", "ip_camera"}:
        return _validate_network_uri(source_uri)

    raise SourceURIValidationError(f"Unsupported source type: {source_type}.")


def _validate_webcam_uri(source_uri: str) -> str:
    value = source_uri.strip()
    try:
        index = int(value)
    except ValueError:
        index = None
    if index is not None:
        if index < 0 or index > 99:
            raise SourceURIValidationError("Webcam device index must be between 0 and 99.")
        return str(index)
    lowered = value.lower()
    if "://" in lowered:
        raise SourceURIValidationError("Webcam source must be a device index, not a URL.")
    if not value.replace("_", "").replace("-", "").replace(".", "").replace(" ", "").isalnum():
        raise SourceURIValidationError("Webcam device path contains disallowed characters.")
    return value


def _validate_local_video_uri(source_uri: str) -> str:
    value = source_uri.strip()
    if "://" in value:
        scheme = value.split("://", 1)[0].lower()
        if scheme in {"file"}:
            raise SourceURIValidationError("File:// scheme is not permitted for video sources.")
        raise SourceURIValidationError(
            "Video file sources must be local paths, not URLs."
        )

    raw_path = Path(value).expanduser()
    parts = raw_path.parts
    if any(part == ".." for part in parts):
        raise SourceURIValidationError("Path traversal is not permitted in video file sources.")

    return source_uri


def _validate_network_uri(source_uri: str) -> str:
    parsed = urlsplit(source_uri)
    scheme = (parsed.scheme or "").lower()
    if scheme not in SSRF_SCHEMES:
        raise SourceURIValidationError(
            "RTSP/IP camera sources must use rtsp://, http://, or https://."
        )

    host = parsed.hostname
    if not host:
        raise SourceURIValidationError("Source URI must include a host.")

    if ":" in host and host not in BLOCKED_HOSTS:
        raise SourceURIValidationError("IPv6 literals are not supported as camera hosts.")

    if _host_is_blocked(host):
        raise SourceURIValidationError("Access to reserved or internal metadata hosts is blocked.")

    if not _ip_is_safe(_resolve_host_ips(host)):
        raise SourceURIValidationError(
            "Resolved host addresses internal/cloud-metadata targets; source blocked."
        )

    return source_uri


def _host_is_blocked(host: str) -> bool:
    normalized = host.strip().lower().rstrip(".")
    if normalized in BLOCKED_HOSTS:
        return True
    if normalized.endswith(".localhost") or normalized.endswith(".internal"):
        return True
    return False


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        return [ip]

    try:
        future = _RESOLVER_EXECUTOR.submit(socket.getaddrinfo, host, None, proto=socket.IPPROTO_TCP)
        infos = future.result(timeout=_DNS_TIMEOUT_SECONDS)
    except (FutureTimeoutError, socket.gaierror, socket.timeout, OSError):
        return []

    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        ips.append(addr)
    return ips


def _ip_is_safe(ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address]) -> bool:
    if not ips:
        return True
    for ip in ips:
        if _is_blocked_address(ip):
            return False
    return True


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return True
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK:
        return True
    return False
