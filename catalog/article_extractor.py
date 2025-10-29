"""
Article extractor for ManualBook catalog.

Extracts articles from markdown based on heading structure and metadata.

Rules:
1. Articles are always in a heading scope that has metadata
2. Heading structure automatically creates parent-child relationships
3. "see also" lists extra relationships outside heading structure
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .metadata_parser import parse_metadata, extract_metadata_block, MetadataError


@dataclass
class Article:
    """Represents an extracted article."""
    id: str
    title: str
    intent: str
    category: str
    content: str  # Full markdown content including heading
    metadata: Dict
    heading_level: int
    parent_id: Optional[str] = None
    children_ids: List[str] = None
    see_also_ids: List[str] = None
    images: List[str] = None
    synonyms: List[str] = None
    codes: List[str] = None

    def __post_init__(self):
        if self.children_ids is None:
            self.children_ids = []
        if self.see_also_ids is None:
            self.see_also_ids = self.metadata.get('see', [])
        if self.images is None:
            self.images = []
        if self.synonyms is None:
            self.synonyms = self.metadata.get('synonyms', [])
        if self.codes is None:
            self.codes = self.metadata.get('codes', [])


def extract_articles(markdown_content: str, source_file: str = "unknown") -> List[Article]:
    """Extract articles from markdown content based on metadata and heading structure.

    New two-step process:
    1. Parse ALL sections (with/without metadata)
    2. Group sections into articles using stack-based approach

    Rules:
    - Section WITH metadata → creates new article
    - Section WITHOUT metadata → appends to parent article (top of stack)
    - Heading structure preserved when appending

    Args:
        markdown_content: Full markdown file content
        source_file: Name of source file (for error reporting)

    Returns:
        List of Article objects

    Example:
        >>> content = '''
        ... <!--METADATA
        ... intent: learn
        ... id: palettes
        ... category: application
        ... -->
        ... # Palettes
        ... Introduction to palettes
        ...
        ... ## Color Options
        ... No metadata - appends to parent
        ...
        ... <!--METADATA
        ... intent: do
        ... id: editing_palette
        ... category: application
        ... -->
        ... ## Editing a Palette
        ... How to edit
        ... '''
        >>> articles = extract_articles(content)
        >>> len(articles)
        2
        >>> "Color Options" in articles[0].content
        True
    """
    # Step 1: Parse all sections (with and without metadata)
    sections = _parse_all_sections(markdown_content)

    if not sections:
        return []

    # Step 2: Build articles using stack-based grouping
    articles = _build_articles_from_sections(sections, source_file)

    return articles


def _parse_all_sections(markdown_content: str) -> List[Dict]:
    """Parse ALL heading sections from markdown (with or without metadata).

    Returns flat list of sections with:
    - level: heading level (1-6)
    - heading: heading text
    - content: full section content (metadata + heading + body)
    - has_metadata: boolean flag
    - metadata: parsed metadata dict (if has_metadata=True)

    Args:
        markdown_content: Full markdown content

    Returns:
        List of section dictionaries
    """
    sections = []

    # Find all headings with their positions
    heading_pattern = r'^(#{1,6})\s+(.+)$'
    heading_matches = list(re.finditer(heading_pattern, markdown_content, re.MULTILINE))

    if not heading_matches:
        return []

    # For each heading, extract its section content
    for i, heading_match in enumerate(heading_matches):
        level = len(heading_match.group(1))
        heading_text = heading_match.group(2).strip()
        heading_start = heading_match.start()

        # Find end of this section
        if i + 1 < len(heading_matches):
            next_heading_start = heading_matches[i + 1].start()

            # Check if there's a metadata block before the next heading
            # If so, end current section before that metadata
            search_area = markdown_content[heading_start:next_heading_start]
            metadata_pattern_end = r'<!--\s*METADATA\s*\n.*?\n\s*-->'
            metadata_matches_in_section = list(re.finditer(metadata_pattern_end, search_area, re.DOTALL | re.IGNORECASE))

            if metadata_matches_in_section:
                # End current section just before the first metadata block found
                section_end = heading_start + metadata_matches_in_section[0].start()
            else:
                # No metadata found, end at next heading
                section_end = next_heading_start
        else:
            section_end = len(markdown_content)

        # Check if there's a metadata block BEFORE this heading
        # Look backwards from heading to find metadata
        search_start = max(0, heading_start - 500)  # Look back max 500 chars
        section_start = heading_start
        metadata_dict = None
        has_metadata = False

        # Search for metadata block before this heading
        # Use finditer to find ALL matches, then take the LAST (closest) one
        metadata_pattern = r'<!--\s*METADATA\s*\n(.*?)\n\s*-->'
        content_before = markdown_content[search_start:heading_start]
        metadata_matches = list(re.finditer(metadata_pattern, content_before, re.DOTALL | re.IGNORECASE))

        # Take the last (closest) metadata block
        if metadata_matches:
            metadata_match = metadata_matches[-1]

            # Check if there's another heading between metadata and this heading
            metadata_end = search_start + metadata_match.end()
            text_between = markdown_content[metadata_end:heading_start]

            # If there's another heading in between, metadata doesn't belong to this heading
            if re.search(r'^#{1,6}\s+', text_between, re.MULTILINE):
                has_metadata = False
                metadata_dict = None
                section_start = heading_start
            else:
                # Found metadata right before this heading (no intervening headings)
                metadata_block_start = search_start + metadata_match.start()
                section_start = metadata_block_start
                has_metadata = True

                # Parse the metadata
                try:
                    metadata_dict = parse_metadata(metadata_match.group(0))
                except:
                    # Invalid metadata, treat as no metadata
                    has_metadata = False
                    metadata_dict = None
                    section_start = heading_start

        # Extract full section content
        section_content = markdown_content[section_start:section_end].strip()

        sections.append({
            'level': level,
            'heading': heading_text,
            'content': section_content,
            'has_metadata': has_metadata,
            'metadata': metadata_dict
        })

    return sections


def _build_articles_from_sections(sections: List[Dict], source_file: str) -> List[Article]:
    """Build articles from parsed sections using stack-based grouping.

    Rules:
    - Section WITH metadata → create new article, push to stack
    - Section WITHOUT metadata → append to current parent (top of stack)
    - Stack maintains hierarchy: pop when encountering same/higher level

    Args:
        sections: List of parsed section dicts from _parse_all_sections()
        source_file: Source file name for error reporting

    Returns:
        List of Article objects
    """
    articles = []
    stack = []  # Stack of (level, article) tuples

    for section in sections:
        level = section['level']
        heading = section['heading']
        content = section['content']
        has_metadata = section['has_metadata']
        metadata = section['metadata']

        if has_metadata:
            # Pop stack until we find parent (level < current)
            while stack and stack[-1][0] >= level:
                stack.pop()
            # Validate required metadata fields
            if not metadata or 'id' not in metadata:
                print(f"⚠ Warning: Skipping section '{heading}' - missing 'id' in metadata")
                continue

            if 'intent' not in metadata or 'category' not in metadata:
                print(f"⚠ Warning: Skipping section '{heading}' (id: {metadata.get('id')}) - missing 'intent' or 'category'")
                continue

            # Determine parent from stack
            parent_id = stack[-1][1].id if stack else None

            # Extract images
            images = _extract_images(content)

            # Create new article
            article = Article(
                id=metadata['id'],
                title=heading,
                intent=metadata['intent'],
                category=metadata['category'],
                content=content,
                metadata=metadata,
                heading_level=level,
                parent_id=parent_id,
                images=images
            )

            articles.append(article)

            # Update parent's children list
            if parent_id:
                for a in articles:
                    if a.id == parent_id:
                        a.children_ids.append(article.id)
                        break

            # Push to stack
            stack.append((level, article))

        else:
            # No metadata - append to current parent
            # Pop stack to find appropriate parent (level < current)
            while stack and stack[-1][0] >= level:
                stack.pop()

            if stack:
                parent_article = stack[-1][1]

                # Reconstruct section with heading (preserve structure)
                section_heading = f"{'#' * level} {heading}"
                section_body = content

                # If content starts with heading, use as-is
                # Otherwise, prepend heading
                if not content.startswith('#'):
                    section_text = f"\n\n{section_heading}\n\n{section_body}"
                else:
                    section_text = f"\n\n{content}"

                # Append to parent article
                parent_article.content += section_text

                # Extract and add images from this section
                section_images = _extract_images(content)
                parent_article.images.extend(section_images)

            else:
                # Orphan section at root level (no parent to append to)
                print(f"⚠ Warning: Section '{heading}' at level {level} has no metadata and no parent - skipping")

    return articles


def _extract_images(content: str) -> List[str]:
    """Extract image paths from markdown content.

    Args:
        content: Markdown content

    Returns:
        List of image paths
    """
    # Find all markdown image syntax: ![alt](path)
    pattern = r'!\[.*?\]\(([^\)]+)\)'
    matches = re.findall(pattern, content)
    return matches


def build_relationship_graph(articles: List[Article]) -> Dict:
    """Build relationship graph from articles.

    Args:
        articles: List of Article objects

    Returns:
        Dictionary representing the relationship graph

    Example:
        {
            "articles": {
                "editing_palette": {
                    "parent": "palettes",
                    "children": [],
                    "see_also": ["color_settings"],
                    "intent": "do",
                    "category": "application"
                }
            }
        }
    """
    graph = {"articles": {}}

    for article in articles:
        graph["articles"][article.id] = {
            "title": article.title,
            "intent": article.intent,
            "category": article.category,
            "heading_level": article.heading_level,
            "parent": article.parent_id,
            "children": article.children_ids.copy(),
            "see_also": article.see_also_ids.copy(),
            "images": article.images.copy(),
            "synonyms": article.synonyms.copy(),
            "codes": article.codes.copy()
        }

    return graph


if __name__ == "__main__":
    # Test the extractor
    test_content = """<!--METADATA
intent: learn
id: palettes
category: application
-->
# Palettes

Introduction to palette system in the application.

![Palette Overview](images/palette_overview.png)

<!--METADATA
intent: do
id: editing_palette
category: application
see:
    - color_settings
    - workspace_config
-->
## Editing a Palette

Step-by-step guide to edit palettes.

![Edit Dialog](images/edit_dialog.png)

1. Open palette editor
2. Make changes
3. Save

<!--METADATA
intent: do
id: creating_palette
category: application
-->
## Creating a New Palette

How to create a new palette from scratch.

<!--METADATA
intent: learn
id: orderbook_data
category: data
-->
# Orderbook Data

Understanding orderbook data structure.
"""

    try:
        articles = extract_articles(test_content, "test.md")
        print(f"✓ Extracted {len(articles)} articles:\n")

        for article in articles:
            print(f"ID: {article.id}")
            print(f"  Title: {article.title}")
            print(f"  Intent: {article.intent}")
            print(f"  Category: {article.category}")
            print(f"  Level: H{article.heading_level}")
            print(f"  Parent: {article.parent_id or '(none)'}")
            print(f"  Children: {article.children_ids or '(none)'}")
            print(f"  See Also: {article.see_also_ids or '(none)'}")
            print(f"  Images: {len(article.images)}")
            print()

        graph = build_relationship_graph(articles)
        print("✓ Relationship graph built")
        print(f"  Total articles: {len(graph['articles'])}")

    except MetadataError as e:
        print(f"✗ Error: {e}")
