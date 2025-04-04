#!/usr/bin/env python

import csv
import json
import sys
import click
import io
import re
from collections import Counter


def detect_delimiter(sample_data, possible_delimiters=',;|\t'):
    """
    Auto-detect the delimiter used in a CSV file.
    
    Args:
        sample_data: A sample of the CSV data as a string
        possible_delimiters: String of possible delimiter characters to check
        
    Returns:
        The most likely delimiter character
    """
    if not sample_data:
        return ','
    
    # Read a few lines to analyze
    lines = sample_data.split('\n')
    if not lines:
        return ','
    
    # Keep only non-empty lines
    lines = [line for line in lines if line.strip()]
    if not lines:
        return ','
    
    # Count occurrences of each delimiter in each line
    scores = {}
    for delimiter in possible_delimiters:
        scores[delimiter] = 0
        # Check consistency of field count
        field_counts = Counter()
        
        for line in lines[:10]:  # Check first 10 lines at most
            # Skip lines that might be inside quoted fields
            if line.count('"') % 2 != 0:
                continue
                
            count = line.count(delimiter)
            field_counts[count] += 1
            # Higher score for delimiters that appear more frequently
            scores[delimiter] += count
    
        # If the delimiter creates consistent field counts, that's a good sign
        # We weight our score by the frequency of the most common field count
        most_common = field_counts.most_common(1)
        if most_common:
            count, frequency = most_common[0]
            # Bonus points for consistency and non-zero counts
            if count > 0:
                scores[delimiter] *= (frequency / len(lines[:10])) * 2
    
    # Default to comma if we couldn't determine or if all scores are 0
    if not scores or all(score == 0 for score in scores.values()):
        return ','
        
    # Return the delimiter with the highest score
    return max(scores, key=scores.get)


def validate_header_count(fp, custom_headers, delimiter, quotechar):
    """
    Validate that the number of custom headers matches the number of columns in the CSV.
    
    Args:
        fp: File pointer to the CSV
        custom_headers: List of custom headers
        delimiter: Delimiter used in the CSV
        quotechar: Quote character used in the CSV
        
    Returns:
        Boolean indicating if validation passed, and the current position in file
    """
    if not custom_headers:
        return True, 0
    
    # Save current position
    start_pos = fp.tell()
    
    # Read the first line to count fields
    sample = fp.readline()
    fp.seek(start_pos)
    
    if not sample:
        return True, start_pos
    
    # Count fields in a robust way
    reader = csv.reader([sample], delimiter=delimiter, quotechar=quotechar)
    try:
        fields = next(reader)
        column_count = len(fields)
        header_count = len(custom_headers)
        
        if column_count != header_count:
            click.echo(f"Warning: Number of custom headers ({header_count}) does not match " +
                      f"number of CSV columns ({column_count})", err=True)
            return False, start_pos
        
        return True, start_pos
    except Exception:
        return True, start_pos  # In case of parsing error, proceed anyway


def detect_type(value):
    """
    Detect and convert value to appropriate data type.
    
    Args:
        value: String value from CSV
        
    Returns:
        Converted value with appropriate type (int, float, bool, None, or original string)
    """
    # Handle empty or null values
    if value is None or value.strip() == '':
        return None
        
    # Handle boolean values
    if value.lower() in ('true', 'yes', 'y', '1'):
        return True
    if value.lower() in ('false', 'no', 'n', '0'):
        return False
        
    # Handle numeric values
    # First, try with standard format (dot as decimal separator)
    if re.match(r'^-?\d+(\.\d+)?$', value):
        try:
            if '.' in value:
                return float(value)
            else:
                return int(value)
        except (ValueError, TypeError):
            pass
            
    # Try with European format (comma as decimal separator)
    if re.match(r'^-?\d+(,\d+)?$', value):
        try:
            # Replace comma with dot and try to convert
            numeric_val = value.replace(',', '.')
            if '.' in numeric_val:
                return float(numeric_val)
            else:
                return int(numeric_val)
        except (ValueError, TypeError):
            pass
            
    # Return original value if no conversion is possible
    return value


def infer_column_types(rows, keys=None):
    """
    Analyze a list of dictionaries to determine the most likely type for each column.
    
    Args:
        rows: List of dictionaries (row data)
        keys: Optional list of keys to analyze (defaults to all keys in first row)
        
    Returns:
        Dictionary mapping column names to their most likely data type
    """
    if not rows:
        return {}
        
    # If no keys specified, use all keys from the first row
    if keys is None and rows and isinstance(rows[0], dict):
        keys = rows[0].keys()
    elif keys is None:
        return {}
        
    # Initialize type counts for each column
    type_counts = {key: {'int': 0, 'float': 0, 'bool': 0, 'null': 0, 'string': 0} for key in keys}
    
    # Count occurrences of each type in each column
    for row in rows:
        if not isinstance(row, dict):
            continue
            
        for key in keys:
            if key not in row:
                continue
                
            value = row[key]
            
            if value is None:
                type_counts[key]['null'] += 1
            elif isinstance(value, bool):
                type_counts[key]['bool'] += 1
            elif isinstance(value, int):
                type_counts[key]['int'] += 1
            elif isinstance(value, float):
                type_counts[key]['float'] += 1
            else:
                type_counts[key]['string'] += 1
    
    # Determine the most common non-null type for each column
    column_types = {}
    for key in keys:
        counts = type_counts[key]
        # Remove null from consideration
        null_count = counts.pop('null', 0)
        
        if counts and sum(counts.values()) > 0:
            # Find the most common type
            most_common_type = max(counts.items(), key=lambda x: x[1])[0]
            
            # Special case: if all values are numeric, prefer the more precise type
            if most_common_type in ('int', 'float') and counts['int'] + counts['float'] == sum(counts.values()):
                if counts['float'] > 0:
                    most_common_type = 'float'
            
            column_types[key] = most_common_type
        else:
            # All values are null, default to string
            column_types[key] = 'string'
    
    return column_types


def convert_data_types(rows, type_hints=None):
    """
    Convert data types in a list of dictionaries based on detected types.
    
    Args:
        rows: List of dictionaries (row data)
        type_hints: Optional dictionary mapping column names to explicit types
        
    Returns:
        Updated list of dictionaries with converted data types
    """
    if not rows:
        return rows
        
    # First pass: detect types for all values
    for row in rows:
        if not isinstance(row, dict):
            continue
            
        for key, value in row.items():
            if isinstance(value, str):
                row[key] = detect_type(value)
    
    # Second pass: infer and normalize column types
    if type_hints is None:
        column_types = infer_column_types(rows)
    else:
        column_types = type_hints
    
    # Apply inferred types for consistency
    for row in rows:
        if not isinstance(row, dict):
            continue
            
        for key, type_name in column_types.items():
            if key not in row or row[key] is None:
                continue
                
            value = row[key]
            
            # Convert to the inferred type
            if type_name == 'int' and not isinstance(value, int):
                try:
                    row[key] = int(float(value)) if float(value).is_integer() else float(value)
                except (ValueError, TypeError):
                    pass
            elif type_name == 'float' and not isinstance(value, float):
                try:
                    row[key] = float(value)
                except (ValueError, TypeError):
                    pass
            elif type_name == 'bool' and not isinstance(value, bool):
                if isinstance(value, str):
                    if value.lower() in ('true', 'yes', 'y', '1'):
                        row[key] = True
                    elif value.lower() in ('false', 'no', 'n', '0'):
                        row[key] = False
    
    return rows


def load_csv(fp_in, delimiter=None, quotechar='"', remove_empty=False, 
        custom_headers=None, missing_header=False, skip_first_row=False, detect_types=True, **kwargs):
    # Set default values for CSV DictReader
    csv.field_size_limit(sys.maxsize)  # Handle very large fields
    
    # Auto-detect delimiter if not specified
    if delimiter is None:
        # Save current position and read sample for detection
        current_pos = fp_in.tell()
        sample = fp_in.read(4096)  # Read first 4KB for analysis
        fp_in.seek(current_pos)  # Reset position
        
        if sample:
            delimiter = detect_delimiter(sample)
            click.echo(f"Auto-detected delimiter: '{delimiter}'", err=True)
    
    # Default to comma if still not set
    if delimiter is None:
        delimiter = ','
    
    # Validate custom headers match column count
    if custom_headers:
        validated, _ = validate_header_count(fp_in, custom_headers, delimiter, quotechar)
    
    # Skip the first row if requested
    if skip_first_row:
        fp_in.readline()
    
    try:
        # For files with missing headers and no custom headers, return array of arrays
        if missing_header and not custom_headers:
            csv_reader = csv.reader(fp_in, delimiter=delimiter, quotechar=quotechar)
            rows = [row for row in csv_reader]
            
            # For array of arrays, we'll only detect numeric types
            if detect_types and rows:
                for i, row in enumerate(rows):
                    rows[i] = [detect_type(val) if isinstance(val, str) else val for val in row]
            return rows
        
        # Try to read the CSV file as dict
        if missing_header and custom_headers:
            # If no header in file but custom headers provided, use them
            r = csv.DictReader(fp_in, delimiter=delimiter, quotechar=quotechar,
                    fieldnames=custom_headers)
        elif custom_headers:
            # Using custom headers with a file that has headers (but we want to use our own)
            r = csv.DictReader(fp_in, delimiter=delimiter, quotechar=quotechar,
                    fieldnames=custom_headers)
        else:
            # Normal case with header in first row
            r = csv.DictReader(fp_in, delimiter=delimiter, quotechar=quotechar,
                    fieldnames=custom_headers)
                    
        rows = []
        for row_dct in r:
            # Clean up null or None values that might appear as strings
            cleaned_row = {}
            for key, value in row_dct.items():
                if key is None or key.lower() == 'null':
                    continue
                if isinstance(value, str) and (value == 'None' or value == 'null' or value.strip() == ''):
                    value = None
                cleaned_row[key] = value
            rows.append(cleaned_row)
        
        if remove_empty:
            rows = [dict([(k, item) for k, item in row.items() if item is not None]) for row in rows]
        
        # Detect and convert data types if requested
        if detect_types:
            rows = convert_data_types(rows)
            
        return rows
    except Exception as e:
        click.echo(f"Error parsing CSV: {e}", err=True)
        # Try a more lenient approach for problematic files
        fp_in.seek(0)  # Reset file pointer
        
        # Skip first row again if needed in the fallback parser
        if skip_first_row:
            fp_in.readline()
            
        return fallback_csv_parse(fp_in, delimiter, quotechar, custom_headers, missing_header, detect_types)


def fallback_csv_parse(fp_in, delimiter, quotechar, custom_headers=None, missing_header=False, detect_types=True):
    """A more lenient CSV parser for problematic files."""
    lines = fp_in.readlines()
    
    # Handle CSV with missing headers as array of arrays
    if missing_header and not custom_headers and lines:
        result = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Split by delimiter and handle quoted fields
            fields = []
            current_field = ""
            in_quotes = False
            for char in line:
                if char == quotechar:
                    in_quotes = not in_quotes
                elif char == delimiter and not in_quotes:
                    fields.append(current_field.strip(quotechar))
                    current_field = ""
                else:
                    current_field += char
            # Add the last field
            if current_field:
                fields.append(current_field.strip(quotechar))
                
            # Convert data types if requested
            if detect_types:
                fields = [detect_type(val) if isinstance(val, str) else val for val in fields]
                
            result.append(fields)
        return result
    
    # Determine headers
    if custom_headers:
        headers = custom_headers
    elif lines and not missing_header:
        headers = lines[0].strip().split(delimiter)
        lines = lines[1:]
    else:
        return []
    
    # Process each line
    result = []
    current_row = {}
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # If line starts with delimiter or appears to be a continuation
        if line.startswith(delimiter) or (line and line[0] not in (quotechar, delimiter)):
            # Add to previous row
            if current_row:
                for key in current_row:
                    if current_row[key]:
                        current_row[key] += " " + line
                        break
            continue
            
        # Process as new row
        if current_row:
            result.append(current_row)
            
        fields = line.split(delimiter)
        current_row = {}
        for i, field in enumerate(fields):
            if i < len(headers):
                header = headers[i]
                # Handle empty strings as null
                field_value = field.strip(quotechar)
                if field_value == '':
                    field_value = None
                current_row[header] = field_value
    
    # Add last row
    if current_row:
        result.append(current_row)
    
    # Detect and convert data types if requested
    if detect_types and result:
        result = convert_data_types(result)
        
    return result


def save_json(data, fp_out, pretty_spaces=4, sort_keys=False, id_field=None, **kwargs):
    if id_field and isinstance(data, list) and data and isinstance(data[0], dict):
        # If we should index the data by a specific field
        data_dict = {}
        for item in data:
            if id_field in item:
                data_dict[item[id_field]] = item
        # If no items had the id field, keep the original list
        if data_dict:
            data = data_dict
    
    json.dump(data, fp_out, indent=pretty_spaces, sort_keys=sort_keys, ensure_ascii=False)


def convert(csv_file, json_file, **kwargs):
    '''Convert csv to json.

    csv_file:  filename or file-like object
    json_file: filename  or file-like object
    '''

    csv_local, json_local = None, None
    try:
        if isinstance(csv_file, str):
            csv_file = csv_local = open(csv_file, 'r', encoding='utf-8')
        else:
            # Assuming it's already a file-like object (stdin)
            pass

        if isinstance(json_file, str):
            json_file = json_local = open(json_file, 'w', encoding='utf-8')
        else:
            # Assuming it's already a file-like object (stdout)
            pass

        data = load_csv(csv_file, **kwargs)
        save_json(data, json_file, **kwargs)
    finally:
        if csv_local is not None:
            csv_local.close()
        if json_local is not None:
            json_local.close()


def parse_custom_headers(custom_headers_arg):
    """Parse custom headers from comma-separated string or multiple values."""
    if not custom_headers_arg:
        return None
        
    # If it's a list of strings, it could be either multiple --custom-headers options
    # or a single comma-separated list that Click made into a tuple
    headers = []
    for header_item in custom_headers_arg:
        # Split each item by commas
        for header in header_item.split(','):
            header = header.strip()
            if header:
                headers.append(header)
    
    return headers if headers else None


@click.command(name="csv2json")
@click.argument('input_file', required=False)
@click.argument('output_file', required=False)
@click.option('--delimiter', '-d', default=None, help='CSV delimiter (auto-detected if not specified)')
@click.option('--quotechar', '-q', default='"', help='CSV quote character (default: ")')
@click.option('--remove-empty/--keep-empty', default=False, help='Remove empty fields (default: keep)')
@click.option('--pretty-spaces', '-p', default=4, type=int, help='Number of spaces for JSON indentation (default: 4)')
@click.option('--sort-keys/--no-sort-keys', default=False, help='Sort JSON keys alphabetically (default: no)')
@click.option('--custom-headers', help='Custom CSV headers as comma-separated list (e.g., "id,name,price")')
@click.option('--missing-header', is_flag=True, help='CSV file has no header row')
@click.option('--skip-first-row', is_flag=True, help='Skip the first row (useful with --custom-headers)')
@click.option('--id', 'id_field', help='Field to use as key in the output JSON dictionary')
@click.option('--no-type-detection', is_flag=True, help='Disable automatic data type detection')
def cli(input_file, output_file, delimiter, quotechar, remove_empty, pretty_spaces, 
        sort_keys, custom_headers, missing_header, skip_first_row, id_field, no_type_detection):
    """
    Convert CSV to JSON with support for piping, automatic delimiter detection, and data type detection.
    
    If INPUT_FILE is not specified, reads from standard input.
    If OUTPUT_FILE is not specified, writes to standard output.
    
    Examples:
      csv2json input.csv output.json
      cat input.csv | csv2json output.json
      cat input.csv | csv2json --delimiter=";" test.json
      cat input.csv | csv2json > output.json
      csv2json --missing-header input.csv output.json  # Returns array of arrays
      csv2json --missing-header --custom-headers="id,name,price" input.csv output.json
      csv2json --custom-headers="id,name,price" --skip-first-row input.csv output.json
      csv2json --id="product_id" input.csv output.json
        
    The delimiter is auto-detected by default, but can be manually specified with --delimiter.
    
    Data types are automatically detected (numbers, booleans, null values) unless --no-type-detection is specified.
    """
    # Handle input file
    if input_file is None:
        input_file = sys.stdin
    
    # Handle output file
    if output_file is None:
        output_file = sys.stdout
    
    # Parse custom headers from comma-separated list
    custom_headers_list = parse_custom_headers([custom_headers]) if custom_headers else None
    
    convert(
        input_file, 
        output_file, 
        delimiter=delimiter,
        quotechar=quotechar,
        remove_empty=remove_empty,
        pretty_spaces=pretty_spaces,
        sort_keys=sort_keys,
        custom_headers=custom_headers_list,
        missing_header=missing_header,
        skip_first_row=skip_first_row,
        id_field=id_field,
        detect_types=not no_type_detection
    )


if __name__ == "__main__":
    cli()
