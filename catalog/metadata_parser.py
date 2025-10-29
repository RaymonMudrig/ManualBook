"""
Metadata parser for ManualBook articles.

Parses metadata from HTML comments in markdown files.

Format:
<!--METADATA
intent: do
id: editing_palette
category: application
see:
    - palette_feature
    - other_article
-->
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


class MetadataError(ValueError):
    """Exception raised when metadata is invalid."""
    pass


def parse_metadata(content: str) -> Optional[Dict]:
    """Parse metadata from HTML comment block.

    Args:
        content: Markdown content containing metadata

    Returns:
        Dictionary with metadata fields, or None if no metadata found

    Raises:
        MetadataError: If metadata format is invalid

    Example:
        >>> content = '''
        ... <!--METADATA
        ... intent: do
        ... id: editing_palette
        ... category: application
        ... see:
        ...     - palette_feature
        ...     - other_article
        ... -->
        ... # Article Content
        ... '''
        >>> metadata = parse_metadata(content)
        >>> metadata['id']
        'editing_palette'
    """
    # Find HTML comment block with METADATA
    pattern = r'<!--\s*METADATA\s*\n(.*?)\n\s*-->'
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)

    if not match:
        return None

    metadata_text = match.group(1)
    return _parse_metadata_text(metadata_text)


def _parse_metadata_text(text: str) -> Dict:
    """Parse the actual metadata text content.

    Args:
        text: Metadata text content (without HTML comment markers)

    Returns:
        Dictionary with parsed metadata

    Raises:
        MetadataError: If parsing fails
    """
    metadata = {}
    current_key = None
    list_values = []

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Check if it's a list item
        if line.startswith('-'):
            if current_key is None:
                raise MetadataError(f"List item without a key: {line}")
            # Extract list item value
            value = line[1:].strip()
            list_values.append(value)
            continue

        # Check if it's a key-value pair
        if ':' in line:
            # Save previous list if any
            if current_key and list_values:
                metadata[current_key] = list_values
                list_values = []

            # Parse new key-value
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            if value:
                # Single value
                metadata[key] = value
                current_key = None
            else:
                # Empty value means list follows
                current_key = key
                list_values = []
            continue

        # If we get here, it's an error
        raise MetadataError(f"Invalid metadata line: {line}")

    # Save final list if any
    if current_key and list_values:
        metadata[current_key] = list_values

    # Validate required fields
    _validate_metadata(metadata)

    return metadata


def _validate_metadata(metadata: Dict) -> None:
    """Validate metadata fields.

    Args:
        metadata: Parsed metadata dictionary

    Raises:
        MetadataError: If validation fails
    """
    # Required fields
    required = ['intent', 'id', 'category']
    for field in required:
        if field not in metadata:
            raise MetadataError(f"Missing required field: {field}")

    # Validate intent
    valid_intents = ['do', 'learn', 'trouble']
    if metadata['intent'] not in valid_intents:
        raise MetadataError(
            f"Invalid intent '{metadata['intent']}'. Must be one of: {valid_intents}"
        )

    # Validate category
    valid_categories = ['application', 'data']
    if metadata['category'] not in valid_categories:
        raise MetadataError(
            f"Invalid category '{metadata['category']}'. Must be one of: {valid_categories}"
        )

    # Validate id format (lowercase, alphanumeric, underscore, hyphen)
    if not re.match(r'^[a-z0-9_-]+$', metadata['id']):
        raise MetadataError(
            f"Invalid id '{metadata['id']}'. Must contain only lowercase letters, numbers, underscore, and hyphen."
        )

    # Ensure 'see' is a list
    if 'see' in metadata:
        if isinstance(metadata['see'], str):
            # Convert single value to list
            metadata['see'] = [metadata['see']]
        elif not isinstance(metadata['see'], list):
            raise MetadataError(f"'see' field must be a list, got: {type(metadata['see'])}")

    # Parse synonyms (comma-separated string to list)
    if 'synonyms' in metadata:
        if isinstance(metadata['synonyms'], str):
            # Split by comma, strip whitespace, filter empty
            metadata['synonyms'] = [s.strip() for s in metadata['synonyms'].split(',') if s.strip()]
        elif isinstance(metadata['synonyms'], list):
            # Already a list, just strip each item
            metadata['synonyms'] = [s.strip() for s in metadata['synonyms'] if s.strip()]
        else:
            raise MetadataError(f"'synonyms' field must be a string or list, got: {type(metadata['synonyms'])}")

    # Parse codes (comma-separated string to list, uppercase)
    if 'codes' in metadata:
        if isinstance(metadata['codes'], str):
            # Split by comma, strip whitespace, uppercase, filter empty
            metadata['codes'] = [c.strip().upper() for c in metadata['codes'].split(',') if c.strip()]
        elif isinstance(metadata['codes'], list):
            # Already a list, just strip and uppercase each item
            metadata['codes'] = [c.strip().upper() for c in metadata['codes'] if c.strip()]
        else:
            raise MetadataError(f"'codes' field must be a string or list, got: {type(metadata['codes'])}")


def extract_metadata_block(content: str) -> tuple[Optional[Dict], str]:
    """Extract metadata and return metadata + content without metadata block.

    Args:
        content: Markdown content with metadata

    Returns:
        Tuple of (metadata dict, content without metadata block)

    Example:
        >>> content = '''<!--METADATA
        ... intent: do
        ... id: test
        ... category: application
        ... -->
        ... # Article
        ... Content here'''
        >>> metadata, clean_content = extract_metadata_block(content)
        >>> metadata['id']
        'test'
        >>> '<!--METADATA' in clean_content
        False
    """
    metadata = parse_metadata(content)

    if metadata:
        # Remove metadata block from content
        pattern = r'<!--\s*METADATA\s*\n.*?\n\s*-->\s*\n?'
        clean_content = re.sub(pattern, '', content, count=1, flags=re.DOTALL | re.IGNORECASE)
    else:
        clean_content = content

    return metadata, clean_content


if __name__ == "__main__":
    # Test the parser
    test_content = """<!--METADATA
intent: do
id: editing_palette
category: application
synonyms: palette editor, color palette, palette settings
codes: P100, PALETTE
see:
    - palette_feature
    - color_settings
-->

# Editing Palette

This article explains how to edit the palette.

## Steps

1. Open palette editor
2. Select colors
3. Save changes
"""

    try:
        metadata = parse_metadata(test_content)
        print("✓ Metadata parsed successfully:")
        print(f"  ID: {metadata['id']}")
        print(f"  Intent: {metadata['intent']}")
        print(f"  Category: {metadata['category']}")
        print(f"  Synonyms: {metadata.get('synonyms', [])}")
        print(f"  Codes: {metadata.get('codes', [])}")
        print(f"  See: {metadata.get('see', [])}")

        metadata_dict, clean = extract_metadata_block(test_content)
        print(f"\n✓ Content without metadata ({len(clean)} chars)")
        print(f"  Starts with: {clean[:50]}...")

    except MetadataError as e:
        print(f"✗ Error: {e}")
