from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import List

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    BASE_DIR_TEMP = Path(__file__).resolve().parents[1]
    env_path = BASE_DIR_TEMP / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, skip

# Add parent directory to path for gtranslate module import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gtranslate.translate_service import translate_text, TranslationError

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = BASE_DIR / "md" / "User_Manual_IDX_Terminal_v1-0.mdx"
DEFAULT_OUTPUT = DEFAULT_INPUT.with_suffix(".md")

# Translation settings
DEFAULT_SOURCE_LANGUAGE = "id"  # Indonesian
DEFAULT_TARGET_LANGUAGE = "en"  # English


def is_code_fence(line: str) -> bool:
    """Check if line is a code fence marker."""
    stripped = line.strip()
    return stripped.startswith("```")


def is_table_line(line: str) -> bool:
    """Check if line is part of a markdown table."""
    stripped = line.strip()
    return "|" in line and not stripped.startswith("//")


def is_image_line(line: str) -> bool:
    """Check if line contains a markdown image."""
    stripped = line.strip()
    return stripped.startswith("![") and "](" in stripped


def is_list_item(line: str) -> bool:
    """Check if line is a list item."""
    stripped = line.strip()
    # Unordered list
    if stripped.startswith(("-", "*", "+")):
        return True
    # Ordered list (starts with number followed by dot or parenthesis)
    if re.match(r"^\d+[\.\)]\s", stripped):
        return True
    return False


def is_heading(line: str) -> bool:
    """Check if line is a markdown heading."""
    stripped = line.strip()
    return stripped.startswith("#")


def extract_list_marker(line: str) -> tuple[str, str]:
    """Extract list marker and content from a list item.

    Returns:
        (marker, content) tuple
        e.g., "- Hello world" -> ("- ", "Hello world")
              "1. Hello world" -> ("1. ", "Hello world")
    """
    stripped = line.strip()

    # Unordered list
    for marker in ["-", "*", "+"]:
        if stripped.startswith(marker):
            content = stripped[1:].strip()
            # Preserve original indentation
            indent = line[:len(line) - len(line.lstrip())]
            return f"{indent}{marker} ", content

    # Ordered list
    match = re.match(r"^(\s*)(\d+[\.\)])\s+(.*)$", line)
    if match:
        indent, number, content = match.groups()
        return f"{indent}{number} ", content

    return "", stripped


def extract_heading_marker(line: str) -> tuple[str, str]:
    """Extract heading marker and content.

    Returns:
        (marker, content) tuple
        e.g., "## Hello" -> ("## ", "Hello")
    """
    stripped = line.strip()
    match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
    if match:
        hashes, content = match.groups()
        return f"{hashes} ", content
    return "", stripped


def translate_markdown_line_by_line(
    lines: List[str],
    src_lang: str,
    dest_lang: str,
) -> List[str]:
    """Translate markdown content line by line using Google Translate.

    Rules:
    1. Translation performed line by line, no concatenation
    2. Ignore tables, paste as-is
    3. Ignore code-fenced blocks, paste as-is
    4. Ignore images, paste as-is
    5. Translate list items line by line

    Args:
        lines: List of lines to translate
        src_lang: Source language code
        dest_lang: Destination language code

    Returns:
        List of translated lines
    """
    translated_lines: List[str] = []
    in_code_block = False
    in_table = False
    total_lines = len(lines)
    translated_count = 0
    failed_count = 0

    print(f"\nTranslating {total_lines} lines using Google Translate...")
    print(f"Source: {src_lang} → Target: {dest_lang}")
    print("=" * 70)

    for line_num, line in enumerate(lines, 1):
        # Show progress
        if line_num % 50 == 0 or line_num == total_lines:
            progress = (line_num / total_lines) * 100
            print(f"Progress: [{line_num}/{total_lines}] {progress:.1f}% | Translated: {translated_count} | Failed: {failed_count}")

        # Handle code blocks
        if is_code_fence(line):
            in_code_block = not in_code_block
            translated_lines.append(line)
            continue

        if in_code_block:
            # Inside code block: no translation
            translated_lines.append(line)
            continue

        # Handle images
        if is_image_line(line):
            # Image line: no translation
            translated_lines.append(line)
            continue

        # Handle tables
        if is_table_line(line):
            if not in_table:
                in_table = True
            translated_lines.append(line)
            continue
        else:
            if in_table:
                in_table = False

        # Handle empty lines
        if not line.strip():
            translated_lines.append(line)
            continue

        # Handle list items
        if is_list_item(line):
            marker, content = extract_list_marker(line)
            if content.strip():
                try:
                    translated_content = translate_text(content, source=src_lang, target=dest_lang)
                    translated_lines.append(f"{marker}{translated_content}")
                    translated_count += 1
                except TranslationError as exc:
                    print(f"⚠ Line {line_num}: Translation failed, using original")
                    translated_lines.append(line)
                    failed_count += 1
            else:
                translated_lines.append(line)
            continue

        # Handle headings
        if is_heading(line):
            marker, content = extract_heading_marker(line)
            if content.strip():
                try:
                    translated_content = translate_text(content, source=src_lang, target=dest_lang)
                    translated_lines.append(f"{marker}{translated_content}")
                    translated_count += 1
                except TranslationError as exc:
                    print(f"⚠ Line {line_num}: Translation failed, using original")
                    translated_lines.append(line)
                    failed_count += 1
            else:
                translated_lines.append(line)
            continue

        # Regular text line: translate
        if line.strip():
            try:
                translated_line = translate_text(line.strip(), source=src_lang, target=dest_lang)
                # Preserve original indentation
                indent = line[:len(line) - len(line.lstrip())]
                translated_lines.append(f"{indent}{translated_line}")
                translated_count += 1
            except TranslationError as exc:
                print(f"⚠ Line {line_num}: Translation failed, using original")
                # Preserve original line on failure
                translated_lines.append(line)
                failed_count += 1
        else:
            translated_lines.append(line)

    print("=" * 70)
    print(f"✓ Translation complete!")
    print(f"  Total lines: {total_lines}")
    print(f"  Translated lines: {translated_count}")
    print(f"  Failed lines: {failed_count}")
    print(f"  Skipped lines: {total_lines - translated_count - failed_count}")
    print("=" * 70)

    return translated_lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate Markdown to English using Google Translate (line-by-line).",
        epilog="Example: python translate_md.py --input document.mdx --output document.md"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to the source Markdown file (default: User_Manual_IDX_Terminal_v1-0.mdx)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path to write the translated Markdown (default: same name with .md extension)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=DEFAULT_SOURCE_LANGUAGE,
        help="Source language code (default: id for Indonesian)",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=DEFAULT_TARGET_LANGUAGE,
        help="Target language code (default: en for English)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    print(f"\n{'='*70}")
    print(f"Markdown Translation Tool")
    print(f"{'='*70}")
    print(f"Input:  {args.input}")
    print(f"Output: {args.output}")
    print(f"Source language: {args.source}")
    print(f"Target language: {args.target}")
    print(f"{'='*70}")

    # Read input file
    source_text = args.input.read_text(encoding="utf-8")
    source_lines = source_text.splitlines()

    print(f"\nInput file: {len(source_text)} characters, {len(source_lines)} lines")

    # Translate line by line
    translated_lines = translate_markdown_line_by_line(source_lines, args.source, args.target)

    # Write output
    result = "\n".join(translated_lines)
    if not result.endswith("\n"):
        result += "\n"

    args.output.write_text(result, encoding="utf-8")

    print(f"\n✓ Translated markdown written to {args.output}")
    print(f"  Output: {len(result)} characters, {len(translated_lines)} lines")
    print(f"  Size ratio: {len(result)/len(source_text)*100:.1f}%\n")


if __name__ == "__main__":
    main()
