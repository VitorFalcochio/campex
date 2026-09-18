from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from edge_agent.camera_check import check_camera
from edge_agent.camera_connector import safe_source_ref


@dataclass(frozen=True)
class RtspConnection:
    url: str
    safe_url: str
    host: str | None
    port: int | None
    path: str | None
    username: str | None
    password: str | None


def build_rtsp_url(
    host: str | None = None,
    port: int | None = 554,
    path: str | None = None,
    username: str | None = None,
    password: str | None = None,
    full_url: str | None = None,
) -> RtspConnection:
    if full_url:
        parsed = urlsplit(full_url.strip())
        if parsed.scheme not in {"rtsp", "rtsps"}:
            raise ValueError("A URL completa precisa começar com rtsp:// ou rtsps://.")
        return RtspConnection(
            url=full_url.strip(),
            safe_url=safe_source_ref(full_url.strip()),
            host=parsed.hostname,
            port=parsed.port,
            path=parsed.path,
            username=parsed.username,
            password=parsed.password,
        )

    if not host:
        raise ValueError("Informe o host/IP ou uma URL RTSP completa.")
    clean_path = (path or "").strip()
    if clean_path and not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    user_info = ""
    if username:
        user_info = quote(username, safe="")
        if password:
            user_info += f":{quote(password, safe='')}"
        user_info += "@"
    port_text = f":{port or 554}"
    url = urlunsplit(("rtsp", f"{user_info}{host.strip()}{port_text}", clean_path, "", ""))
    return RtspConnection(
        url=url,
        safe_url=safe_source_ref(url),
        host=host.strip(),
        port=port or 554,
        path=clean_path,
        username=username,
        password=password,
    )


def test_rtsp_connection(connection: RtspConnection, timeout_seconds: float = 5.0) -> dict[str, object]:
    result = check_camera(connection.url, timeout_seconds=timeout_seconds)
    payload = result.to_dict()
    payload["referencia_segura"] = connection.safe_url
    payload["url_rtsp"] = connection.safe_url
    return payload


def public_connection_dict(connection: RtspConnection) -> dict[str, object]:
    data = asdict(connection)
    data.pop("url", None)
    data.pop("username", None)
    data.pop("password", None)
    return data
