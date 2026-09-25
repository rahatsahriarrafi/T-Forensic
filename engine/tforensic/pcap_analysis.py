"""Wireshark-style PCAP analysis — tshark when available, pure-Python fallback."""
from __future__ import annotations

import re
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Active capture session (one at a time for the API)
_ACTIVE: Optional["PcapSession"] = None

MAX_PACKETS_SCAN = 50_000
DEFAULT_LIST = 200

# Extensions accepted as network packet captures (Wireshark-style)
PCAP_EXTENSIONS = frozenset({
    ".pcap", ".pcapng", ".cap", ".dmp", ".pkt",
    ".snoop", ".netmon", ".ntar", ".erf", ".bfr",
    ".rf5", ".tpc", ".fdc", ".enc", ".tr1", ".5vw",
    ".erp", ".k12", ".vwr", ".mplog", ".ipfix",
    ".pklg",  # Apple PacketLogger
})


def tshark_bin() -> Optional[str]:
    return shutil.which("tshark") or shutil.which("dumpcap")


def capinfos_bin() -> Optional[str]:
    return shutil.which("capinfos")


def packet_extensions() -> list[str]:
    return sorted(e.lstrip(".") for e in PCAP_EXTENSIONS)


def is_pcap_file(path: str | Path) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    ext = path.suffix.lower()
    if ext in PCAP_EXTENSIONS:
        return True
    name = path.name.lower()
    if any(name.endswith(s) for s in (".pcap.gz", ".pcapng.gz", ".cap.gz")):
        return True
    try:
        with open(path, "rb") as f:
            mag = f.read(8)
        if mag[:4] in (
            b"\xd4\xc3\xb2\xa1",
            b"\xa1\xb2\xc3\xd4",
            b"\x4d\x3c\xb2\xa1",
            b"\xa1\xb2\x3c\x4d",
            b"\x0a\x0d\x0d\x0a",
        ):
            return True
        if mag[:4] in (b"RTSS", b"GMBU"):
            return True
    except OSError:
        return False
    return False


@dataclass
class PcapSession:
    path: str
    size: int
    opened_at: float = field(default_factory=time.time)
    packet_count: Optional[int] = None
    duration: Optional[float] = None
    link_type: str = ""
    engine: str = "tshark"  # tshark | native

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "name": Path(self.path).name,
            "size": self.size,
            "opened_at": self.opened_at,
            "packet_count": self.packet_count,
            "duration": self.duration,
            "link_type": self.link_type,
            "engine": self.engine,
            "tshark": bool(tshark_bin()),
        }


def active() -> Optional[PcapSession]:
    return _ACTIVE


def close() -> None:
    global _ACTIVE
    _ACTIVE = None


def open_pcap(path: str | Path) -> PcapSession:
    global _ACTIVE
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"not found: {path}")
    if not is_pcap_file(path):
        raise ValueError(f"not a PCAP/PCAPNG capture: {path}")
    size = path.stat().st_size
    sess = PcapSession(path=str(path), size=size)
    if tshark_bin():
        sess.engine = "tshark"
        meta = _tshark_meta(str(path))
        sess.packet_count = meta.get("packets")
        sess.duration = meta.get("duration")
        sess.link_type = meta.get("link") or ""
    else:
        sess.engine = "native"
        meta = _native_meta(str(path))
        sess.packet_count = meta.get("packets")
        sess.duration = meta.get("duration")
        sess.link_type = meta.get("link") or "ethernet"
    _ACTIVE = sess
    return sess


def _run(cmd: list[str], timeout: float = 120) -> str:
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if p.returncode not in (0, 1):  # tshark often exits 1 with warnings
        err = (p.stderr or p.stdout or "").strip()[:500]
        if err and "appears to have been cut short" not in err.lower():
            # still return stdout if useful
            if not p.stdout.strip():
                raise RuntimeError(err or f"command failed: {cmd[0]}")
    return p.stdout or ""


def _tshark_meta(path: str) -> dict:
    out: dict[str, Any] = {}
    ci = capinfos_bin()
    if ci:
        raw = _run([ci, "-c", "-u", "-t", "-y", path], timeout=60)
        for ln in raw.splitlines():
            if "Number of packets" in ln:
                m = re.search(r":\s*([\d.]+)", ln)
                if m:
                    out["packets"] = int(float(m.group(1)))
            elif "Capture duration" in ln:
                m = re.search(r":\s*([\d.]+)", ln)
                if m:
                    out["duration"] = float(m.group(1))
            elif "File encapsulation" in ln or "Packet size limit" in ln:
                pass
            elif ln.lower().startswith("file encapsulation") or "encapsulation" in ln.lower():
                parts = ln.split(":", 1)
                if len(parts) == 2:
                    out["link"] = parts[1].strip()
    if out.get("packets") is None:
        # count via tshark (capped)
        raw = _run(
            [tshark_bin(), "-r", path, "-T", "fields", "-e", "frame.number", "-c", str(MAX_PACKETS_SCAN)],
            timeout=180,
        )
        nums = [ln for ln in raw.splitlines() if ln.strip().isdigit()]
        out["packets"] = len(nums)
    return out


def summary() -> dict:
    sess = _ACTIVE
    if not sess:
        return {"open": False}
    data = sess.as_dict()
    data["open"] = True
    data["protocols"] = protocol_stats(limit=20)
    data["charts"] = {
        "protocols": data["protocols"],
        "conversations": [
            {"label": f"{c['a']} ↔ {c['b']}", "count": c["frames"]}
            for c in conversations(kind="ip", limit=10)
        ],
    }
    return data


def packet_list(
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIST,
    display_filter: str = "",
) -> dict:
    sess = _ACTIVE
    if not sess:
        raise RuntimeError("no PCAP open")
    limit = max(1, min(int(limit), 2000))
    offset = max(0, int(offset))
    if sess.engine == "tshark" and tshark_bin():
        return _tshark_packets(sess.path, offset, limit, display_filter)
    return _native_packets(sess.path, offset, limit)


def _tshark_packets(path: str, offset: int, limit: int, yfilter: str) -> dict:
    need = offset + limit
    cmd = [
        tshark_bin(), "-r", path,
        "-T", "fields",
        "-E", "separator=\t",
        "-E", "quote=n",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "eth.src",
        "-e", "eth.dst",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "ipv6.src",
        "-e", "ipv6.dst",
        "-e", "_ws.col.Protocol",
        "-e", "frame.len",
        "-e", "_ws.col.Info",
        "-c", str(min(need, MAX_PACKETS_SCAN)),
    ]
    if yfilter.strip():
        cmd.extend(["-Y", yfilter.strip()])
    raw = _run(cmd, timeout=180)
    rows = []
    for ln in raw.splitlines():
        parts = ln.split("\t")
        while len(parts) < 11:
            parts.append("")
        num, trel, es, ed, ips, ipd, v6s, v6d, proto, length, info = parts[:11]
        src = ips or v6s or es or ""
        dst = ipd or v6d or ed or ""
        try:
            n = int(num)
        except ValueError:
            continue
        rows.append({
            "no": n,
            "time": float(trel) if trel else 0.0,
            "src": src,
            "dst": dst,
            "proto": proto or "?",
            "length": int(length) if length.isdigit() else 0,
            "info": info[:200],
        })
    sliced = rows[offset : offset + limit]
    return {
        "packets": sliced,
        "offset": offset,
        "limit": limit,
        "returned": len(sliced),
        "filter": yfilter,
        "engine": "tshark",
    }


def packet_detail(frame_no: int) -> dict:
    sess = _ACTIVE
    if not sess:
        raise RuntimeError("no PCAP open")
    if sess.engine == "tshark" and tshark_bin():
        raw = _run(
            [
                tshark_bin(), "-r", sess.path,
                "-Y", f"frame.number=={int(frame_no)}",
                "-V",
                "-c", "1",
            ],
            timeout=60,
        )
        hexraw = _run(
            [
                tshark_bin(), "-r", sess.path,
                "-Y", f"frame.number=={int(frame_no)}",
                "-x",
                "-c", "1",
            ],
            timeout=60,
        )
        return {
            "no": int(frame_no),
            "tree": raw.strip()[:50_000],
            "hex": hexraw.strip()[:30_000],
            "engine": "tshark",
        }
    pkts = _native_packets(sess.path, max(0, frame_no - 1), 1)
    if not pkts["packets"]:
        raise LookupError(f"frame {frame_no} not found")
    p = pkts["packets"][0]
    return {
        "no": frame_no,
        "tree": f"Native parser\n  {p.get('info')}\n  {p.get('src')} → {p.get('dst')} {p.get('proto')}",
        "hex": p.get("hex") or "",
        "engine": "native",
    }


def protocol_stats(limit: int = 20) -> list[dict]:
    sess = _ACTIVE
    if not sess:
        return []
    if sess.engine == "tshark" and tshark_bin():
        raw = _run([tshark_bin(), "-r", sess.path, "-q", "-z", "io,phs"], timeout=120)
        return _parse_phs(raw, limit=limit)
    return _native_proto_stats(sess.path, limit=limit)


def _parse_phs(raw: str, limit: int = 20) -> list[dict]:
    counts: dict[str, int] = {}
    for ln in raw.splitlines():
        m = re.match(r"^\s+([A-Za-z0-9_\-\.]+)\s+frames:(\d+)", ln)
        if not m:
            continue
        name, n = m.group(1), int(m.group(2))
        if name.lower() in ("frame", "frames", "bytes"):
            continue
        counts[name] = max(counts.get(name, 0), n)
    items = [{"label": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return items[:limit]


def conversations(*, kind: str = "ip", limit: int = 30) -> list[dict]:
    sess = _ACTIVE
    if not sess:
        return []
    kind = (kind or "ip").lower()
    if kind not in ("ip", "tcp", "udp", "ipv6", "ethernet"):
        kind = "ip"
    if sess.engine == "tshark" and tshark_bin():
        raw = _run([tshark_bin(), "-r", sess.path, "-q", "-z", f"conv,{kind}"], timeout=120)
        return _parse_conv(raw, limit=limit)
    return _native_conversations(sess.path, limit=limit)


def _parse_conv(raw: str, limit: int = 30) -> list[dict]:
    rows = []
    for ln in raw.splitlines():
        if "<->" not in ln and "↔" not in ln:
            continue
        ln = ln.replace("↔", "<->")
        # Classic: A <-> B  f1 b1 bytes  f2 b2 bytes  total_f total_b bytes  start dur
        m = re.match(
            r"^\s*(\S+)\s+<->\s+(\S+)\s+"
            r"(\d+)\s+(\d+)\s+bytes\s+"
            r"(\d+)\s+(\d+)\s+bytes\s+"
            r"(\d+)\s+(\d+)\s+bytes",
            ln,
        )
        if m:
            a, b, f1, b1, f2, b2, frames, bytes_ = m.groups()
            rows.append({
                "a": a,
                "b": b,
                "frames": int(frames),
                "bytes": int(bytes_),
                "ab_frames": int(f1),
                "ba_frames": int(f2),
            })
            continue
        # Numeric-only fallback (older/tabbed)
        m2 = re.match(
            r"^\s*(\S+)\s+<->\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
            ln,
        )
        if m2:
            a, b, f1, b1, f2, b2, frames, bytes_ = m2.groups()
            rows.append({
                "a": a,
                "b": b,
                "frames": int(frames),
                "bytes": int(bytes_),
                "ab_frames": int(f1),
                "ba_frames": int(f2),
            })
    rows.sort(key=lambda r: -r["frames"])
    return rows[:limit]


def dns_queries(limit: int = 100) -> list[dict]:
    sess = _ACTIVE
    if not sess or not tshark_bin():
        return []
    raw = _run(
        [
            tshark_bin(), "-r", sess.path,
            "-Y", "dns.flags.response==0",
            "-T", "fields",
            "-E", "separator=\t",
            "-e", "frame.number",
            "-e", "ip.src",
            "-e", "dns.qry.name",
            "-e", "dns.qry.type",
            "-c", str(limit),
        ],
        timeout=90,
    )
    out = []
    for ln in raw.splitlines():
        parts = ln.split("\t")
        while len(parts) < 4:
            parts.append("")
        out.append({
            "no": int(parts[0]) if parts[0].isdigit() else 0,
            "src": parts[1],
            "query": parts[2],
            "type": parts[3],
        })
    return out


def http_hosts(limit: int = 100) -> list[dict]:
    sess = _ACTIVE
    if not sess or not tshark_bin():
        return []
    raw = _run(
        [
            tshark_bin(), "-r", sess.path,
            "-Y", "http.request",
            "-T", "fields",
            "-E", "separator=\t",
            "-e", "frame.number",
            "-e", "ip.src",
            "-e", "ip.dst",
            "-e", "http.host",
            "-e", "http.request.method",
            "-e", "http.request.uri",
            "-c", str(limit),
        ],
        timeout=90,
    )
    out = []
    for ln in raw.splitlines():
        parts = ln.split("\t")
        while len(parts) < 6:
            parts.append("")
        out.append({
            "no": int(parts[0]) if parts[0].isdigit() else 0,
            "src": parts[1],
            "dst": parts[2],
            "host": parts[3],
            "method": parts[4],
            "uri": parts[5][:200],
        })
    return out


# ---- Pure-Python classic PCAP fallback (Ethernet/IPv4/TCP/UDP) ----

def _native_meta(path: str) -> dict:
    pkts = _native_iter(path, max_packets=MAX_PACKETS_SCAN)
    if not pkts:
        return {"packets": 0, "duration": 0.0, "link": "unknown"}
    dur = pkts[-1]["time"] - pkts[0]["time"] if len(pkts) > 1 else 0.0
    return {"packets": len(pkts), "duration": max(0.0, dur), "link": "ethernet"}


def _native_packets(path: str, offset: int, limit: int) -> dict:
    allp = _native_iter(path, max_packets=offset + limit + 1)
    sliced = allp[offset : offset + limit]
    for p in sliced:
        p.pop("hex", None)  # keep list light; detail re-reads
    # re-include hex only if single? skip
    return {
        "packets": [
            {k: v for k, v in p.items() if k != "raw"}
            for p in sliced
        ],
        "offset": offset,
        "limit": limit,
        "returned": len(sliced),
        "filter": "",
        "engine": "native",
    }


def _native_proto_stats(path: str, limit: int = 20) -> list[dict]:
    counts: dict[str, int] = {}
    for p in _native_iter(path, max_packets=MAX_PACKETS_SCAN):
        proto = p.get("proto") or "?"
        counts[proto] = counts.get(proto, 0) + 1
    return [
        {"label": k, "count": v}
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    ][:limit]


def _native_conversations(path: str, limit: int = 30) -> list[dict]:
    pairs: dict[tuple[str, str], dict] = {}
    for p in _native_iter(path, max_packets=MAX_PACKETS_SCAN):
        a, b = p.get("src") or "?", p.get("dst") or "?"
        key = tuple(sorted((a, b)))
        ent = pairs.setdefault(key, {"a": key[0], "b": key[1], "frames": 0, "bytes": 0})
        ent["frames"] += 1
        ent["bytes"] += int(p.get("length") or 0)
    rows = sorted(pairs.values(), key=lambda r: -r["frames"])
    return rows[:limit]


def _native_iter(path: str, max_packets: int = 5000) -> list[dict]:
    """Parse classic libpcap only (not pcapng)."""
    out: list[dict] = []
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return out
        magic = gh[:4]
        if magic == b"\x0a\x0d\x0d\x0a":
            # pcapng — require tshark
            return out
        if magic == b"\xd4\xc3\xb2\xa1":
            endian = "<"
        elif magic == b"\xa1\xb2\xc3\xd4":
            endian = ">"
        elif magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
            endian = "<" if magic[0] == 0x4D else ">"
        else:
            return out
        # linktype at offset 20
        linktype = struct.unpack(endian + "I", gh[20:24])[0]
        t0 = None
        while len(out) < max_packets:
            ph = f.read(16)
            if len(ph) < 16:
                break
            ts_sec, ts_usec, incl_len, _orig = struct.unpack(endian + "IIII", ph)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            t = ts_sec + ts_usec / 1_000_000.0
            if t0 is None:
                t0 = t
            parsed = _parse_frame(data, linktype)
            parsed.update({
                "no": len(out) + 1,
                "time": t - t0,
                "length": incl_len,
                "hex": data[:256].hex(),
            })
            out.append(parsed)
    return out


def _parse_frame(data: bytes, linktype: int) -> dict:
    src = dst = ""
    proto = "ETH"
    info = f"{len(data)} bytes"
    # Ethernet
    if linktype == 1 and len(data) >= 14:
        dst = ":".join(f"{b:02x}" for b in data[0:6])
        src = ":".join(f"{b:02x}" for b in data[6:12])
        ethertype = struct.unpack("!H", data[12:14])[0]
        payload = data[14:]
        if ethertype == 0x0800 and len(payload) >= 20:  # IPv4
            ihl = (payload[0] & 0x0F) * 4
            total = struct.unpack("!H", payload[2:4])[0]
            ip_proto = payload[9]
            src = ".".join(str(b) for b in payload[12:16])
            dst = ".".join(str(b) for b in payload[16:20])
            ip_payload = payload[ihl:total] if total <= len(payload) else payload[ihl:]
            if ip_proto == 6 and len(ip_payload) >= 4:
                sport, dport = struct.unpack("!HH", ip_payload[0:4])
                proto = "TCP"
                info = f"{sport} → {dport} [{len(ip_payload)} B]"
            elif ip_proto == 17 and len(ip_payload) >= 4:
                sport, dport = struct.unpack("!HH", ip_payload[0:4])
                proto = "UDP"
                info = f"{sport} → {dport} [{len(ip_payload)} B]"
            elif ip_proto == 1:
                proto = "ICMP"
                info = "ICMP"
            else:
                proto = f"IP/{ip_proto}"
                info = f"proto {ip_proto}"
        elif ethertype == 0x0806:
            proto = "ARP"
            info = "ARP"
        elif ethertype == 0x86DD:
            proto = "IPv6"
            info = "IPv6"
    return {"src": src, "dst": dst, "proto": proto, "info": info}


def write_sample_pcap(path: str | Path) -> Path:
    """Tiny classic PCAP for tests (2 UDP frames)."""
    path = Path(path)
    # Global header LE
    gh = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)

    def eth_ip_udp(src_ip, dst_ip, sport, dport, payload: bytes) -> bytes:
        eth = bytes.fromhex("ffffffffffff0011223344550800")
        # IPv4
        ver_ihl = 0x45
        total = 20 + 8 + len(payload)
        ip = bytearray(20)
        ip[0] = ver_ihl
        struct.pack_into("!H", ip, 2, total)
        ip[8] = 64
        ip[9] = 17
        ip[12:16] = bytes(int(x) for x in src_ip.split("."))
        ip[16:20] = bytes(int(x) for x in dst_ip.split("."))
        # checksum skip (0 ok for many tools)
        udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
        return bytes(eth) + bytes(ip) + udp

    frames = [
        eth_ip_udp("10.0.0.1", "10.0.0.2", 12345, 53, b"dns"),
        eth_ip_udp("10.0.0.2", "10.0.0.1", 53, 12345, b"ok"),
    ]
    blob = bytearray(gh)
    for i, fr in enumerate(frames):
        blob += struct.pack("<IIII", 1000 + i, 0, len(fr), len(fr))
        blob += fr
    path.write_bytes(blob)
    return path
