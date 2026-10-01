"""User-friendly error messages + short fix suggestions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class UserError:
    title: str
    message: str
    suggestion: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "error": self.message,
            "title": self.title,
            "suggestion": self.suggestion,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        parts = [self.message]
        if self.suggestion:
            parts.append(f"Try: {self.suggestion}")
        if self.detail:
            parts.append(f"({self.detail})")
        return " — ".join(parts)


def explain_exception(exc: BaseException, context: str = "") -> UserError:
    """Map a technical exception to a calm, actionable message."""
    msg = str(exc).strip() or type(exc).__name__
    low = msg.lower()
    ctx = (context or "").lower()

    def ue(title, message, suggestion, detail="") -> UserError:
        return UserError(title, message, suggestion, detail or msg)

    if "pyscca" in low or "libscca" in low:
        return ue(
            "Prefetch library missing",
            "Prefetch parsing needs pyscca (libscca).",
            "Install: sudo apt install python3-libscca",
        )
    if "pyregf" in low or "libregf" in low or "pyfwsi" in low:
        return ue(
            "Registry library missing",
            "ShellBags / hive tools need libregf (+ libfwsi).",
            "Install: sudo apt install python3-libregf python3-libfwsi",
        )
    if "impacket" in low:
        return ue(
            "impacket missing",
            "SAM NTLM dump needs the impacket Python package.",
            "Install: pip install -r requirements.txt",
        )
    if "hashcat" in low or "john the ripper" in low or ("john" in low and "not" in low):
        return ue(
            "Password cracker missing",
            "Auto-crack needs john (preferred) or hashcat.",
            "Install: sudo apt install john hashcat",
        )
    if "exiftool" in low:
        return ue(
            "exiftool missing",
            "Image EXIF preview needs exiftool.",
            "Install: sudo apt install libimage-exiftool-perl",
        )
    if "tshark" in low:
        return ue(
            "tshark missing",
            "Full PCAP analysis needs Wireshark's tshark.",
            "Install: sudo apt install tshark",
        )
    if "xmount not found" in low or ("xmount" in low and "path" in low):
        return ue(
            "xmount missing",
            "Disk / OVA analysis needs the xmount tool, which is not installed.",
            "Install it: sudo apt install xmount",
        )
    if "qemu-img" in low:
        return ue(
            "qemu-img missing",
            "This image needs conversion (VMDK/VHD/OVA disk) but qemu-img was not found.",
            "Install it: sudo apt install qemu-utils",
        )
    if "mmls" in low or "sleuthkit" in low or "fls" in low or "icat" in low:
        return ue(
            "Sleuth Kit missing",
            "Partition / filesystem browse needs Sleuth Kit tools.",
            "Install them: sudo apt install sleuthkit",
        )
    if "fusermount" in low or "fuse" in low or "operation not permitted" in low:
        return ue(
            "FUSE mount problem",
            "Could not create or remove a FUSE mount (permission or busy mount).",
            "Check /etc/fuse.conf has user_allow_other uncommented, or: fusermount -uz <mount-dir>",
        )
    if "not a valid ova" in low or ("ova" in low and "tar" in low):
        return ue(
            "Invalid OVA",
            "The file looks like .ova but is not a readable virtual appliance archive.",
            "Confirm the file opens with tar tf file.ova, or re-export the OVA from the hypervisor.",
        )
    if "no virtual disk found inside ova" in low:
        return ue(
            "OVA has no disk",
            "The OVA was extracted but no VMDK/VDI/qcow disk was found inside.",
            "Open the OVA and check it contains a .vmdk (or .vdi/.qcow2) disk file.",
        )
    if "qemu-img convert failed" in low:
        return ue(
            "Disk convert failed",
            "qemu-img could not convert the virtual disk to raw for analysis.",
            "Try: qemu-img info <disk.vmdk> — if corrupt, re-export from the VM host.",
        )
    if "unsupported evidence format" in low:
        return ue(
            "Unsupported file type",
            "This file type is not on the accepted formats list.",
            "Use Formats tab, or convert to .E01 / .dd / .ad1 / .ova. Check tforensic formats.",
        )
    if "not an ad1" in low or "adsegmentedfile" in low:
        return ue(
            "Not an AD1 image",
            "This file is not a valid AccessData AD1 logical image.",
            "If it is a disk image, open it as E01/raw/OVA instead (File → Open image…).",
        )
    if "no active xmount" in low or "mount not found" in low:
        return ue(
            "No active mount",
            "There is no mounted disk session to work with.",
            "Open a disk/OVA image first, or use Disk tab → Mount.",
        )
    if "primary disk mount" in low:
        return ue(
            "Cannot unmount yet",
            "This mount belongs to the open case.",
            "Close the case / quit the app to unmount safely.",
        )
    if "not found" in low and ("image" in low or "file" in low or context == "open"):
        return ue(
            "File not found",
            "The image path does not exist or is not readable.",
            "Check the path, permissions, and that the drive is mounted.",
        )
    if "timed out" in low or "timeout" in low:
        return ue(
            "Taking too long",
            "The operation timed out (large image, slow disk, or stuck mount).",
            "Wait and retry; for huge OVAs ensure enough free disk in /tmp.",
        )
    if "permission" in low or "permissionerror" in low:
        return ue(
            "Permission denied",
            "Cannot read the image or write the session temp folder.",
            "Check file permissions, or free space under /tmp/tforensic-sessions.",
        )
    if "xmount exited" in low or "no virtual device" in low:
        return ue(
            "Mount failed",
            "xmount started but did not expose a virtual disk.",
            "Confirm the image type (--in ewf/raw/vdi), or run: xmount --in raw file.dd /tmp/testmnt",
        )
    if ctx == "mount" or "mount" in low:
        return ue(
            "Mount error",
            "Could not mount the disk image.",
            "Confirm xmount is installed and the image type is correct. See Formats tab.",
            msg,
        )
    if ctx == "open" or ctx == "serve":
        short = msg if len(msg) < 220 else msg[:217] + "…"
        return ue(
            "Could not open evidence",
            short or "Opening the image failed.",
            "Check Formats tab. Disk/OVA need: sudo apt install xmount sleuthkit qemu-utils. "
            "Then: tforensic deps",
            msg,
        )
    return ue(
        "Something went wrong",
        msg if len(msg) < 180 else msg[:177] + "…",
        "Retry the action. If it continues, copy the detail below and check logs.",
        msg,
    )


def format_cli_error(exc: BaseException, context: str = "") -> str:
    err = explain_exception(exc, context)
    lines = [f"error: {err.message}"]
    if err.suggestion:
        lines.append(f"hint:  {err.suggestion}")
    if err.detail and err.detail != err.message:
        lines.append(f"detail:{err.detail}")
    return "\n".join(lines)
