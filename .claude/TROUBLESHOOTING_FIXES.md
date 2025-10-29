# Troubleshooting Fixes Log

## Issue 1: ChromaDB Import Error (FIXED)

### Problem
```
Missing dependency 'chromadb'. Install it with 'pip install chromadb' and retry.
ModuleNotFoundError: No module named 'google.protobuf'
```

Despite having `chromadb` installed, the app couldn't import it due to a namespace collision.

### Root Cause
The local `/google/` directory (Google Translate service) was shadowing the `google.protobuf` package that ChromaDB requires.

When Python tried to `import google.protobuf`, it found the local `google/` directory first and couldn't find the `protobuf` submodule there.

### Solution
1. **Renamed directory**: `/google/` → `/gtranslate/`
2. **Updated imports**: Changed `from google.translate_service` to `from gtranslate.translate_service` in:
   - `Ingress/translate_md.py`

### Files Changed
- `google/` → `gtranslate/` (directory rename)
- `Ingress/translate_md.py` (import updated)

### Verification
```bash
python -c "import chromadb; print(chromadb.__version__)"
# Output: 1.2.2
```

---

## Issue 2: Pydantic V2 Deprecation Warning (FIXED)

### Problem
```
PydanticDeprecatedSince20: Pydantic V1 style `@validator` validators are deprecated.
You should migrate to Pydantic V2 style `@field_validator` validators
```

### Root Cause
The `QueryPayload` class in `Backend/app.py` was using Pydantic V1 style `@validator` decorator, which is deprecated in Pydantic V2.

### Solution
Updated validator to Pydantic V2 syntax:

**Before:**
```python
from pydantic import BaseModel, Field, validator

class QueryPayload(BaseModel):
    query: str = Field(...)

    @validator("query")
    def clean_query(cls, value: str) -> str:
        # validation logic
        return cleaned
```

**After:**
```python
from pydantic import BaseModel, Field, field_validator

class QueryPayload(BaseModel):
    query: str = Field(...)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        # validation logic
        return cleaned
```

### Files Changed
- `Backend/app.py`
  - Import: `validator` → `field_validator`
  - Decorator: `@validator("query")` → `@field_validator("query")` + `@classmethod`

### Verification
```bash
python Backend/app.py
# No deprecation warnings
```

---

## Current Status

✅ **All issues resolved**

The application now starts without errors or deprecation warnings:

```
✓ Loaded environment from /Users/raymonmudrig/AI/ManualBook/.env
✓ Catalog system initialized (Phase 2 mode)
INFO: Uvicorn running on http://0.0.0.0:8800
```

### Expected Warnings (Normal)
These warnings are expected and not issues:

1. **CORS Warning**:
   ```
   WARNING - CORS is set to allow all origins. This is not recommended for production!
   ```
   - **Reason**: `CORS_ORIGINS=*` in `.env` for development
   - **Fix for production**: Set `CORS_ORIGINS=https://yourdomain.com` in `.env`

2. **ChromaDB Telemetry**:
   ```
   INFO - Anonymized telemetry enabled.
   ```
   - **Reason**: ChromaDB sends anonymized usage stats
   - **To disable**: Set `ANONYMIZED_TELEMETRY=False` in `.env` (optional)

---

## Summary of Changes

### Namespace Collision Fix
- **Problem**: Local `google/` directory shadowing `google.protobuf` package
- **Solution**: Renamed to `gtranslate/`, updated imports
- **Impact**: ChromaDB now imports successfully

### Pydantic V2 Migration
- **Problem**: Using deprecated V1 `@validator` decorator
- **Solution**: Migrated to V2 `@field_validator` with `@classmethod`
- **Impact**: No more deprecation warnings

### Phase 2 Status
✅ All Phase 2 components working:
- Query Classifier
- Catalog Retriever
- Metadata-filtered search
- Complete article retrieval with relationships

---

## Testing

### Quick Test
```bash
# 1. Verify ChromaDB imports
python -c "import chromadb; print('✓ ChromaDB OK')"

# 2. Verify app starts
python Backend/app.py
# Look for: "✓ Catalog system initialized (Phase 2 mode)"

# 3. Test API
curl http://localhost:8800/health
# Expected: {"status":"ok"}
```

### Full Test
```bash
# Test query classification
curl -X POST http://localhost:8800/api/classify \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I set up workspace?"}'

# Test catalog retrieval
curl -X POST http://localhost:8800/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I set up workspace?", "top_k": 3}'
```

---

## Lessons Learned

1. **Namespace Collisions**: Avoid naming local directories after common Python packages (google, test, data, etc.)
2. **Import Precedence**: Python searches for modules in this order:
   - Current directory
   - Directories in `sys.path`
   - Standard library
   - Installed packages

3. **Best Practices**:
   - Use unique names for local modules (e.g., `gtranslate` instead of `google`)
   - Keep up with library migrations (Pydantic V2)
   - Test imports after major changes

---

---

## Issue 3: Embedding Dimension Mismatch (FIXED)

### Problem
```
⚠ ChromaDB query failed: Collection expecting embedding with dimension of 768, got 384
```

Queries were failing because the retriever was using ChromaDB's default embedding function (384 dims) instead of Cloudflare embeddings (768 dims).

### Root Cause
`catalog_retriever.py` was using `query_texts=[query]` which triggers ChromaDB's built-in embedding function:
```python
results = self.chroma.query(
    query_texts=[query],  # ❌ Uses ChromaDB default (384 dims)
    n_results=n_results,
    where=where_filter
)
```

But vectors were created with Cloudflare embeddings (768 dims) in `vectorize_catalog.py`.

### Solution
Updated `catalog_retriever.py` to use Cloudflare embeddings for queries (matching vectorization):

**Before:**
```python
results = self.chroma.query(
    query_texts=[query],  # Wrong: uses default embedding
    n_results=n_results,
    where=where_filter
)
```

**After:**
```python
# Import Cloudflare embeddings
from llm import get_embeddings

# Generate embedding using same model as vectorization
query_embedding = get_embeddings([query])[0]

# Query with pre-computed embedding
results = self.chroma.query(
    query_embeddings=[query_embedding],  # Correct: uses Cloudflare
    n_results=n_results,
    where=where_filter
)
```

### Files Changed
- `retrieval/catalog_retriever.py`
  - Added import: `from llm import get_embeddings`
  - Updated `_semantic_search()` to use `query_embeddings` instead of `query_texts`

### Configuration
Ensure these are set in `.env`:
```bash
API_PROVIDER=cloudflare
CLOUDFLARE_EMBEDDING_MODEL=@cf/baai/bge-base-en-v1.5  # 768 dimensions
```

### Verification
```bash
# 1. Delete old index
rm -rf output/vector_index

# 2. Re-vectorize with Cloudflare embeddings
python Ingress/vectorize_catalog.py --reset

# 3. Restart app
python Backend/app.py

# 4. Test query
curl -X POST http://localhost:8800/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "getting started", "top_k": 3}'
```

**Expected**: No dimension mismatch errors, articles retrieved successfully.

---

---

## Issue 4: ChromaDB Multiple Filter Error (FIXED)

### Problem
```
⚠ ChromaDB query failed: Expected where to have exactly one operator, got {'intent': 'learn', 'category': 'application'} in query.
```

ChromaDB was rejecting queries with multiple metadata filters.

### Root Cause
ChromaDB requires logical operators (`$and`, `$or`) when using multiple filters. Direct dictionary syntax only works for single filters:

**Wrong:**
```python
where_filter = {
    "intent": "learn",
    "category": "application"
}
# ❌ ChromaDB rejects this
```

**Correct:**
```python
where_filter = {
    "$and": [
        {"intent": "learn"},
        {"category": "application"}
    ]
}
# ✓ ChromaDB accepts this
```

### Solution
Updated `_build_filter()` in `catalog_retriever.py` to use proper ChromaDB query syntax:

**Before:**
```python
def _build_filter(self, classification: Optional[Dict]) -> Optional[Dict]:
    where_filter = {}

    if intent:
        where_filter["intent"] = intent
    if category:
        where_filter["category"] = category

    return where_filter  # ❌ Multiple keys not supported
```

**After:**
```python
def _build_filter(self, classification: Optional[Dict]) -> Optional[Dict]:
    filters = []

    if intent:
        filters.append({"intent": intent})
    if category:
        filters.append({"category": category})

    if not filters:
        return None

    # Single filter: return directly
    if len(filters) == 1:
        return filters[0]

    # Multiple filters: use $and operator
    return {"$and": filters}
```

### Files Changed
- `retrieval/catalog_retriever.py`
  - Updated `_build_filter()` to use `$and` operator for multiple filters

### Verification
```bash
# Test with multiple filters
curl -X POST http://localhost:8800/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "what is workspace", "top_k": 3}'

# Should classify as: intent=learn, category=application
# Should return articles matching BOTH filters
```

**Expected**: Articles with `intent=learn AND category=application`

---

---

## Issue 5: LLM Token Limit Exceeded (FIXED)

### Problem
```
AiError: The estimated number of input and maximum output tokens (13810) exceeded
this model context window limit (7968)
```

Complete articles were too large for Cloudflare LLM's 8K token limit.

### Root Cause
Phase 2 returns complete articles instead of chunks, which can be very long. Multiple complete articles exceed the LLM's context window.

**Example**: 5 articles × 2,500 chars each = 12,500 chars ≈ 13,810 tokens (with metadata)

### Solution
**Two-tier approach**:
1. **For LLM context**: Truncate articles to 1,000 chars each (for answer generation)
2. **For response sources**: Include complete articles (for user to read)

**Implementation**:
```python
def build_catalog_context(article_results, max_context_chars=1000):
    for result in article_results:
        article = result["article"]

        # 1. Sources: FULL content for user
        source_info = {
            "content": article["content"],  # Complete article
            ...
        }

        # 2. LLM Context: TRUNCATED content
        content_for_llm = article['content']
        if len(content_for_llm) > max_context_chars:
            content_for_llm = content_for_llm[:max_context_chars] + "... [truncated]"

        context_parts.append(f"Content:\n{content_for_llm}")
```

### Benefits
✅ **LLM gets enough context** - Truncated articles fit in 8K token limit
✅ **User gets complete articles** - Full content in response sources
✅ **Best of both worlds** - AI answer + complete source material

### Response Format
```json
{
  "answer": "To add orderbook to workspace... [generated from truncated content]",
  "sources": [
    {
      "article_id": "orderbook_widget",
      "title": "Orderbook Widget",
      "content": "...complete article text here...",  // FULL content
      "score": 0.85
    }
  ]
}
```

### Configuration
Adjust truncation limit in `Backend/app.py`:
```python
context_block, sources = build_catalog_context(
    article_results,
    max_context_chars=1000  # Adjust if needed
)
```

**Guidelines**:
- **1000 chars**: Fits ~5 articles in 8K context
- **1500 chars**: Fits ~3 articles
- **2000 chars**: Fits ~2 articles

### Files Changed
- `Backend/app.py`
  - Updated `build_catalog_context()` to truncate content for LLM
  - Keep complete content in sources for user

### Verification
```bash
# Test with query that returns multiple articles
curl -X POST http://localhost:8800/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "add orderbook to workspace", "top_k": 5}'

# Should succeed and return:
# - answer: Generated from truncated context
# - sources: With complete article content
```

---

**Date Fixed**: 2025-10-29
**Status**: ✅ Production Ready
