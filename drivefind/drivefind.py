#!/usr/bin/env python3

import json
import os
import platform
import plistlib
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import click


@dataclass
class DriveInfo:
    mount_point: str
    device: str = ""
    label: str = ""
    size: int = 0
    fstype: str = ""


# --- Platform-specific drive listing (fast, for polling) ---


def get_drives_macos():
    """List mounted volumes via /Volumes/ (fast, no subprocess)."""
    drives = {}
    volumes = Path("/Volumes")
    if volumes.exists():
        for entry in volumes.iterdir():
            drives[str(entry)] = DriveInfo(mount_point=str(entry))
    return drives


def get_drives_linux():
    """List mounted drives via lsblk."""
    drives = {}
    try:
        result = subprocess.run(
            ["lsblk", "--json", "-b", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL,TYPE"],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return drives

    def walk(devices):
        for dev in devices:
            mp = dev.get("mountpoint")
            if mp and dev.get("type") == "part":
                drives[mp] = DriveInfo(
                    mount_point=mp,
                    device=f"/dev/{dev['name']}",
                    label=dev.get("label") or "",
                    size=dev.get("size") or 0,
                    fstype=dev.get("fstype") or "",
                )
            for child in dev.get("children", []):
                walk([child])

    walk(data.get("blockdevices", []))
    return drives


def get_drives_windows():
    """List drives via PowerShell Get-Volume."""
    drives = {}
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Volume | Where-Object { $_.DriveLetter } | "
             "Select-Object DriveLetter, Size, FileSystemType, FileSystemLabel, DriveType | "
             "ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return drives

    if isinstance(data, dict):
        data = [data]
    for vol in data:
        letter = vol.get("DriveLetter")
        if not letter:
            continue
        mp = f"{letter}:\\"
        drives[mp] = DriveInfo(
            mount_point=mp,
            device=mp,
            label=vol.get("FileSystemLabel") or "",
            size=vol.get("Size") or 0,
            fstype=vol.get("FileSystemType") or "",
        )
    return drives


def get_drives():
    system = platform.system()
    if system == "Darwin":
        return get_drives_macos()
    elif system == "Linux":
        return get_drives_linux()
    elif system == "Windows":
        return get_drives_windows()
    else:
        click.echo(f"Unsupported platform: {system}", err=True)
        sys.exit(1)


# --- Detail fetchers (called once after detection) ---


def get_drive_details_macos(mount_point):
    """Fetch detailed info for a macOS volume via diskutil."""
    try:
        result = subprocess.run(
            ["diskutil", "info", "-plist", mount_point],
            capture_output=True, timeout=5,
        )
        info = plistlib.loads(result.stdout)
        return DriveInfo(
            mount_point=info.get("MountPoint", mount_point),
            device=info.get("DeviceNode", ""),
            label=info.get("VolumeName", ""),
            size=info.get("TotalSize", 0),
            fstype=info.get("FilesystemType", ""),
        )
    except (subprocess.SubprocessError, plistlib.InvalidFileException):
        return DriveInfo(mount_point=mount_point)


def get_drive_details(mount_point):
    system = platform.system()
    if system == "Darwin":
        return get_drive_details_macos(mount_point)
    elif system == "Linux":
        # lsblk already provides full info during polling
        drives = get_drives_linux()
        return drives.get(mount_point, DriveInfo(mount_point=mount_point))
    elif system == "Windows":
        drives = get_drives_windows()
        return drives.get(mount_point, DriveInfo(mount_point=mount_point))
    return DriveInfo(mount_point=mount_point)


# --- Helpers ---


def format_size(size_bytes):
    if size_bytes <= 0:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def whole_disk(device):
    """Strip the partition suffix so 'device' points at the whole disk.

    macOS:   /dev/disk12s1     -> /dev/disk12   (also /dev/disk3s1s1 -> /dev/disk3)
    Linux:   /dev/sda1         -> /dev/sda
             /dev/nvme0n1p1    -> /dev/nvme0n1
             /dev/mmcblk0p1    -> /dev/mmcblk0
    """
    if not device:
        return device
    system = platform.system()
    if system == "Darwin":
        m = re.match(r"(/dev/disk\d+)", device)
        return m.group(1) if m else device
    if system == "Linux":
        if re.search(r"\d+p\d+$", device):   # nvme / mmc style
            return re.sub(r"p\d+$", "", device)
        return re.sub(r"\d+$", "", device)   # sd style
    return device  # Windows: no partition suffix to strip


def open_drive(mount_point):
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", mount_point])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", mount_point])
    elif system == "Windows":
        os.startfile(mount_point)


# --- Polling ---


def wait_for_drive(timeout):
    """Poll until a new drive appears. Returns (primary DriveInfo, list of all new)."""
    old = get_drives()
    click.echo("Please plug in the drive...", err=True)

    start = time.monotonic()
    try:
        while True:
            time.sleep(0.5)
            new = get_drives()
            diff = set(new.keys()) - set(old.keys())
            if diff:
                mount_point = sorted(diff)[0]
                if len(diff) > 1:
                    click.echo(
                        f"Warning: {len(diff)} new drives detected, using {mount_point}",
                        err=True,
                    )
                # stabilization pause
                time.sleep(0.3)
                detail = get_drive_details(mount_point)
                all_new = [get_drive_details(mp) for mp in sorted(diff)]
                return detail, all_new

            if timeout is not None and (time.monotonic() - start) > timeout:
                click.echo(
                    f"Error: Timed out after {timeout} seconds waiting for a new drive.",
                    err=True,
                )
                sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


# --- CLI ---


@click.command(name="drivefind")
@click.option("--verbose", "-v", is_flag=True, help="Show full drive details.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option("--dev", "dev", is_flag=True, help="Print the device path (e.g. /dev/disk2s1) instead of the mount point.")
@click.option("--open", "open_drive_flag", is_flag=True, help="Open in file manager.")
@click.option("--timeout", "-t", type=int, default=None, help="Timeout in seconds.")
def drivefind(verbose, json_output, dev, open_drive_flag, timeout):
    """Detect a newly plugged-in drive and print its mount point."""
    drive, all_new = wait_for_drive(timeout)

    if json_output:
        click.echo(json.dumps(asdict(drive), indent=2))
    elif verbose:
        click.echo(f"Mount point: {drive.mount_point}")
        click.echo(f"Device:      {drive.device}")
        click.echo(f"Label:       {drive.label}")
        click.echo(f"Size:        {format_size(drive.size)}")
        click.echo(f"Filesystem:  {drive.fstype}")
    elif dev:
        if not drive.device:
            click.echo("Error: no device path available for this drive.", err=True)
            sys.exit(1)
        click.echo(whole_disk(drive.device))
    else:
        click.echo(drive.mount_point)

    if open_drive_flag:
        open_drive(drive.mount_point)


if __name__ == "__main__":
    drivefind()
