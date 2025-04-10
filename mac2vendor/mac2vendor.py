#!/usr/bin/env python3
import os, sys, time, urllib.request, gzip, click
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ========== CONFIGURATION ==========
MANUF_DIR = SCRIPT_DIR  # adjust as needed
MAX_AGE_DAYS = 30
MANUF_URL = "https://www.wireshark.org/download/automated/data/manuf.gz"
# ====================================

MANUF_FILE = os.path.join(MANUF_DIR, "manuf")
QUIET = False

def echo(msg):
    if not QUIET:
        click.echo(msg)

def download_file(url, filename):
    gz_filename = filename + ".gz"
    echo(f"Downloading manuf file from {url} ...")
    echo(f"Saving as {gz_filename} ...")
    with tqdm(unit='B', unit_scale=True, unit_divisor=1024, miniters=1,
              desc=gz_filename, disable=QUIET) as bar:
        def reporthook(block_num, block_size, total_size):
            if total_size > 0:
                bar.total = total_size
            bar.update(block_size)
        urllib.request.urlretrieve(url, gz_filename, reporthook)
    echo("Decompressing file ...")
    with gzip.open(gz_filename, "rb") as f_in:
        with open(filename, "wb") as f_out:
            f_out.write(f_in.read())
    os.remove(gz_filename)

def is_file_old(filename, days=MAX_AGE_DAYS):
    if not os.path.exists(filename):
        return True
    file_age = time.time() - os.path.getmtime(filename)
    return file_age > days * 24 * 3600

def normalize(s):
    return ''.join(c for c in s if c.isalnum()).upper()

def get_vendors():
    """
    Parse the manuf file and return a dictionary.
    Key: normalized prefix.
    Value: tuple(prefix_length, vendor)
    """
    vendors = {}
    with open(MANUF_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split(maxsplit=2)
            if len(parts) < 2:
                continue
            prefix_field = parts[0]
            vendor = parts[2] if len(parts) > 2 else parts[1]
            if "/" in prefix_field:
                hex_part, bits_str = prefix_field.split("/")
                try:
                    prefix_bits = int(bits_str)
                except ValueError:
                    continue
                normalized_prefix = normalize(hex_part)
                hex_digits = prefix_bits // 4
                key = normalized_prefix[:hex_digits]
                vendors[key] = (hex_digits, vendor)
            else:
                normalized_prefix = normalize(prefix_field)
                prefix_length = len(normalized_prefix)
                key = normalized_prefix
                vendors[key] = (prefix_length, vendor)
    return vendors

def lookup_vendor(normalized_mac, vendors):
    best_vendor = None
    best_prefix_len = 0
    for prefix, (length, vendor) in vendors.items():
        if normalized_mac.startswith(prefix) and length > best_prefix_len:
            best_vendor = vendor
            best_prefix_len = length
    return best_vendor

def show_info():
    if os.path.exists(MANUF_FILE):
        age_seconds = time.time() - os.path.getmtime(MANUF_FILE)
        age_days = age_seconds / (24 * 3600)
        echo(f"Manuf file: {MANUF_FILE}\nAge: {age_days:.2f} days")
        unique_vendors = set(get_vendors().values())
        echo(f"Unique vendors: {len(unique_vendors)}")
    else:
        echo(f"Manuf file: {MANUF_FILE} does not exist. Run the script with a MAC address to download it.")

@click.command()
@click.argument('mac')
@click.option('--update', is_flag=True, default=False,
              help=f"Manually update manuf file if older than {MAX_AGE_DAYS} days")
@click.option('--no-update', is_flag=True, default=False,
              help="Do not update the manuf file before lookup")
@click.option('--info', is_flag=True, default=False,
              help="Show the path and age of the manuf file")
@click.option('--quiet', is_flag=True, default=False,
              help="Output only the vendor name")
def mac2vendor(mac, update=False, no_update=False, info=False, quiet=False):
    global QUIET
    QUIET = quiet
    normalized_mac = normalize(mac)
    if update or is_file_old(MANUF_FILE, MAX_AGE_DAYS):
        download_file(MANUF_URL, MANUF_FILE)
    vendors = get_vendors()
    vendor = lookup_vendor(normalized_mac, vendors)
    print(vendor if vendor else "Unknown vendor")
    return vendor

if __name__ == "__main__":
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            sys.argv.append(piped)
    if '--info' in sys.argv:
        show_info()
        exit(0)
    mac2vendor()