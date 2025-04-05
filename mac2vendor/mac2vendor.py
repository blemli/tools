#!/usr/bin/env python3
import os,sys,time
import urllib.request,gzip,click
from tqdm import tqdm


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ========== CONFIGURATION ==========
MANUF_DIR=SCRIPT_DIR #you can adjust this to your needs
MAX_AGE_DAYS = 30
MANUF_URL = "https://www.wireshark.org/download/automated/data/manuf.gz"
# ====================================

MANUF_FILE = os.path.join(MANUF_DIR, "manuf.gz")
QUIET = False

def echo(msg):
    if not QUIET:
        click.echo(msg)
        
        
def download_file(url, filename):
    echo(f"Downloading updated manuf file from {url} ...")
    echo(f"Saving to {filename} ...")
    with tqdm(unit='B', unit_scale=True, unit_divisor=1024, miniters=1, desc=filename, disable=QUIET) as bar:
        def reporthook(block_num, block_size, total_size):
            if total_size > 0:
                bar.total = total_size
            bar.update(block_size)
        urllib.request.urlretrieve(url, filename, reporthook)


def is_file_old(filename, days=MAX_AGE_DAYS):
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
            prefix_field = parts[0]
            vendor = parts[2] if len(parts) > 2 else parts[1]
            if "/" in prefix_field:
                hex_part, bits_str = prefix_field.split("/")
                try:
                    prefix_bits = int(bits_str)
                except ValueError:
                    continue
                normalized_prefix = normalize(hex_part)
                # each hex digit represents 4 bits
                hex_digits = prefix_bits // 4
                if normalized_mac[:hex_digits] == normalized_prefix[:hex_digits]:
                    if hex_digits > best_prefix_len:
                        best_vendor = vendor
                        best_prefix_len = hex_digits
            else:
                normalized_prefix = normalize(prefix_field)
                prefix_length = len(normalized_prefix)
                if normalized_mac.startswith(normalized_prefix) and prefix_length > best_prefix_len:
                    best_vendor = vendor
                    best_prefix_len = prefix_length
    return best_vendor


def show_info():
    if os.path.exists(MANUF_FILE):
        age_seconds = time.time() - os.path.getmtime(MANUF_FILE)
        age_days = age_seconds / (24 * 3600)
        echo(f"Manuf file: {MANUF_FILE}\nAge: {age_days:.2f} days")
        vendors = set()
        with gzip.open(MANUF_FILE, "rt", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split(maxsplit=2)
                if len(parts) < 2:
                    continue
                vendor = parts[2] if len(parts) > 2 else parts[1]
                vendors.add(vendor)
        echo(f"Unique vendors: {len(vendors)}")
    else:
        echo(f"Manuf file: {MANUF_FILE} does not exist. Run the script once with a mac address to download it.")
    


@click.command()
@click.argument('mac')
@click.option('--update', is_flag=True, default=False, help=f'Update the manuf file manually before lookup. Default: Automatically If older than {MAX_AGE_DAYS} days')
@click.option('--no-update', is_flag=True, default=False, help='Do not update the manuf file before lookup')
@click.option('--info', is_flag=True, default=False, help='Show the path and the age of the manuf file')
@click.option('--quiet', is_flag=True, default=False, help='Don\'t output anything except the vendor name')
def mac2vendor(mac,update=False,no_update=False,info=False,quiet=False):
    """Return vendor for given MAC address or prefix."""
    global QUIET
    QUIET = quiet
    normalized_mac = normalize(mac)
    if update or is_file_old(MANUF_FILE, MAX_AGE_DAYS):
        download_file(MANUF_URL, MANUF_FILE)
    vendor=lookup_vendor(normalized_mac)
    print(vendor) if vendor else print("Unknown vendor")
    return vendor

if __name__ == "__main__":
     # Append piped input to sys.argv if not running interactively
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            sys.argv.append(piped)
    if '--info' in sys.argv:
        show_info()
        exit(0)
    mac2vendor()