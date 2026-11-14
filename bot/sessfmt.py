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


# ---------------------------------------------------------------------------
# Parsing: kisi bhi library ki string padh kar (dc, ip, port, auth key) nikaalna (revoke ke liye)
# ---------------------------------------------------------------------------
class ParsedSession:
    def __init__(self, lib, dc_id, ip, port, key, api_id=None, user_id=None):
        self.lib, self.dc_id, self.ip, self.port, self.key = lib, dc_id, ip, port, key
        self.api_id, self.user_id = api_id, user_id


# Telegram production DC addresses (jab string me IP na ho, jaise Kurigram)
DC_IPS = {1: "149.154.175.53", 2: "149.154.167.51", 3: "149.154.175.100", 4: "149.154.167.91", 5: "91.108.56.130"}


def _b64d(s: str, urlsafe: bool) -> bytes:
    s = s.strip()
    s += "=" * (-len(s) % 4)
    return (base64.urlsafe_b64decode if urlsafe else base64.b64decode)(s.encode())


def _parse_telethon(s: str):
    import ipaddress
    if not s.startswith("1"):
        return None
    raw = _b64d(s[1:], True)
    if len(raw) == 263:
        ip = str(ipaddress.IPv4Address(raw[1:5]))
    elif len(raw) == 275:
        ip = str(ipaddress.IPv6Address(raw[1:17]))
    else:
        return None
    dc, port, key = raw[0], struct.unpack(">H", raw[-258:-256])[0], raw[-256:]
    if not 1 <= dc <= 5 or not port:
        return None
    return ParsedSession("telethon", dc, ip, port, key)


def _parse_gramjs(s: str):
    import ipaddress
    if not s.startswith("1"):
        return None
    raw = _b64d(s[1:], False)
    dc = raw[0]
    n = struct.unpack(">H", raw[1:3])[0]
    if len(raw) != 1 + 2 + n + 2 + 256 or not 1 <= dc <= 5:
        return None
    ip = raw[3:3 + n].decode()
    ipaddress.ip_address(ip)
    port = struct.unpack(">H", raw[3 + n:5 + n])[0]
    return ParsedSession("gramjs", dc, ip, port, raw[-256:])


def _parse_kurigram(s: str):
    raw = _b64d(s, True)
    if len(raw) != struct.calcsize(">BI?256sQ?"):
        return None
    dc, api_id, test, key, uid, _bot = struct.unpack(">BI?256sQ?", raw)
    if test or not 1 <= dc <= 5:
        return None
    return ParsedSession("kurigram", dc, DC_IPS[dc], 443, key, api_id=api_id, user_id=uid)


def _read_tl_bytes(buf: bytes, pos: int):
    n = buf[pos]
    if n == 254:
        n = int.from_bytes(buf[pos + 1:pos + 4], "little")
        start = pos + 4
    else:
        start = pos + 1
    data = buf[start:start + n]
    if len(data) != n:
        raise ValueError("short")
    end = start + n
    end += -(end - pos) % 4
    return data, end


def _parse_mtcute(s: str):
    buf = _b64d(s, True)
    if not buf or buf[0] != 3:
        return None
    flags = struct.unpack("<i", buf[1:5])[0]
    pos = 5
    dc_opt, pos = _read_tl_bytes(buf, pos)
    if flags & 4:
        _, pos = _read_tl_bytes(buf, pos)
    uid = None
    if flags & 1:
        uid = struct.unpack("<q", buf[pos:pos + 8])[0]
        pos += 12  # int53 + bool constructor
    key, pos = _read_tl_bytes(buf, pos)
    if len(key) != 256 or dc_opt[0] not in (1, 2) or flags & 2:
        return None
    if dc_opt[0] == 2 and dc_opt[2] & 4:
        return None  # test DC
    ip, p2 = _read_tl_bytes(dc_opt, 3)
    port = struct.unpack("<i", dc_opt[p2:p2 + 4])[0]
    return ParsedSession("mtcute", dc_opt[1], ip.decode(), port, key, user_id=uid)


def _parse_gotg(s: str):
    obj = json.loads(_b64d(s, False).decode())
    d = obj["Data"]
    key = base64.b64decode(d["AuthKey"])
    if len(key) != 256 or d["Config"].get("TestMode"):
        return None
    ip, _, port = d["Addr"].rpartition(":")
    return ParsedSession("gotg", int(d["DC"]), ip.strip("[]"), int(port), key)


def parse(string: str):
    """Kisi bhi supported library ki string detect + decode karo. Na mile to None."""
    string = "".join(string.split())
    if not string:
        return None
    for fn in (_parse_gotg, _parse_mtcute, _parse_kurigram, _parse_gramjs, _parse_telethon):
        try:
            r = fn(string)
        except Exception:
            continue
        if r:
            return r
    return None
