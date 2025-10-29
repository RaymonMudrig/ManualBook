# Semantic Chunking Implementation

## Overview

The ManualBook system now uses **Semantic Chunking** instead of arbitrary token-based chunking. This ensures that search results return **complete, meaningful sections** rather than broken fragments.

## What Changed?

### Before (Token-Based Chunking)
- ❌ Chunked by ~600 tokens with 80 token overlap
- ❌ Broke sections mid-content
- ❌ Lost semantic boundaries
- ❌ Search returned incomplete information

### After (Semantic Chunking)
- ✅ Chunks by complete heading sections (H1-H6)
- ✅ Preserves full heading hierarchy
- ✅ Returns complete, understandable content
- ✅ Intelligent handling of large sections

## Implementation Details

### 1. Heading-Based Chunking

Each chunk represents a **complete section** defined by markdown headings:

```markdown
# Chapter 1                    ← Chunk 1
Content of chapter 1...

## Section 1.1                 ← Chunk 2
Content of section 1.1...

### Subsection 1.1.1          ← Chunk 3
Content of subsection 1.1.1...

## Section 1.2                 ← Chunk 4
Content of section 1.2...
```

### 2. Chunk Structure

New chunk format includes rich metadata:

```json
{
  "id": "abc123",
  "chunk_type": "section",
  "heading_level": 2,
  "heading_hierarchy": ["User Guide", "Installation", "Prerequisites"],
  "title": "User Guide / Installation / Prerequisites",
  "section_title": "Prerequisites",
  "text": "Complete section content...",
  "token_count": 850,
  "images": ["images/diagram.png"],
  "has_children": true,
  "parent_title": "Installation",
  "source": {
    "kind": "markdown",
    "file": "User_Manual.md",
    "section_index": 5
  }
}
```

### 3. Intelligent Section Splitting

When a section exceeds max token limit (2000 tokens):

1. **First**: Try to split at sub-heading boundaries
2. **Fallback**: Split at paragraph boundaries (double newline)
3. **Last resort**: Keep large paragraphs intact (better than mid-sentence breaks)

### 4. Configuration

Adjust these parameters in `Ingress/parse_md.py`:

```python
MIN_CHUNK_SIZE = 100      # Keep small sections intact
MAX_CHUNK_SIZE = 2000     # Split larger sections at this threshold
TARGET_CHUNK_SIZE = 800   # Ideal size for embeddings
```

## Benefits

### 1. Complete Content in Results

**Query**: "How to reset the device?"

**Old Result** (broken):
```
...follow these steps carefully. First, power off
the device and wait for 30 seconds. Then...
```

**New Result** (complete):
```
📍 Path: User Manual > Troubleshooting > Device Reset

## Device Reset

To reset your device, follow these steps:

1. Power off the device completely
2. Wait for 30 seconds
3. Press and hold the reset button for 10 seconds
4. Release and power on

Note: This will erase all custom settings.
```

### 2. Better Context Understanding

- Full heading path shows **exact location** in document
- Parent/child relationships preserved
- Complete sections = better LLM comprehension

### 3. User-Friendly Navigation

Search results now show:
- 📍 **Full heading path**: "Manual > Chapter > Section"
- **Parent context**: Links to related sections
- **Complete content**: No broken sentences
- **Token count**: Know how much content you're reading

## Example Output

### Query Response Format

```json
{
  "query": "system requirements",
  "answer": "The system requires...",
  "mode": "rag",
  "sources": [
    {
      "id": "abc123",
      "title": "Installation Guide / Prerequisites / System Requirements",
      "heading_path": "Installation Guide > Prerequisites > System Requirements",
      "level": 3,
      "section": "System Requirements",
      "parent": "Prerequisites",
      "score": 0.89,
      "tokens": 450,
      "source_file": "User_Manual.md"
    }
  ]
}
```

## Backward Compatibility

The system gracefully handles **both** chunking formats:

- ✅ New semantic chunks (with hierarchy metadata)
- ✅ Old token-based chunks (without hierarchy)

To migrate existing data:

```bash
# Re-parse with new semantic chunking
python Ingress/parse_md.py

# Re-vectorize with --reset flag
python Ingress/vectorize.py --reset
```

## Testing

### Test the New Chunking

```bash
# 1. Parse a markdown file
python Ingress/parse_md.py

# 2. Check the generated chunks
cat output/chunks/YourFile.jsonl | jq '.'

# 3. Verify heading hierarchy is preserved
cat output/chunks/YourFile.jsonl | jq '.heading_hierarchy'
```

### Example Output

```bash
$ cat output/chunks/User_Manual.jsonl | head -1 | jq '.'
{
  "id": "fc23da6476287cb6",
  "chunk_type": "section",
  "heading_level": 1,
  "heading_hierarchy": [
    "User Manual"
  ],
  "title": "User Manual",
  "section_title": "User Manual",
  "text": "# User Manual\n\nWelcome to the comprehensive user manual...",
  "token_count": 245,
  "images": [],
  "has_children": true,
  "parent_title": null,
  "source": {
    "kind": "markdown",
    "file": "User_Manual.md",
    "section_index": 0
  }
}
```

## Technical Details

### Parse Algorithm

1. **Parse Headings**: Identify all H1-H6 headings
2. **Build Hierarchy**: Maintain parent-child relationships using a stack
3. **Collect Content**: Gather all content under each heading
4. **Estimate Tokens**: Calculate rough token count (chars/4)
5. **Split if Needed**: Break large sections at paragraph boundaries
6. **Generate Chunks**: Create JSON records with full metadata

### Key Functions

- `parse_markdown_by_sections()`: Build section tree from markdown
- `split_large_section()`: Intelligently split oversized sections
- `section_to_chunks()`: Convert sections to chunk records
- `Section.get_heading_path()`: Generate full heading hierarchy

## Performance Considerations

### Token Estimation

Uses rough estimate: `tokens ≈ characters / 4`

This is approximate but sufficient for:
- ✅ Preventing oversized chunks
- ✅ Fast computation (no tokenizer needed)
- ✅ Consistent across all documents

### Memory Usage

- Minimal: Processes documents line-by-line
- Scales: Handles documents of any size
- Efficient: Only stores current section tree in memory

## Troubleshooting

### Problem: Chunks still too large

**Solution**: Reduce `MAX_CHUNK_SIZE` in `parse_md.py`:
```python
MAX_CHUNK_SIZE = 1500  # Default: 2000
```

### Problem: Small sections creating too many chunks

**Solution**: Increase `MIN_CHUNK_SIZE`:
```python
MIN_CHUNK_SIZE = 200  # Default: 100
```

### Problem: Want different chunking for specific documents

**Solution**: Create custom parse script:
```python
# parse_custom.py
from parse_md import process_markdown, MAX_CHUNK_SIZE

# Override for this run
MAX_CHUNK_SIZE = 1000
process_markdown(Path("my_special_doc.md"))
```

## Future Enhancements

Potential improvements:

1. **Sibling Navigation**: Link to next/previous sections
2. **Table of Contents**: Generate TOC from chunk hierarchy
3. **Section Summaries**: Auto-generate summaries for large sections
4. **Smart Merging**: Combine very small adjacent sections
5. **Multi-level Context**: Include parent section content in context

## Migration Guide

### From Old to New Format

1. **Backup Current Data**
   ```bash
   cp -r output/chunks output/chunks.backup
   cp -r output/vector_index output/vector_index.backup
   ```

2. **Re-parse with Semantic Chunking**
   ```bash
   python Ingress/parse_md.py
   ```

3. **Re-vectorize**
   ```bash
   python Ingress/vectorize.py --reset
   ```

4. **Test Search**
   ```bash
   cd Backend
   python app.py
   # Query and verify hierarchy is displayed
   ```

5. **Rollback if Needed**
   ```bash
   # Restore backup
   rm -rf output/chunks output/vector_index
   mv output/chunks.backup output/chunks
   mv output/vector_index.backup output/vector_index
   ```

## Summary

✅ **Complete Content**: No more broken fragments
✅ **Full Hierarchy**: Know exactly where content comes from
✅ **Better UX**: Users get meaningful, complete answers
✅ **Backward Compatible**: Works with old and new chunks
✅ **Configurable**: Adjust chunk sizes as needed
✅ **Production Ready**: Tested and optimized

The semantic chunking implementation transforms ManualBook from a simple RAG system into a **hierarchically-aware knowledge base** that respects document structure and returns complete, meaningful content.
