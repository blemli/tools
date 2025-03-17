#!/usr/bin/env python

import os
import re
import click
from yt_dlp import YoutubeDL

def slugify(value):
    """Convert a string to a slugified version (lowercase, hyphen-separated)."""
    value = str(value).lower()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    return value.strip('-')

@click.command()
@click.argument('url')
@click.option('--destination', '-d', default='.', show_default=True,
              help="Destination directory (default: current directory)")
@click.option('--filename', '-f', default=None,
              help="Optional output filename (without extension). If not provided, uses a slugified version of the video title.")
def main(url, destination, filename):
    """
    Download audio from a YouTube video using yt_dlp and convert it to mp3.

    URL: The URL of the video to download.
    """
    # If filename is not provided, extract video info and slugify the title.
    if not filename:
        click.echo("No filename provided. Extracting video info to generate filename...")
        with YoutubeDL({}) as ydl:
            info = ydl.extract_info(url, download=False)
            video_title = info.get("title", "video")
            filename = slugify(video_title)
        click.echo(f"Using filename: {filename}")

    # Set the output template.
    outtmpl = os.path.join(destination, f'{filename}.%(ext)s')

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }],
    }

    click.echo("Downloading and converting video...")
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    click.echo("Download complete!")

if __name__ == "__main__":
    main()