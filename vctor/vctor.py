#!/usr/bin/env python

import click,subprocess,tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def process_file(file, output, threshold, gigicon, force):
    """Process a single file. Returns output path on success, None on failure."""
    path = Path(file)
    if path.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
        return None, f"Skipping {file}: not a JPG/JPEG/PNG"

    out_path = Path(output) / (path.stem + '.svg') if output else path.with_suffix('.svg')

    if out_path.exists() and not force:
        return None, f"Skipping {file}: {out_path} exists (use --force)"

    with tempfile.NamedTemporaryFile(suffix='.pbm', delete=True) as tmp:
        magick_cmd = ['magick', str(path)]
        if gigicon:
            magick_cmd += ['-shave', '4.5%', '-bordercolor', 'white', '-border', '4.5%',
                           '-gravity', 'SouthWest', '-region', '16%x9%', '-fill', 'white', '-colorize', '100%', '+region',
                           '-gravity', 'SouthEast', '-region', '16%x9%', '-fill', 'white', '-colorize', '100%', '+region',
                           '-gravity', 'NorthWest']
        magick_cmd += ['-colorspace', 'Gray', '-threshold', f'{threshold}%', '-type', 'bilevel', tmp.name]

        try:
            subprocess.run(magick_cmd, check=True, capture_output=True)
            subprocess.run(['potrace', '-s', '-o', str(out_path), tmp.name], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            return None, f"Error processing {file}: {e.stderr.decode()}"

    return out_path, f"Created {out_path}"


@click.command()
@click.argument('files', nargs=-1)
@click.option('--output', '-o', type=click.Path(), help='Output directory (default: same as input)')
@click.option('--threshold', '-t', default=55, help='Grayscale threshold % (default: 55)')
@click.option('--gigicon', is_flag=True, help='Add 4.5% white border mask')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing SVGs')
@click.option('--preview', '-p', is_flag=True, help='Preview result with ql (single file only)')
def vctor(files, output, threshold, gigicon, force, preview):
    """Convert JPG/JPEG/PNG images to SVG using potrace."""
    with ThreadPoolExecutor() as pool:
        results = pool.map(lambda f: process_file(f, output, threshold, gigicon, force), files)
    processed = []
    for out_path, msg in results:
        click.echo(msg)
        if out_path:
            processed.append(out_path)
    if preview and len(processed) == 1:
        subprocess.run(['ql', str(processed[0])])

if __name__ == "__main__":
    vctor()
