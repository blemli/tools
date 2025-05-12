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
    
    # Skip comment lines that start with '#'
    data_lines = [line for line in lines if not line.strip().startswith('#')]
    if not data_lines:
        # If all lines are comments, still use the original lines
        data_lines = lines
    
    # Count occurrences of each delimiter in each line
    scores = {}
    for delimiter in possible_delimiters:
        scores[delimiter] = 0
        # Check consistency of field count
        field_counts = Counter()
        
        for line in data_lines[:10]:  # Check first 10 lines at most
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
                scores[delimiter] *= (frequency / len(data_lines[:10])) * 2
    
    # Special handling for tab-delimited files (often mixed with spaces)
    if '\t' in possible_delimiters and '\t' in sample_data:
        # Check if typical tab-delimited patterns exist
        tab_pattern_score = 0
        
        # Typical tab-delimited files have consistent structure with tabs between fields
        # Count the number of lines where tabs appear at consistent positions
        tab_positions = set()
        
        for line in data_lines[:10]:
            line_positions = [i for i, char in enumerate(line) if char == '\t']
            if line_positions:
                if not tab_positions:
                    tab_positions = set(line_positions)
                else:
                    # Bonus for consistent tab positions
                    tab_pattern_score += len(tab_positions.intersection(set(line_positions)))
        
        # Apply the calculated pattern score as a bonus for tabs
        if tab_pattern_score > 0:
            scores['\t'] += tab_pattern_score * 2
        
        # Another heuristic: If there are many spaces vs tabs
        # This helps with files that have multiple spaces as column separators but use tabs as field separators
        spaces_count = sum(line.count(' ') for line in data_lines[:10])
        tabs_count = sum(line.count('\t') for line in data_lines[:10])
        if tabs_count > 0 and spaces_count / max(tabs_count, 1) > 5:
            # If there are a lot more spaces than tabs, the tabs are likely meaningful delimiters
            scores['\t'] *= 2
    
    # Default to comma if we couldn't determine or if all scores are 0
    if not scores or all(score == 0 for score in scores.values()):
        return ','
        
    # Return the delimiter with the highest score
    return max(scores, key=scores.get)


def validate_header_count(fp, custom_headers, delimiter, quotechar, ignore_mismatch=False):
    """
    Validate that the number of custom headers matches the number of columns in the CSV.
    
    Args:
        fp: File pointer to the CSV
        custom_headers: List of custom headers
        delimiter: Delimiter used in the CSV
        quotechar: Quote character used in the CSV
        ignore_mismatch: Whether to suppress the warning message
        
    Returns:
        Boolean indicating if validation passed, and the current position in file
    """
    if not custom_headers:
        return True, 0
    
    # Save current position
    start_pos = fp.tell()
    
    # Skip any comment lines or empty lines at the beginning
    sample_lines = []
    line = fp.readline()
    while line and (line.strip().startswith('#') or line.strip() == ''):
        sample_lines.append(line)
        line = fp.readline()
    
    # If we found a non-comment line, use it for column counting
    if line:
        sample_lines.append(line)
    
    # Reset file position
    fp.seek(start_pos)
    
    if not sample_lines:
        return True, start_pos
    
    # Use the last non-comment line for column detection
    sample = sample_lines[-1]
    
    # Count fields in a robust way
    try:
        # For tab-delimited files, try a more robust approach first
        if delimiter == '\t':
            # Use a regex to split by tabs more reliably
            fields = [f for f in re.split(r'\t+', sample.strip()) if f.strip()]
            column_count = len(fields)
        else:
            # Use standard CSV reader for other delimiters
            reader = csv.reader([sample], delimiter=delimiter, quotechar=quotechar)
            fields = next(reader)
            column_count = len(fields)
        
        header_count = len(custom_headers)
        
        # For display purposes, show tabs as '\t'
        display_delimiter = '\\t' if delimiter == '\t' else delimiter
        
        if column_count != header_count and not ignore_mismatch:
            click.echo(f"Warning: Number of custom headers ({header_count}) does not match " +
                      f"number of CSV columns ({column_count}) with delimiter '{display_delimiter}'", err=True)
        
        return True, start_pos
    except Exception as e:
        click.echo(f"Warning: Error counting columns: {e}", err=True)
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


def parse_transforms(transform_arg):
    """
    Parse the transform argument to extract column types and transformations.
    
    Format: "column1:type/transform1/transform2,column2:type,..."
    
    Examples:
      - "id:number,name:string/trim/upper,active:bool"
      - "price:float,date:string/trim"
      - "code:string/replace:old=new"
    
    Args:
        transform_arg: String containing transform specifications
        
    Returns:
        Dictionary mapping column names to their type and transformations
    """
    if not transform_arg:
        return {}
        
    transforms = {}
    for item in transform_arg.split(','):
        if not item or ':' not in item:
            continue
            
        column, specs = item.split(':', 1)
        column = column.strip()
        if not column:
            continue
            
        specs_parts = specs.split('/')
        # First part is the type
        type_name = specs_parts[0].strip().lower()
        
        # Map friendly type names to internal type names
        type_map = {
            'string': 'string',
            'str': 'string',
            'text': 'string',
            'number': 'float',
            'num': 'float',
            'float': 'float',
            'integer': 'int',
            'int': 'int',
            'boolean': 'bool',
            'bool': 'bool',
        }
        
        # Default to string if type is not recognized
        type_name = type_map.get(type_name, 'string')
        
        # Remaining parts are transformations
        transformations = []
        for t in specs_parts[1:]:
            if not t.strip():
                continue
                
            if t.startswith('replace:'):
                # Handle replace transformation with parameters
                _, replace_spec = t.split(':', 1)
                if '=' in replace_spec:
                    old_val, new_val = replace_spec.split('=', 1)
                    transformations.append(('replace', (old_val, new_val)))
            else:
                # Regular transformation without parameters
                transformations.append((t.strip().lower(), None))
        
        transforms[column] = {
            'type': type_name,
            'transformations': transformations
        }
    
    return transforms


def apply_transformations(value, transformations):
    """
    Apply a list of transformations to a value.
    
    Args:
        value: The value to transform
        transformations: List of transformation specifications
        
    Returns:
        Transformed value
    """
    if value is None:
        return None
        
    result = value
    original = value
    
    for transform_spec in transformations:
        if isinstance(transform_spec, tuple):
            transform_name, transform_params = transform_spec
        else:
            transform_name, transform_params = transform_spec, None
            
        if transform_name == 'upper' and isinstance(result, str):
            result = result.upper()
        elif transform_name == 'lower' and isinstance(result, str):
            result = result.lower()
        elif transform_name == 'trim' and isinstance(result, str):
            result = result.strip()
        elif transform_name == 'capitalize' and isinstance(result, str):
            result = result.capitalize()
        elif transform_name == 'title' and isinstance(result, str):
            result = result.title()
        elif transform_name == 'replace' and isinstance(result, str) and transform_params:
            old_val, new_val = transform_params
            result = result.replace(old_val, new_val)
    
    # Print debug info if value was transformed
    if result != original:
        click.echo(f"Applied transformation: '{original}' -> '{result}'", err=True)
    
    return result


def convert_data_types(rows, type_hints=None, transforms=None):
    """
    Convert data types in a list of dictionaries based on detected types.
    
    Args:
        rows: List of dictionaries (row data)
        type_hints: Optional dictionary mapping column names to explicit types
        transforms: Optional dictionary mapping column names to transform specs
        
    Returns:
        Updated list of dictionaries with converted data types and transformations
    """
    if not rows:
        return rows
        
    has_transforms = transforms and isinstance(transforms, dict)
    
    # First pass: detect types for all values unless explicit types provided
    if not type_hints:
        for row in rows:
            if not isinstance(row, dict):
                continue
                
            for key, value in row.items():
                # Skip columns with explicit type specifications
                if has_transforms and key in transforms:
                    continue
                    
                if isinstance(value, str):
                    row[key] = detect_type(value)
    
    # Second pass: infer and normalize column types
    column_types = {}
    
    if type_hints:
        column_types.update(type_hints)
    
    # If we have transforms, use those type specifications
    if has_transforms:
        for col, spec in transforms.items():
            column_types[col] = spec['type']
    
    # For columns without explicit types, infer types
    if not column_types:
        column_types.update(infer_column_types(rows))
    
    # Apply inferred types and transformations
    for row in rows:
        if not isinstance(row, dict):
            continue
            
        for key, value in row.items():
            if key not in row or row[key] is None:
                continue
                
            # Apply transformations if specified
            if has_transforms and key in transforms:
                value = row[key]
                # First apply transformations
                value = apply_transformations(value, transforms[key]['transformations'])
                row[key] = value
            
            # Apply type conversion
            if key in column_types:
                value = row[key]
                type_name = column_types[key]
                
                if type_name == 'int' and not isinstance(value, int):
                    try:
                        row[key] = int(float(value)) if isinstance(value, (str, float)) and float(value).is_integer() else float(value)
                    except (ValueError, TypeError, AttributeError):
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
        custom_headers=None, missing_header=False, skip_first_row=0, detect_types=True, 
        transforms=None, ignore_column_mismatch=False, verbose=False, **kwargs):
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
            
            # If delimiter is tab and verbose is enabled, show more details
            if verbose and delimiter == '\t':
                click.echo("Tab-delimited file detected. Analyzing structure:", err=True)
                fp_in.seek(current_pos)  # Reset position
                debug_csv_structure(fp_in, delimiter=delimiter, quotechar=quotechar)
                fp_in.seek(current_pos)  # Reset position again
    
    # Default to comma if still not set
    if delimiter is None:
        delimiter = ','
    
    # Validate custom headers match column count - this now just provides a warning
    if custom_headers:
        validated, _ = validate_header_count(fp_in, custom_headers, delimiter, quotechar, ignore_column_mismatch)
        
        # Show verbose debug info if there are issues with custom headers
        if verbose and not validated:
            fp_in.seek(0)  # Reset position
            debug_csv_structure(fp_in, delimiter=delimiter, quotechar=quotechar)
            fp_in.seek(0)  # Reset position again
    
    # Skip rows if requested (including comment lines)
    skipped = 0
    rows_to_skip = skip_first_row
    while skipped < rows_to_skip:
        line = fp_in.readline()
        if not line:
            break
        # Only count non-comment lines toward our skip count
        if not line.strip().startswith('#'):
            skipped += 1
    
    # Skip any remaining comments at the beginning
    pos = fp_in.tell()
    line = fp_in.readline()
    while line and line.strip().startswith('#'):
        pos = fp_in.tell()
        line = fp_in.readline()
    fp_in.seek(pos)  # Go back to start of first non-comment line
    
    try:
        # Enhanced handling for tab-delimited files
        if delimiter == '\t':
            # Try to read the file using a more flexible approach for tab-delimited files
            return parse_tab_delimited_file(fp_in, custom_headers, missing_header, detect_types, transforms)
        
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
            
            # Only add the row if it has at least one non-None value
            if any(v is not None for v in cleaned_row.values()):
                rows.append(cleaned_row)
        
        if remove_empty:
            rows = [dict([(k, item) for k, item in row.items() if item is not None]) for row in rows]
        
        # Detect and convert data types if requested
        if detect_types:
            rows = convert_data_types(rows, transforms=transforms)
            
        return rows
    except Exception as e:
        click.echo(f"Error parsing CSV: {e}", err=True)
        # Try a more lenient approach for problematic files
        fp_in.seek(0)  # Reset file pointer
        
        # Skip rows again
        skipped = 0
        while skipped < skip_first_row:
            line = fp_in.readline()
            if not line:
                break
            if not line.strip().startswith('#'):
                skipped += 1
            
        return fallback_csv_parse(fp_in, delimiter, quotechar, custom_headers, missing_header, 
                                 detect_types, skip_first_row, transforms, ignore_column_mismatch)


def parse_tab_delimited_file(fp_in, custom_headers=None, missing_header=False, detect_types=True, transforms=None):
    """
    More flexible parsing for tab-delimited files, especially Wireshark manuf format.
    """
    # Read all lines
    lines = fp_in.readlines()
    
    # Filter out comment lines and empty lines
    data_lines = [line.strip() for line in lines if line.strip() and not line.strip().startswith('#')]
    
    # Determine headers
    headers = custom_headers
    if not headers and not missing_header and data_lines:
        # Use first line as header if not missing
        header_line = data_lines[0]
        headers = [h.strip() for h in re.split(r'\t+', header_line) if h.strip()]
        data_lines = data_lines[1:]  # Skip header line
    
    if not headers:
        # Return data as arrays if no headers
        rows = []
        for line in data_lines:
            fields = [f.strip() for f in re.split(r'\t+', line) if f.strip()]
            if fields:
                rows.append(fields)
        return rows
    
    # Parse each line into a dictionary
    rows = []
    for line in data_lines:
        fields = [f.strip() for f in re.split(r'\t+', line) if f]
        if not fields:
            continue
            
        row = {}
        for i, field in enumerate(fields):
            if i < len(headers):
                header = headers[i]
                row[header] = field if field.strip() else None
            else:
                # If more fields than headers, append to the last header
                if len(headers) > 0:
                    last_header = headers[-1]
                    if last_header in row and row[last_header]:
                        row[last_header] += " " + field
                    else:
                        row[last_header] = field
        
        # Only add rows with data
        if any(v is not None for v in row.values()):
            rows.append(row)
    
    # Detect and convert data types if requested
    if detect_types:
        rows = convert_data_types(rows, transforms=transforms)
        
    return rows


def fallback_csv_parse(fp_in, delimiter, quotechar, custom_headers=None, missing_header=False, 
                      detect_types=True, skip_first_row=0, transforms=None, ignore_column_mismatch=False):
    """A more lenient CSV parser for problematic files."""
    # For tab-delimited files, use our specialized tab parser
    if delimiter == '\t':
        return parse_tab_delimited_file(fp_in, custom_headers, missing_header, detect_types, transforms)
    
    # For other delimiters, use the original fallback logic
    lines = fp_in.readlines()
    
    # Skip rows if specified
    if skip_first_row > 0 and len(lines) > skip_first_row:
        lines = lines[skip_first_row:]
    
    # Filter out comment lines
    lines = [line for line in lines if line.strip() and not line.strip().startswith('#')]
    
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
        result = convert_data_types(result, transforms=transforms)
        
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

        # Print transform info for debugging
        if 'transforms' in kwargs and kwargs['transforms'] and kwargs.get('verbose', False):
            click.echo(f"Applying transforms: {kwargs['transforms']}", err=True)
        
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
@click.option('--delimiter', '-d', default=None, help='CSV delimiter (auto-detected if not specified). Special: "\\t" for tab')
@click.option('--quotechar', '-q', default='"', help='CSV quote character (default: ")')
@click.option('--remove-empty/--keep-empty', default=False, help='Remove empty fields (default: keep)')
@click.option('--pretty-spaces', '-p', default=4, type=int, help='Number of spaces for JSON indentation (default: 4)')
@click.option('--sort-keys/--no-sort-keys', default=False, help='Sort JSON keys alphabetically (default: no)')
@click.option('--custom-headers', help='Custom CSV headers as comma-separated list (e.g., "id,name,price")')
@click.option('--missing-header', is_flag=True, help='CSV file has no header row')
@click.option('--skip', '-s', default=0, type=int, help='Number of rows to skip from the beginning (default: 0)')
@click.option('--id', 'id_field', help='Field to use as key in the output JSON dictionary')
@click.option('--no-type-detection', is_flag=True, help='Disable automatic data type detection')
@click.option('--transform', '-t', help='Specify column types and transformations (e.g., "id:int,name:string/trim/upper,active:bool")')
@click.option('--ignore-column-mismatch', is_flag=True, help='Ignore warning when custom headers count does not match CSV column count')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose debug output')
def cli(input_file, output_file, delimiter, quotechar, remove_empty, pretty_spaces, 
        sort_keys, custom_headers, missing_header, skip, id_field, no_type_detection, transform, 
        ignore_column_mismatch, verbose):
    """
    Convert CSV to JSON with support for piping, automatic delimiter detection, and data type detection.
    
    If INPUT_FILE is not specified, reads from standard input.
    If OUTPUT_FILE is not specified, writes to standard output.
    
    Examples:
      csv2json input.csv output.json
      cat input.csv | csv2json output.json
      cat input.csv | csv2json --delimiter=";" test.json
      cat input.csv | csv2json --delimiter="\t" output.json  # Use tab as delimiter
      csv2json --delimiter='\\t' input.csv output.json       # Alternative way to specify tab
      cat input.csv | csv2json > output.json
      csv2json --missing-header input.csv output.json        # Returns array of arrays
      csv2json --missing-header --custom-headers="id,name,price" input.csv output.json
      csv2json --custom-headers="id,name,price" --skip=1 input.csv output.json
      csv2json --skip=3 input.csv output.json                # Skip first 3 rows
      csv2json --id="product_id" input.csv output.json
      csv2json --transform="id:int,name:string/upper" input.csv output.json
      csv2json --ignore-column-mismatch --custom-headers="mac,vendor" input.csv output.json
        
    The delimiter is auto-detected by default, but can be manually specified with --delimiter.
    
    Special delimiters:
      - For tab character: use --delimiter="\t" or --delimiter='\\t'
      - Other supported escape sequences: \\n (newline), \\r (carriage return), etc.
      
    Transformations:
      Use --transform to specify column types and transformations:
        "column:type/transform1/transform2,..."
      
      Supported types: string (str), int (integer), float (number), bool (boolean)
      Supported transformations: 
        - upper, lower, trim, capitalize, title
        - replace:old=new (replaces 'old' with 'new' in the text)
      
      Examples: 
        --transform="id:int,name:string/trim/upper,price:float,active:bool"
        --transform="code:string/replace:-=_,name:string/upper"
    
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
    
    # Parse transform specifications
    transform_dict = parse_transforms(transform)
    
    # Handle special delimiter characters
    if delimiter:
        # Process common escape sequences
        escape_sequences = {
            '\\t': '\t',   # tab
            '\\n': '\n',   # newline
            '\\r': '\r',   # carriage return
            '\\f': '\f',   # form feed
            '\\v': '\v',   # vertical tab
        }
        
        # If the delimiter is a recognized escape sequence
        if delimiter in escape_sequences:
            delimiter = escape_sequences[delimiter]
        # If the delimiter is quoted and contains escape sequences
        elif (delimiter.startswith('"') and delimiter.endswith('"')) or \
             (delimiter.startswith("'") and delimiter.endswith("'")):
            # Remove quotes
            unquoted = delimiter[1:-1]
            # Replace escape sequences
            for seq, char in escape_sequences.items():
                unquoted = unquoted.replace(seq, char)
            delimiter = unquoted
    
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
        skip_first_row=skip,
        id_field=id_field,
        detect_types=not no_type_detection,
        transforms=transform_dict,
        ignore_column_mismatch=ignore_column_mismatch,
        verbose=verbose
    )


def debug_csv_structure(fp, max_lines=5, delimiter=None, quotechar='"'):
    """
    Debug helper to analyze the structure of a CSV file.
    This is called when there are issues with delimiter detection or column count.
    
    Args:
        fp: File pointer to the CSV
        max_lines: Maximum number of lines to analyze
        delimiter: Delimiter used in the CSV
        quotechar: Quote character used in the CSV
    """
    # Save current position
    start_pos = fp.tell()
    
    click.echo("Analyzing CSV structure:", err=True)
    
    # Read a few sample lines for analysis
    lines = []
    for _ in range(max_lines):
        line = fp.readline()
        if not line:
            break
        lines.append(line)
    
    # Reset file position
    fp.seek(start_pos)
    
    if not lines:
        click.echo("  File appears to be empty", err=True)
        return
    
    # Analyze each line
    for i, line in enumerate(lines):
        # Show line info
        click.echo(f"  Line {i+1} ({len(line)} chars):", err=True)
        click.echo(f"    Raw: {repr(line)}", err=True)
        
        # If delimiter is specified, show field breakdown
        if delimiter:
            # Try to parse with csv module
            reader = csv.reader([line], delimiter=delimiter, quotechar=quotechar)
            try:
                fields = next(reader)
                click.echo(f"    Fields ({len(fields)}): {fields}", err=True)
            except Exception as e:
                click.echo(f"    Error parsing with csv module: {e}", err=True)
            
            # Also show simple split result for comparison
            simple_fields = line.strip().split(delimiter)
            click.echo(f"    Simple split ({len(simple_fields)}): {simple_fields}", err=True)


if __name__ == "__main__":
    cli()
