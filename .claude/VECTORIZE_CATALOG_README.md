# Catalog Vectorization - README

## What Was Built

`Ingress/vectorize_catalog.py` - Vectorizes articles from catalog instead of raw markdown chunks.

### Key Features

✅ **Reads from Catalog** - Uses catalog.json + articles/*.md
✅ **Intelligent Chunking** - Splits by paragraph, or keeps whole if small
✅ **Rich Metadata** - Stores article_id, intent, category, relationships
✅ **Links to Articles** - Each chunk has article_id to retrieve complete article
✅ **Cloudflare/OpenAI** - Uses your configured LLM service

---

## How It Works

### 1. Read Articles from Catalog

```python
catalog_builder = CatalogBuilder(Path("output/catalog"))
article = catalog_builder.get_article("workspace_setup")
```

### 2. Chunk Each Article

**Small article (< 800 chars):**
```
Single chunk = entire article
```

**Large article (> 800 chars):**
```
Split by paragraphs → Group into chunks (100-1000 chars each)
```

**Example:**
```
Article "workspace_setup" (1500 chars)
    ↓
Chunk 0: Introduction + step 1-2 (600 chars)
Chunk 1: Step 3-4 + images (700 chars)
```

### 3. Store with Rich Metadata

Each chunk stored in ChromaDB with:

```python
{
    "article_id": "workspace_setup",      # Link back to catalog
    "title": "Setting Up Workspace",
    "intent": "do",                       # do/learn/trouble
    "category": "application",            # application/data
    "chunk_index": 0,                     # Position in article
    "total_chunks": 2,                    # Total chunks for this article
    "parent_id": "application_basics",    # Parent article
    "has_children": true,                 # Has child articles
    "see_also_ids": "widget;template",    # Related articles
    "heading_level": 2,                   # H2
    "images": "images/workspace.png",     # Images in chunk
    "gloss": "Guide to workspace setup"   # AI-generated summary
}
```

### 4. Enable Filtered Retrieval

Now you can search with metadata filters:

```python
# Find "how-to" articles about application
results = collection.query(
    query_texts=["how do I set up workspace"],
    n_results=5,
    where={
        "intent": "do",
        "category": "application"
    }
)

# Get article_ids
article_ids = [r['article_id'] for r in results['metadatas'][0]]

# Load complete articles from catalog
articles = [catalog.get_article(aid) for aid in article_ids]
```

---

## Usage

### Prerequisites

```bash
# 1. Build catalog first
python Ingress/build_catalog.py --input md/your_file.md

# 2. Ensure ChromaDB is installed
pip install chromadb

# 3. Ensure LLM service is configured (.env file with Cloudflare settings)
```

### Basic Usage

```bash
# Vectorize catalog (default settings)
python Ingress/vectorize_catalog.py

# Reset existing vectors first
python Ingress/vectorize_catalog.py --reset

# Custom batch size
python Ingress/vectorize_catalog.py --batch-size 10

# Custom collection name
python Ingress/vectorize_catalog.py --collection my_articles
```

### Advanced Options

```bash
python Ingress/vectorize_catalog.py \
    --catalog-dir output/catalog \
    --index-dir output/vector_index \
    --collection manual_chunks \
    --batch-size 8 \
    --reset \
    --pause 0.2
```

**Parameters:**
- `--catalog-dir`: Where catalog.json is located
- `--index-dir`: Where to store ChromaDB index
- `--collection`: ChromaDB collection name
- `--batch-size`: Chunks per embedding batch
- `--reset`: Clear existing vectors first
- `--pause`: Seconds between batches (rate limiting)

---

## Output

After successful vectorization:

```
======================================================================
VECTORIZATION COMPLETE
======================================================================
  Total articles: 7
  Processed: 7
  Failed: 0
  Total chunks: 15
  Avg chunks/article: 2.1
  Total time: 45.3s (0.8 min)
  Speed: 0.33 chunks/sec
======================================================================

Vector index: output/vector_index
Collection: manual_chunks
Total vectors: 15

Next steps:
  1. Test semantic search with metadata filters
  2. Integrate with app.py for catalog-based retrieval
======================================================================
```

---

## Chunking Algorithm

### ArticleChunker Class

```python
chunker = ArticleChunker(
    min_chunk_size=100,          # Minimum chunk size
    max_chunk_size=1000,         # Maximum chunk size
    whole_article_threshold=800  # Don't chunk if smaller than this
)
```

### Algorithm Steps

1. **Remove metadata block** from article content
2. **Check size**: If < 800 chars → return as single chunk
3. **Split by paragraphs** (double newline)
4. **Group paragraphs** into chunks:
   - Add paragraphs until max_chunk_size reached
   - Start new chunk
   - Skip tiny paragraphs (< 20 chars)
5. **Return chunks** with indices

**Example:**
```
Input article (1500 chars):
    Metadata block
    # Heading

    Paragraph 1 (300 chars)

    Paragraph 2 (400 chars)

    Paragraph 3 (500 chars)

    Paragraph 4 (300 chars)

Output:
    Chunk 0: Para 1 + Para 2 (700 chars)
    Chunk 1: Para 3 + Para 4 (800 chars)
```

---

## Metadata Fields Reference

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `article_id` | string | Unique article identifier | "workspace_setup" |
| `title` | string | Article title | "Setting Up Workspace" |
| `intent` | string | User intent | "do", "learn", "trouble" |
| `category` | string | Article category | "application", "data" |
| `chunk_index` | int | Chunk position in article | 0, 1, 2... |
| `total_chunks` | int | Total chunks for article | 3 |
| `parent_id` | string | Parent article ID (or "") | "application_basics" |
| `has_children` | bool | Has child articles | true, false |
| `see_also_ids` | string | Related article IDs (semicolon-separated) | "widget;template" |
| `heading_level` | int | Heading level (H1-H6) | 1, 2, 3... |
| `images` | string | Image paths (semicolon-separated) | "img1.png;img2.png" |
| `gloss` | string | AI-generated summary | "Guide to workspace..." |

---

## Benefits vs. Old Vectorization

| Feature | Old (vectorize.py) | New (vectorize_catalog.py) |
|---------|-------------------|---------------------------|
| Source | Raw markdown chunks | Catalog articles |
| Metadata | Heading hierarchy only | Rich: intent, category, relationships |
| Retrieval | Chunk fragments | Link to complete articles via article_id |
| Filtering | None | Filter by intent, category, parent, etc. |
| Relationships | None | Parent, children, see-also preserved |
| Maintainability | Hard to trace back | Easy: chunk → article_id → catalog |

---

## Next Steps

After vectorization completes:

### 1. Test Metadata Filtering

```python
from pathlib import Path
import chromadb

# Connect to ChromaDB
client = chromadb.PersistentClient(path="output/vector_index")
collection = client.get_collection("manual_chunks")

# Test query with filter
results = collection.query(
    query_texts=["how to customize"],
    n_results=5,
    where={"intent": "do"}  # Only "how-to" articles
)

print(f"Found {len(results['ids'][0])} results")
for metadata in results['metadatas'][0]:
    print(f"  • {metadata['title']} (article_id: {metadata['article_id']})")
```

### 2. Retrieve Complete Articles

```python
from catalog import CatalogBuilder

catalog = CatalogBuilder(Path("output/catalog"))

# Get article_ids from search results
article_ids = [m['article_id'] for m in results['metadatas'][0]]

# Load complete articles
for aid in set(article_ids):  # Unique IDs
    article = catalog.get_article(aid)
    print(f"\n{article['title']}")
    print(f"Intent: {article['intent']}")
    print(f"Content: {article['content'][:200]}...")
```

### 3. Integration Points

- **Query Classifier** (Phase 2.2): Classify user query → extract intent/category → use as filters
- **Catalog Retriever** (Phase 2.3): Search ChromaDB → get article_ids → load from catalog → add related articles
- **Backend App** (Phase 2.4): Integrate classifier + retriever → return complete articles

---

## Troubleshooting

### Issue: "Catalog not found"

```
✗ Error: Catalog not found at output/catalog/catalog.json
```

**Solution:** Build catalog first:
```bash
python Ingress/build_catalog.py --input md/your_file.md
```

### Issue: "Missing dependency 'chromadb'"

**Solution:** Install ChromaDB:
```bash
pip install chromadb
```

### Issue: Embedding failures

```
⚠ Gloss generation failed for workspace_setup__chunk_0: ...
```

**Check:**
1. `.env` file with Cloudflare/OpenAI credentials
2. `API_PROVIDER` environment variable set
3. Network connection

### Issue: Slow vectorization

**Solutions:**
- Increase `--batch-size` (default 8 → try 16)
- Reduce `--pause` (default 0.1s → try 0.05s)
- Use faster embedding model

---

## Code Architecture

```
vectorize_catalog.py
    ↓
CatalogBuilder (read articles)
    ↓
ArticleChunker (split into chunks)
    ↓
LLM Service (generate embeddings + glosses)
    ↓
ChromaDB (store with metadata)
```

**Key Classes:**

1. **ArticleChunker**: Intelligent chunking algorithm
2. **CatalogBuilder**: Read articles from catalog
3. **build_chunk_metadata()**: Build rich metadata
4. **vectorize_catalog()**: Main vectorization loop

---

## Testing

```bash
# 1. Test with small catalog
python Ingress/build_catalog.py --input md/test_catalog.md --clean
python Ingress/vectorize_catalog.py --reset --batch-size 4

# 2. Verify in ChromaDB
python3 << EOF
import chromadb
client = chromadb.PersistentClient(path="output/vector_index")
collection = client.get_collection("manual_chunks")
print(f"Total vectors: {collection.count()}")

# Test metadata filter
results = collection.query(
    query_texts=["workspace"],
    n_results=3,
    where={"category": "application"}
)
print(f"Application articles: {len(results['ids'][0])}")
EOF

# 3. Test article retrieval
python3 << EOF
from pathlib import Path
from catalog import CatalogBuilder
import chromadb

catalog = CatalogBuilder(Path("output/catalog"))
client = chromadb.PersistentClient(path="output/vector_index")
collection = client.get_collection("manual_chunks")

# Search
results = collection.query(query_texts=["setup workspace"], n_results=1)
article_id = results['metadatas'][0][0]['article_id']

# Get complete article
article = catalog.get_article(article_id)
print(f"Retrieved: {article['title']}")
print(f"Content length: {len(article['content'])} chars")
EOF
```

---

## What's Next?

Phase 2 continues with:

1. ✅ **vectorize_catalog.py** (DONE)
2. ⏳ **query_classifier.py** - Classify user queries
3. ⏳ **catalog_retriever.py** - Smart retrieval with filters
4. ⏳ **Update app.py** - Integrate everything

**You're 25% done with Phase 2!** 🎉
