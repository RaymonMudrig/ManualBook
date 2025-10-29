# Phase 2: Integration Plan

## Overview

Integrate the catalog system with vectorization and query pipeline to enable:
1. **Vectorize complete articles** (not arbitrary chunks)
2. **Classify user queries** by intent and category
3. **Retrieve complete articles** with relationships
4. **Filter by metadata** before semantic search
5. **Build rich context** with related articles

---

## Current State vs. Target State

### Current System (Phase 1)

```
Source MD → build_catalog.py → {
    catalog/articles/*.md
    catalog/catalog.json
    catalog/relationships.json
}

(Separate) MD → parse_md.py → chunks → vectorize.py → ChromaDB → app.py
```

**Problem:** Catalog and vectorization are disconnected!

### Target System (Phase 2)

```
Source MD → build_catalog.py → Catalog

Catalog → vectorize_catalog.py → {
    ChromaDB (with article_id metadata)
    + Catalog (for complete article retrieval)
}

User Query → app.py → {
    1. Classify query (intent, category)
    2. Search ChromaDB (with metadata filter)
    3. Lookup complete articles from catalog
    4. Add related articles
    5. Generate answer with full context
}
```

---

## Phase 2 Components

### 1. Update Vectorization ✅

**File:** `Ingress/vectorize_catalog.py` (new)

**What it does:**
- Read articles from catalog (not raw markdown)
- Chunk articles if needed (by paragraph or section)
- Store article_id in chunk metadata
- Enable retrieval by article_id

**Chunk metadata:**
```python
{
    "article_id": "workspace_setup",
    "intent": "do",
    "category": "application",
    "chunk_index": 0,
    "parent_id": "application_basics",
    "has_children": true
}
```

**Benefits:**
- Link chunks back to complete articles
- Filter by intent/category before semantic search
- Enable article-level retrieval

### 2. Query Classifier ✅

**File:** `retrieval/query_classifier.py` (new)

**What it does:**
- Classify user query intent (do/learn/trouble)
- Extract mentioned categories (application/data)
- Identify key topics
- Use Cloudflare LLM

**Example:**
```python
query = "How do I set up my workspace?"

classifier.classify(query)
# Returns:
{
    "intent": "do",           # "How do I" → intent=do
    "category": "application", # "workspace" → category=application
    "topics": ["workspace", "setup", "configuration"]
}
```

**Benefits:**
- Filter search results before retrieval
- Route to appropriate retrieval strategy
- Improve accuracy by reducing search space

### 3. Catalog Retriever ✅

**File:** `retrieval/catalog_retriever.py` (new)

**What it does:**
- Combine semantic search + metadata filtering
- Retrieve complete articles (not chunks)
- Add related articles automatically
- Build comprehensive context

**Flow:**
```python
1. Query: "How do I customize workspace?"
2. Classify: intent=do, category=application
3. Search ChromaDB with filter:
   WHERE intent='do' AND category='application'
4. Get article_ids from top results
5. Load complete articles from catalog
6. Add related articles (parent, children, see-also)
7. Return rich context
```

**Benefits:**
- Complete articles, not fragments
- Relationship-aware context
- Better answer quality

### 4. Update Backend (app.py) ✅

**File:** `Backend/app.py` (update)

**Changes:**
- Add query classification endpoint
- Use catalog retriever instead of chunk retrieval
- Display complete articles with relationships
- Show article metadata in UI

**New response format:**
```json
{
    "answer": "To customize your workspace...",
    "sources": [
        {
            "article_id": "workspace_setup",
            "title": "Setting Up Workspace",
            "intent": "do",
            "category": "application",
            "content": "...",
            "images": ["images/workspace.png"],
            "parent": {"id": "application_basics", "title": "..."},
            "see_also": [
                {"id": "widget_management", "title": "..."}
            ]
        }
    ]
}
```

---

## Implementation Order

### Step 1: Vectorize Catalog Articles (Week 1)

**Tasks:**
- [x] Create `vectorize_catalog.py`
- [ ] Read articles from catalog
- [ ] Chunk articles intelligently (by paragraph)
- [ ] Store article_id + metadata in ChromaDB
- [ ] Test vectorization

**Output:**
- ChromaDB with catalog-linked vectors
- Metadata filters enabled

### Step 2: Query Classification (Week 1-2)

**Tasks:**
- [ ] Create `query_classifier.py`
- [ ] Implement Cloudflare LLM classification
- [ ] Extract intent + category
- [ ] Test classification accuracy

**Output:**
- Query classifier service
- Classification examples

### Step 3: Catalog Retriever (Week 2)

**Tasks:**
- [ ] Create `catalog_retriever.py`
- [ ] Implement hybrid search (semantic + metadata)
- [ ] Add article lookup from catalog
- [ ] Add related article expansion
- [ ] Test retrieval quality

**Output:**
- Complete article retrieval
- Relationship-aware context

### Step 4: Backend Integration (Week 2-3)

**Tasks:**
- [ ] Update `app.py`
- [ ] Add query classification
- [ ] Use catalog retriever
- [ ] Update response format
- [ ] Test end-to-end

**Output:**
- Integrated system
- Better answers with complete articles

---

## Technical Design Details

### Vectorize Catalog Articles

**Chunking strategy:**
```python
# Option 1: Whole article (if small)
if len(article.content) < 1000:
    chunk = article.content
    store_chunk(chunk, article_id, chunk_index=0)

# Option 2: Split by paragraphs
else:
    paragraphs = article.content.split('\n\n')
    for i, para in enumerate(paragraphs):
        if len(para) > 50:  # Skip tiny paragraphs
            store_chunk(para, article_id, chunk_index=i)
```

**Metadata schema:**
```python
chunk_metadata = {
    "article_id": str,        # Link back to catalog
    "intent": str,            # do/learn/trouble
    "category": str,          # application/data
    "chunk_index": int,       # Position in article
    "parent_id": str | None,  # Parent article
    "has_children": bool,     # Has child articles
    "see_also_ids": list[str], # Related articles
}
```

### Query Classifier

**Cloudflare LLM prompt:**
```python
CLASSIFICATION_PROMPT = """
You are a technical documentation query classifier.

Query: "{query}"

Classify this query and return JSON:
{{
    "intent": "do" | "learn" | "trouble",
    "category": "application" | "data" | "unknown",
    "topics": ["topic1", "topic2", ...],
    "confidence": 0.0-1.0
}}

Intent rules:
- "do": User wants step-by-step instructions (how to, guide, tutorial)
- "learn": User wants to understand concepts (what is, explain, definition)
- "trouble": User has a problem to solve (error, not working, issue)

Category rules:
- "application": About UI, features, configuration, workspace, widgets
- "data": About market data, orderbook, prices, trades
- "unknown": Cannot determine

Return ONLY valid JSON.
"""
```

**Implementation:**
```python
class QueryClassifier:
    def __init__(self, llm_service):
        self.llm = llm_service

    def classify(self, query: str) -> Dict:
        prompt = CLASSIFICATION_PROMPT.format(query=query)
        response = self.llm.get_completion(
            prompt,
            temperature=0.1,  # Low temp for consistent classification
            max_tokens=200
        )
        return json.loads(response)
```

### Catalog Retriever

**Hybrid retrieval strategy:**
```python
class CatalogRetriever:
    def __init__(self, chroma_collection, catalog_builder):
        self.chroma = chroma_collection
        self.catalog = catalog_builder

    def retrieve(self, query: str, classification: Dict, top_k: int = 3):
        # 1. Build metadata filter from classification
        where_filter = {}
        if classification['intent'] != 'unknown':
            where_filter['intent'] = classification['intent']
        if classification['category'] != 'unknown':
            where_filter['category'] = classification['category']

        # 2. Semantic search with metadata filter
        results = self.chroma.query(
            query_texts=[query],
            n_results=top_k * 2,  # Get more, then dedupe by article_id
            where=where_filter if where_filter else None
        )

        # 3. Get unique article IDs
        article_ids = set()
        for metadata in results['metadatas'][0]:
            article_ids.add(metadata['article_id'])

        # 4. Load complete articles from catalog
        articles = []
        for article_id in list(article_ids)[:top_k]:
            article = self.catalog.get_article(article_id)
            related = self.catalog.get_related_articles(article_id)
            articles.append({
                'article': article,
                'related': related
            })

        return articles
```

---

## Testing Strategy

### Unit Tests

1. **Vectorize Catalog:**
   - Read articles from catalog ✓
   - Chunk articles correctly ✓
   - Store metadata properly ✓

2. **Query Classifier:**
   - Classify "do" queries ✓
   - Classify "learn" queries ✓
   - Classify "trouble" queries ✓
   - Extract categories ✓

3. **Catalog Retriever:**
   - Metadata filtering works ✓
   - Article deduplication ✓
   - Related articles added ✓

### Integration Tests

1. **End-to-End:**
   - Query → Classify → Retrieve → Answer ✓
   - Complete articles returned ✓
   - Related articles included ✓
   - Images preserved ✓

### Quality Tests

1. **Answer Quality:**
   - Compare Phase 1 vs Phase 2 answers
   - Measure completeness
   - Measure accuracy
   - User satisfaction

---

## Success Metrics

After Phase 2, we should see:

✅ **Completeness:**
- Answers include full article content (not fragments)
- Related articles automatically included

✅ **Accuracy:**
- Query classification filters irrelevant results
- Metadata filtering reduces noise

✅ **Context:**
- Parent-child relationships preserved
- See-also references available
- Images and code samples included

✅ **Performance:**
- Faster retrieval (smaller search space with filters)
- Better relevance (metadata + semantic)

---

## Timeline

| Week | Tasks | Deliverable |
|------|-------|-------------|
| 1 | Vectorize catalog, Query classifier | ChromaDB with catalog links |
| 2 | Catalog retriever, Backend updates | Working integration |
| 3 | Testing, refinement, documentation | Production-ready Phase 2 |

**Estimated: 2-3 weeks**

---

## Ready to Start?

**Option 1:** Start with vectorize_catalog.py (most critical)
**Option 2:** Start with query_classifier.py (enables filtering)
**Option 3:** Do both in parallel (faster, but more complex)

**Which would you prefer?**
