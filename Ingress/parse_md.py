from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, Dict

BASE_DIR = Path(__file__).resolve().parents[1]
MD_DIR = BASE_DIR / "md"
OUT_DIR = BASE_DIR / "output"
CHUNK_DIR = OUT_DIR / "chunks"
IMAGE_ROOT = OUT_DIR / "images"

CHUNK_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_ROOT.mkdir(parents=True, exist_ok=True)

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
CODE_FENCE_PATTERN = re.compile(r"^(```|~~~)")
IMAGE_PATTERN = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<dest>[^)]+)\)")
WHITESPACE_RE = re.compile(r"\s+")

# Chunking configuration
MIN_CHUNK_SIZE = 100  # tokens - keep small sections intact
MAX_CHUNK_SIZE = 2000  # tokens - split larger sections
TARGET_CHUNK_SIZE = 800  # tokens - ideal size for embeddings


def sanitize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def parse_image_destination(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1]
    try:
        parts = shlex.split(cleaned)
    except ValueError:
        parts = cleaned.split()
    return parts[0] if parts else cleaned


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 characters per token."""
    return max(1, len(text) // 4)


def copy_image(md_path: Path, dest: str, ctx: dict) -> str | None:
    url = dest.strip()
    if not url or url.startswith(("http://", "https://", "data:")):
        return url or None

    relative = url.lstrip("./")
    candidates = [
        md_path.parent / url,
        md_path.parent / relative,
        BASE_DIR / url.lstrip("/"),
        BASE_DIR / relative.lstrip("/"),
    ]

    source = next((p for p in candidates if p.exists()), None)
    if not source or not source.is_file():
        return None

    source = source.resolve()
    cached = ctx["copied"].get(str(source))
    if cached:
        return cached

    safe_parts = [
        part for part in Path(relative).parts if part not in ("..", "")
    ] or [source.name]
    relative_subpath = Path(*safe_parts)
    target_dir = ctx["image_dir"] / relative_subpath.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / relative_subpath.name
    if not target_path.exists():
        shutil.copy2(source, target_path)

    rel_path = (ctx["image_rel_root"] / relative_subpath).as_posix()
    ctx["copied"][str(source)] = rel_path
    return rel_path


def replace_images(md_path: Path, text: str, ctx: dict) -> Tuple[str, List[str]]:
    found: List[str] = []

    def _replace(match: re.Match) -> str:
        alt = sanitize_whitespace(match.group("alt"))
        dest_raw = match.group("dest")
        href = parse_image_destination(dest_raw)
        new_path = copy_image(md_path, href, ctx)
        if new_path:
            if new_path not in found:
                found.append(new_path)
            return f"![{alt}]({new_path})"
        return f"![{alt}]({href})"

    updated = IMAGE_PATTERN.sub(_replace, text)
    return updated, found


def extract_images_from_text(text: str) -> List[str]:
    paths: List[str] = []
    for match in IMAGE_PATTERN.finditer(text):
        href = parse_image_destination(match.group("dest"))
        if href and href not in paths:
            paths.append(href)
    return paths


class Section:
    """Represents a document section with heading hierarchy."""

    def __init__(
        self,
        level: int,
        title: str,
        content: List[str],
        parent: Optional[Section] = None,
    ):
        self.level = level
        self.title = title
        self.content = content
        self.parent = parent
        self.children: List[Section] = []

    def get_heading_path(self) -> List[str]:
        """Get full heading path from root to this section."""
        if self.parent:
            return self.parent.get_heading_path() + [self.title]
        return [self.title] if self.title else []

    def get_full_text(self) -> str:
        """Get complete section text including title."""
        parts = []
        if self.title:
            parts.append(f"{'#' * self.level} {self.title}")
        if self.content:
            parts.append("\n".join(self.content))
        return "\n\n".join(parts)

    def get_content_only(self) -> str:
        """Get section content without title."""
        return "\n".join(self.content) if self.content else ""

    def add_child(self, child: Section):
        self.children.append(child)


def split_large_section(section: Section, max_size: int) -> List[Section]:
    """
    Split a large section into smaller chunks at paragraph boundaries.
    Preserves heading hierarchy.
    """
    content = section.get_content_only()
    tokens = estimate_tokens(content)

    if tokens <= max_size:
        return [section]

    # Split at paragraph boundaries (double newline)
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        # If single paragraph is too large, keep it intact (better than breaking mid-sentence)
        if not current_chunk and para_tokens > max_size:
            chunk_section = Section(
                level=section.level,
                title=f"{section.title} (part {len(chunks) + 1})",
                content=[para],
                parent=section.parent
            )
            chunks.append(chunk_section)
            continue

        # If adding this paragraph exceeds limit, flush current chunk
        if current_chunk and current_tokens + para_tokens > max_size:
            chunk_section = Section(
                level=section.level,
                title=f"{section.title} (part {len(chunks) + 1})" if chunks else section.title,
                content=current_chunk,
                parent=section.parent
            )
            chunks.append(chunk_section)
            current_chunk = []
            current_tokens = 0

        current_chunk.append(para)
        current_tokens += para_tokens

    # Flush remaining
    if current_chunk:
        chunk_section = Section(
            level=section.level,
            title=f"{section.title} (part {len(chunks) + 1})" if chunks else section.title,
            content=current_chunk,
            parent=section.parent
        )
        chunks.append(chunk_section)

    return chunks if chunks else [section]


def parse_markdown_by_sections(md_path: Path) -> List[Section]:
    """
    Parse markdown into hierarchical sections based on heading structure.
    """
    sections: List[Section] = []
    heading_stack: List[Section] = []  # Stack to maintain hierarchy
    current_content: List[str] = []
    in_code_block = False

    # Root section for content before first heading
    root = Section(level=0, title="", content=[], parent=None)
    heading_stack.append(root)

    with md_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\n")
            fence = stripped.strip()

            # Track code blocks to avoid parsing headings inside them
            if CODE_FENCE_PATTERN.match(fence):
                in_code_block = not in_code_block
                current_content.append(stripped)
                continue

            if in_code_block:
                current_content.append(stripped)
                continue

            # Check for heading
            match = HEADING_PATTERN.match(stripped)
            if match:
                level = len(match.group(1))
                title = sanitize_whitespace(match.group(2))

                # Save current section's content
                if heading_stack:
                    heading_stack[-1].content.extend(current_content)
                    current_content = []

                # Find appropriate parent (pop stack until we find lower level)
                while len(heading_stack) > 1 and heading_stack[-1].level >= level:
                    heading_stack.pop()

                parent = heading_stack[-1] if heading_stack else None
                new_section = Section(level=level, title=title, content=[], parent=parent)

                if parent:
                    parent.add_child(new_section)

                heading_stack.append(new_section)
                sections.append(new_section)
            else:
                # Regular content line
                current_content.append(stripped)

    # Save final content
    if heading_stack and current_content:
        heading_stack[-1].content.extend(current_content)

    # If root has content but no children, it's a document without headings
    if root.content and not root.children:
        sections.append(root)

    return sections


def section_to_chunks(
    section: Section,
    md_path: Path,
    ctx: dict,
    chunk_index: int
) -> Tuple[List[Dict], int]:
    """
    Convert a section into one or more chunks with metadata.
    """
    chunks = []

    # Get full text
    full_text = section.get_full_text()
    tokens = estimate_tokens(full_text)

    # Determine if we need to split this section
    sections_to_process = [section]
    if tokens > MAX_CHUNK_SIZE:
        sections_to_process = split_large_section(section, MAX_CHUNK_SIZE)

    for sect in sections_to_process:
        text = sect.get_full_text()
        tokens = estimate_tokens(text)

        # Skip very small sections (likely empty or just whitespace)
        if tokens < 10:
            continue

        # Replace images and get updated text
        replaced_text, images = replace_images(md_path, text, ctx)

        # Build heading hierarchy path
        heading_path = sect.get_heading_path()
        title = " / ".join(heading_path) if heading_path else md_path.stem

        # Generate chunk ID
        chunk_id = hashlib.sha1(
            f"{md_path.name}:{title}:{chunk_index}".encode("utf-8")
        ).hexdigest()[:16]

        # Create chunk record
        record = {
            "id": chunk_id,
            "chunk_type": "section",
            "heading_level": sect.level,
            "heading_hierarchy": heading_path,
            "title": title,
            "section_title": sect.title,
            "text": replaced_text,
            "token_count": tokens,
            "images": images,
            "has_children": len(sect.children) > 0,
            "parent_title": sect.parent.title if sect.parent and sect.parent.title else None,
            "source": {
                "kind": "markdown",
                "file": md_path.name,
                "section_index": chunk_index
            }
        }

        chunks.append(record)
        chunk_index += 1

    # Process children
    for child in section.children:
        child_chunks, chunk_index = section_to_chunks(child, md_path, ctx, chunk_index)
        chunks.extend(child_chunks)

    return chunks, chunk_index


def process_markdown(md_path: Path) -> None:
    """Process a markdown file into semantic chunks based on heading structure."""

    image_dir = IMAGE_ROOT / md_path.stem
    shutil.rmtree(image_dir, ignore_errors=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    ctx = {
        "image_dir": image_dir,
        "image_rel_root": Path("images") / md_path.stem,
        "copied": {},
    }

    # Parse markdown into sections
    sections = parse_markdown_by_sections(md_path)

    # Convert sections to chunks
    chunks: List[Dict] = []
    chunk_index = 0

    for section in sections:
        section_chunks, chunk_index = section_to_chunks(section, md_path, ctx, chunk_index)
        chunks.extend(section_chunks)

    if not chunks:
        print(f"  Warning: No chunks generated for {md_path.name}")
        return

    # Write chunks to JSONL
    output_path = CHUNK_DIR / f"{md_path.stem}.jsonl"
    with output_path.open("w", encoding="utf-8") as writer:
        for record in chunks:
            writer.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  ✓ Generated {len(chunks)} semantic chunks from {md_path.name}")


def main() -> None:
    if not MD_DIR.exists():
        raise SystemExit(f"Missing md directory: {MD_DIR}")

    md_files = sorted(f for f in MD_DIR.glob("*.md") if not f.name.startswith("~$"))
    if not md_files:
        raise SystemExit(f"No .md files found in {MD_DIR}")

    print(f"Processing {len(md_files)} markdown file(s) with semantic chunking...")
    print(f"Strategy: Chunk by heading structure (H1-H6)")
    print(f"Max chunk size: {MAX_CHUNK_SIZE} tokens")
    print()

    for md_file in md_files:
        process_markdown(md_file)

    print()
    print("✓ All files processed successfully!")


if __name__ == "__main__":
    main()
