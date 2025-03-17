#!/usr/bin/env python3

import os
import time
import shutil
import click
from pathlib import Path

@click.command(name="purgedl")
@click.option('--days', '-d', default=7, type=int,
              help="Delete files and folders older than the specified number of days (default is 7).")
@click.option('--force', '-f', is_flag=True,
              help="Force deletion without confirmation prompt.")
def purgedl(days, force):
    """
    Clean up the Downloads folder by removing files and folders that are older than a specified number of days.
    """
    home = Path.home()
    download_folder = os.path.join(home, 'Downloads')
    now = time.time()
    age_in_seconds = days * 24 * 60 * 60

    click.echo(f"Preparing to clean up files older than {days} day(s) from {download_folder}...")

    if not force:
        if not click.confirm(f"Delete everything in {download_folder} older than {days} days?"):
            click.echo("Operation aborted by user.")
            return

    for filename in os.listdir(download_folder):
        file_path = os.path.join(download_folder, filename)
        try:
            file_mtime = os.path.getmtime(file_path)
            if (now - file_mtime) > age_in_seconds:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.remove(file_path)
                    click.echo(f"Deleted file: {file_path}")
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    click.echo(f"Deleted folder: {file_path}")
        except Exception as e:
            click.echo(f"Error processing {file_path}: {e}")

if __name__ == "__main__":
    purgedl()