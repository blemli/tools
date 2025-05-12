#!/usr/bin/env python3

import click
import base64
import glob
import logging
import os
import re
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger('vcf2img')
logger.setLevel(logging.WARNING)  # Default to warnings only

def extract_image_from_vcf(vcf_path):
    """Extract image data from a VCF file."""
    try:
        with open(vcf_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for PHOTO field
        photo_match = re.search(r'PHOTO;[^:]*:(.+?)(?:\r?\n[^ ]|\r?\n$|$)', content, re.DOTALL)
        if not photo_match:
            logger.error(f"No PHOTO field found in {vcf_path}")
            return None, None
        
        # Extract base64 data
        photo_data = photo_match.group(1).strip()
        
        # Determine image type (default to JPEG if not specified)
        type_match = re.search(r'PHOTO;[^:]*TYPE=([^:;]+)', content)
        img_type = type_match.group(1).lower() if type_match else 'jpeg'
        
        # Map common image types to file extensions
        extension_map = {
            'jpeg': 'jpg',
            'jpg': 'jpg',
            'png': 'png',
            'gif': 'gif'
        }
        extension = extension_map.get(img_type, 'jpg')
        
        # Decode base64 data
        try:
            image_data = base64.b64decode(photo_data)
            return image_data, extension
        except Exception as e:
            logger.error(f"Failed to decode image data: {e}")
            return None, None
            
    except Exception as e:
        logger.error(f"Error processing {vcf_path}: {e}")
        return None, None

def get_vcf_name(vcf_path):
    """Extract name from VCF file for use in output filename."""
    try:
        with open(vcf_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for FN (Full Name) field
        name_match = re.search(r'FN:(.+?)(?:\r?\n)', content)
        if name_match:
            # Clean the name to make it suitable for a filename
            name = name_match.group(1).strip()
            name = re.sub(r'[\\/*?:"<>|]', '_', name)  # Replace invalid filename chars
            return name
        
        # Fallback to base filename without extension
        return os.path.splitext(os.path.basename(vcf_path))[0]
    except Exception:
        # If anything goes wrong, use the base filename
        return os.path.splitext(os.path.basename(vcf_path))[0]

def save_image(image_data, output_path, force=False):
    """Save image data to file."""
    if os.path.exists(output_path) and not force:
        logger.error(f"Output file {output_path} already exists. Use --force to overwrite.")
        return False
    
    try:
        with open(output_path, 'wb') as f:
            f.write(image_data)
        logger.info(f"Image saved to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save image to {output_path}: {e}")
        return False

@click.command()
@click.argument('input_pattern', required=True)
@click.argument('output', required=False)
@click.option('--verbose', is_flag=True, help='Enable verbose logging')
@click.option('--force', is_flag=True, help='Overwrite existing files')
def main(input_pattern, output, verbose, force):
    """Extract images from VCF files."""
    # Configure logging based on verbose flag
    if verbose:
        logger.setLevel(logging.INFO)
    
    # Get list of input files using glob
    input_files = glob.glob(input_pattern)
    
    if not input_files:
        logger.error(f"No files found matching pattern: {input_pattern}")
        sys.exit(1)
    
    logger.info(f"Found {len(input_files)} file(s) matching pattern")
    
    # Process single file with specific output
    if len(input_files) == 1 and output:
        vcf_path = input_files[0]
        image_data, extension = extract_image_from_vcf(vcf_path)
        
        if image_data:
            # If output doesn't have an extension, add the detected one
            if not os.path.splitext(output)[1]:
                output = f"{output}.{extension}"
            
            if save_image(image_data, output, force):
                logger.info(f"Successfully extracted image from {vcf_path}")
            else:
                sys.exit(1)
    
    # Process multiple files or single file without specific output
    else:
        success_count = 0
        for vcf_path in input_files:
            image_data, extension = extract_image_from_vcf(vcf_path)
            
            if image_data:
                # Generate output filename if not specified
                if not output:
                    name = get_vcf_name(vcf_path)
                    out_path = f"{name}.{extension}"
                else:
                    # For multiple files with output specified, use it as directory
                    if os.path.isdir(output):
                        name = get_vcf_name(vcf_path)
                        out_path = os.path.join(output, f"{name}.{extension}")
                    else:
                        # Add index for multiple files
                        base, ext = os.path.splitext(output)
                        if not ext:
                            ext = f".{extension}"
                        if len(input_files) > 1:
                            out_path = f"{base}_{success_count}{ext}"
                        else:
                            out_path = f"{base}{ext}"
                
                if save_image(image_data, out_path, force):
                    success_count += 1
                    logger.info(f"Successfully extracted image from {vcf_path}")
        
        logger.info(f"Processed {len(input_files)} files, extracted {success_count} images")

if __name__ == '__main__':
    main()
