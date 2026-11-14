"""Convert one logged-in MTProto auth key into the string formats of different libraries.

Every library stores the same thing (DC + auth key); only the packing differs.
"""
import base64
import hashlib
import json
import struct

LIBS = {
    "telethon": "Telethon",
    "mtcute": "mtcute",
    "kurigram": "Kurigram (Pyrogram)",
    "gramjs": "GramJS",
    "gotg": "GoTG (gotgproto)",
}


def _tl_bytes(data: bytes) -> bytes:
    """TL 'bytes' / 'string' serialization (length prefix + 4-byte alignment)."""
    n = len(data)
    if n < 254:
        out = bytes([n]) + data
    else:
        out = b"\xfe" + n.to_bytes(3, "little") + data
    return out + b"\x00" * (-len(out) % 4)


def telethon_string(dc_id: int, ip: str, port: int, key: bytes) -> str:
    import ipaddress
    packed_ip = ipaddress.ip_address(ip).packed
    raw = struct.pack(">B{}sH256s".format(len(packed_ip)), dc_id, packed_ip, port, key)
    return "1" + base64.urlsafe_b64encode(raw).decode()


def gramjs_string(dc_id: int, ip: str, port: int, key: bytes) -> str:
    addr = ip.encode()
    raw = bytes([dc_id]) + struct.pack(">H", len(addr)) + addr + struct.pack(">H", port) + key
    return "1" + base64.b64encode(raw).decode()


def kurigram_string(dc_id: int, api_id: int, user_id: int, key: bytes, is_bot: bool = False) -> str:
    raw = struct.pack(">BI?256sQ?", dc_id, api_id, False, key, user_id, is_bot)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def mtcute_string(dc_id: int, ip: str, port: int, user_id: int, key: bytes, is_bot: bool = False) -> str:
    dc_opt = bytes([2, dc_id, 0]) + _tl_bytes(ip.encode()) + struct.pack("<i", port)
    buf = bytes([3]) + struct.pack("<i", 1)  # version 3, flags: has self
    buf += _tl_bytes(dc_opt)
    buf += struct.pack("<q", user_id)  # int53 == little-endian int64 for normal ids
    buf += struct.pack("<I", 0x997275B5 if is_bot else 0xBC799737)
    buf += _tl_bytes(key)
    return base64.urlsafe_b64encode(buf).decode().rstrip("=")


def gotg_string(dc_id: int, ip: str, port: int, key: bytes) -> str:
    key_id = hashlib.sha1(key).digest()[12:20]
    data = {
        "Version": 1,
        "Data": {
            "Config": {
                "BlockedMode": False, "ForceTryIpv6": False, "Date": 0, "Expires": 0, "TestMode": False,
                "ThisDC": 0, "DCOptions": None, "DCTxtDomainName": "", "WebfileDCID": 0, "TmpSessions": 0,
            },
            "DC": dc_id,
            "Addr": f"{ip}:{port}",
            "AuthKey": base64.b64encode(key).decode(),
            "AuthKeyID": base64.b64encode(key_id).decode(),
            "Salt": 0,
        },
    }
    return base64.b64encode((json.dumps(data, separators=(",", ":")) + "\n").encode()).decode()


def build(lib: str, *, dc_id: int, ip: str, port: int, key: bytes, api_id: int, user_id: int) -> str:
    if lib == "telethon":
        return telethon_string(dc_id, ip, port, key)
    if lib == "gramjs":
        return gramjs_string(dc_id, ip, port, key)
    if lib == "kurigram":
        return kurigram_string(dc_id, api_id, user_id, key)
    if lib == "mtcute":
        return mtcute_string(dc_id, ip, port, user_id, key)
    if lib == "gotg":
        return gotg_string(dc_id, ip, port, key)
    raise ValueError(lib)


USAGE = {
    "telethon": (
        "from telethon import TelegramClient\nfrom telethon.sessions import StringSession\n"
        "client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)"
    ),
    "mtcute": (
        "import { TelegramClient } from '@mtcute/node'\n"
        "const tg = new TelegramClient({ apiId: API_ID, apiHash: API_HASH, storage: ':memory:' })\n"
        "await tg.start({ session: SESSION })"
    ),
    "kurigram": (
        "from pyrogram import Client\n"
        "app = Client('me', session_string=SESSION)"
    ),
    "gramjs": (
        "const { TelegramClient } = require('telegram');\n"
        "const { StringSession } = require('telegram/sessions');\n"
        "const client = new TelegramClient(new StringSession(SESSION), API_ID, API_HASH, {});"
    ),
    "gotg": (
        "gotgproto.NewClient(API_ID, API_HASH, gotgproto.ClientTypePhone(\"\"),\n"
        "  &gotgproto.ClientOpts{Session: sessionMaker.StringSession(SESSION)})"
    ),
}
