from __future__ import annotations

import re
import socket
import uuid
from dataclasses import dataclass


WS_DISCOVERY_ADDRESS = ("239.255.255.250", 3702)


@dataclass(frozen=True)
class OnvifDevice:
    xaddr: str
    types: str | None = None
    scopes: str | None = None


def build_probe_message() -> bytes:
    message_id = f"uuid:{uuid.uuid4()}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>{message_id}</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>""".encode("utf-8")


def parse_probe_response(xml_text: str) -> list[OnvifDevice]:
    xaddr_matches = re.findall(r"<(?:\w+:)?XAddrs>(.*?)</(?:\w+:)?XAddrs>", xml_text, flags=re.DOTALL)
    types_match = re.search(r"<(?:\w+:)?Types>(.*?)</(?:\w+:)?Types>", xml_text, flags=re.DOTALL)
    scopes_match = re.search(r"<(?:\w+:)?Scopes>(.*?)</(?:\w+:)?Scopes>", xml_text, flags=re.DOTALL)
    devices: list[OnvifDevice] = []
    for match in xaddr_matches:
        for xaddr in match.split():
            devices.append(
                OnvifDevice(
                    xaddr=xaddr.strip(),
                    types=types_match.group(1).strip() if types_match else None,
                    scopes=scopes_match.group(1).strip() if scopes_match else None,
                )
            )
    return devices


def discover_onvif_devices(timeout_seconds: float = 3.0) -> list[OnvifDevice]:
    devices: list[OnvifDevice] = []
    probe = build_probe_message()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(timeout_seconds)
        sock.sendto(probe, WS_DISCOVERY_ADDRESS)
        while True:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            devices.extend(parse_probe_response(data.decode("utf-8", errors="ignore")))
    finally:
        sock.close()
    unique: dict[str, OnvifDevice] = {device.xaddr: device for device in devices}
    return list(unique.values())
