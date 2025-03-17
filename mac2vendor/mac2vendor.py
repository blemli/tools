#!/usr/bin/env python3
import os
import time
import urllib.request
import gzip
import click

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MANUF_URL = "https://www.wireshark.org/download/automated/data/manuf.gz"
MANUF_FILE = os.path.join(SCRIPT_DIR, "manuf.gz")
MAX_AGE_DAYS = 30

def download_file(url, filename):
    click.echo("Downloading updated manuf file...")
    urllib.request.urlretrieve(url, filename)

def is_file_old(filename, days=30):
    if not os.path.exists(filename):
        return True
    file_age = time.time() - os.path.getmtime(filename)
    return file_age > days * 24 * 3600

def normalize(s):
    return ''.join(c for c in s if c.isalnum()).upper()

def lookup_vendor(normalized_mac):
    best_vendor = None
    best_prefix_len = 0
    with gzip.open(MANUF_FILE, "rt", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split(maxsplit=2)
            if len(parts) < 2:
                continue
            file_prefix = normalize(parts[0])
            vendor = parts[2] if len(parts) > 2 else parts[1]
            if normalized_mac.startswith(file_prefix) and len(file_prefix) > best_prefix_len:
                best_vendor = vendor
                best_prefix_len = len(file_prefix)
    return best_vendor

@click.command()
@click.argument('mac')
def main(mac):
    """Return vendor for given MAC address or prefix."""
    input_mac = normalize(mac)
    if is_file_old(MANUF_FILE, MAX_AGE_DAYS):
        download_file(MANUF_URL, MANUF_FILE)
    vendor = lookup_vendor(input_mac)
    click.echo(vendor if vendor else "Unknown vendor")

if __name__ == "__main__":
    main()