#!/usr/bin/env python3

import os
from bs4 import BeautifulSoup
import click

def remove_width_height(svg_content):
    soup = BeautifulSoup(svg_content, 'xml')
    svg_tag = soup.find('svg')
    if svg_tag:
        if 'width' in svg_tag.attrs:
            del svg_tag.attrs['width']
        if 'height' in svg_tag.attrs:
            del svg_tag.attrs['height']
    return str(soup)

def process_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    new_content = remove_width_height(content)
    
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(new_content)

def process_directory(directory_path):
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.lower().endswith('.svg'):
                process_file(os.path.join(root, file))

@click.command()
@click.argument('path', type=click.Path(exists=True, readable=True, path_type=str))
def main(path):
    """
    Process SVG files to remove width and height attributes.
    PATH can be a file or directory.
    """
    if os.path.isfile(path) and path.lower().endswith('.svg'):
        process_file(path)
    elif os.path.isdir(path):
        process_directory(path)
    else:
        click.echo(f"Invalid path: {path}")

if __name__ == "__main__":
    main()