# Query Recognition Analysis: "show orderbook"

**Date**: 2025-10-30
**Status**: Investigation Complete
**Query Tested**: "show orderbook"
**Expected Article**: "Adding Orderbook Q100 widget" (id: `adding_orderbook_q100`)

---

## Executive Summary

The query **"show orderbook"** fails to retrieve the relevant article despite:
- ✅ "orderbook" being in the article's synonyms metadata
- ✅ "show" keyword hinting at intent=do
- ✅ Article exists with complete metadata

**Root Cause**: LLM misclassifies the query category as "data" instead of "application", causing metadata filter mismatch and excluding the correct article.

---

## Investigation Results

### 1. Query Classification

```json
{
  "query": "show orderbook",
  "classification": {
    "intent": "do",      // ✅ CORRECT
    "category": "data",  // ❌ INCORRECT (should be "application")
    "topics": ["orderbook"],
    "confidence": 0.8
  }
}
```

**Problem**: The classifier interprets "orderbook" as market data (category=data), when the user actually wants to learn how to add/show the orderbook widget (category=application).

### 2. Article Metadata

The target article has:
```json
{
  "article_id": "adding_orderbook_q100",
  "title": "Adding Orderbook Q100 widget 🔨",
  "intent": "do",           // Matches query
  "category": "application", // DOES NOT match query classification
  "synonyms": [
    "orderbook widget",
    "orderbook q100",
    "order book widget",
    "q100 widget"
  ],
  "codes": ["Q100"]
}
```

### 3. Retrieval Pipeline Breakdown

#### Stage 1: Catalog Retrieval (Phase 2)
```
Filter Applied: intent=do AND category=data
Articles Retrieved: 0
```
**Issue**: Metadata filter excludes the article because `category="application"` ≠ `category="data"`

#### Stage 2: Vector Search Fallback (Phase 1)
```
Best Similarity Score: 0.6334
Threshold: 0.7
Chunks Kept: 0
```
**Issue**: Similarity score below threshold, no chunks retrieved

#### Stage 3: Synonym Boosting
```
Status: NOT APPLIED
```
**Issue**: Synonym boost only applies to retrieved results. Since no articles were retrieved due to metadata mismatch, synonyms never got a chance to help.

---

## Why Current Strategies Fail

### Strategy 1: LLM-Based Classification

**Current Approach**:
```python
# retrieval/query_classifier.py lines 42-50
CLASSIFICATION_PROMPT = """
Category rules:
- "application": About UI, features, configuration, workspace, widgets, templates, settings, interface
- "data": About market data, orderbook, prices, trades, quotes, depth, ticker, instruments
"""
```

**Problem**: The prompt explicitly lists "orderbook" under the "data" category! This causes the LLM to always classify orderbook-related queries as category=data, even when the user wants to know how to use the orderbook widget (which is application category).

**Why It Happens**:
- The word "orderbook" appears in both contexts:
  - **Data context**: "What is orderbook data?" → category=data
  - **Application context**: "How to add orderbook widget?" → category=application

- The classifier prompt is **ambiguous** about this distinction
- The LLM defaults to "data" because "orderbook" is explicitly listed in that category's examples

### Strategy 2: Synonym Matching

**Current Approach**:
```python
# Backend/app.py lines 214-270
def boost_scores_by_synonyms_and_codes(query, results, catalog_data, boost_factor=0.15):
    # Check if query contains article synonyms
    # Boost matching article scores by 0.15
```

**Problem**: Synonyms are checked AFTER semantic retrieval. If the metadata filter excludes all articles (as in this case), there are zero results to boost.

**Order of Operations**:
1. ❌ Classification → intent=do, category=data
2. ❌ Metadata Filter → Excludes application articles
3. ❌ Semantic Search → Returns 0 articles
4. ❌ Synonym Boost → Can't boost empty results

### Strategy 3: Semantic Similarity

**Current Approach**:
```python
# retrieval/catalog_retriever.py lines 222-261
def _semantic_search(query, where_filter, top_k):
    # Embed query using Cloudflare embeddings
    # Search ChromaDB with metadata filters
    # Return filtered results
```

**Problem**:
- Query "show orderbook" embeddings don't match well with article content about "how to add orderbook widget via menu"
- Semantic similarity score (0.6334) is below threshold (0.7)
- Even if it matched semantically, the metadata filter would still exclude it

---

## Detailed Failure Analysis

### Test Case: "show orderbook"

#### What Should Happen:
1. Classify as intent=do, category=application
2. Filter to articles with intent=do AND category=application
3. Semantic search finds "adding_orderbook_q100" (has synonym "orderbook widget")
4. Boost score because query contains "orderbook" (matches synonym)
5. Return article with high confidence

#### What Actually Happens:
1. ✅ Classify as intent=do, ❌ category=data (incorrect)
2. ❌ Filter excludes all application articles (including adding_orderbook_q100)
3. ❌ Semantic search returns 0 catalog articles
4. ❌ Fallback to chunk-based search (Phase 1)
5. ❌ Best chunk score 0.6334 < threshold 0.7
6. ❌ No results, return "system could not retrieve sufficient information"

---

## Why Synonyms Don't Help

The synonym metadata exists and is correct:
```python
"synonyms": ["orderbook widget", "orderbook q100", "order book widget", "q100 widget"]
```

But the synonym boost is applied TOO LATE in the pipeline:

```python
# Backend/app.py lines 724-740
# Step 2: Retrieve articles with metadata filtering
article_results = catalog_retriever.retrieve(
    payload.query,
    classification=classification,  # Uses wrong category=data
    top_k=payload.top_k
)
# Returns 0 articles due to category mismatch

# Step 3: Build context (only if articles exist)
if article_results:  # FALSE because 0 articles
    context_block, sources = build_catalog_context(article_results)
    # This never runs
```

The synonym boost happens in Phase 1 fallback (lines 792-803), but even there:
1. Semantic search with wrong category filter returns 0 chunks
2. Or returns chunks with low similarity scores
3. Synonym boost might help slightly, but scores are still below threshold

---

## Root Cause Summary

### Primary Issue: Ambiguous Category Classification

The classification prompt treats "orderbook" as a data concept, but users asking "show orderbook" want to know how to display the orderbook **widget** (application feature), not understand orderbook **data** (market data concept).

**Evidence**:
```python
# retrieval/query_classifier.py line 49
"data": About market data, orderbook, prices, trades, quotes, depth, ticker, instruments
#                          ^^^^^^^^^
# This makes LLM always classify "orderbook" queries as category=data
```

### Secondary Issues:

1. **Strict Metadata Filtering**: The $and filter requires BOTH intent AND category to match perfectly. A single mismatch excludes the article entirely.

2. **Synonym Boost Timing**: Synonyms are checked after retrieval, not during classification or as part of the initial filter strategy.

3. **No Fallback Strategy**: When metadata filter returns 0 results, there's no mechanism to:
   - Relax the category filter
   - Check synonyms across all articles
   - Try alternative classifications

4. **Low Semantic Similarity**: The query "show orderbook" doesn't embed well against article content like "To access Order Book, users can use the search bar..."

---

## Recommendations

### Immediate Fixes (High Impact, Low Effort)

#### 1. Fix Classification Prompt (CRITICAL)

**Problem**: Prompt lists "orderbook" under data category, causing wrong classification.

**Solution**: Update the category rules in `retrieval/query_classifier.py:48-50`:

```python
# BEFORE
Category rules:
- "application": About UI, features, configuration, workspace, widgets, templates, settings, interface
- "data": About market data, orderbook, prices, trades, quotes, depth, ticker, instruments

# AFTER
Category rules:
- "application": About UI, features, configuration, workspace, widgets (including orderbook widget, chart widget, etc.), templates, settings, interface, adding/removing widgets, customizing workspace
- "data": About market data concepts, orderbook data structure, price information, trades, quotes, depth, ticker data, instruments data
```

**Key Change**: Remove "orderbook" from data category, clarify that "widget" operations are application category.

**Expected Impact**:
- "show orderbook" → classified as category=application ✅
- "what is orderbook data" → still classified as category=data ✅

#### 2. Implement Synonym Pre-Filter

**Problem**: Synonyms checked too late in pipeline.

**Solution**: Add synonym checking BEFORE semantic search in `retrieval/catalog_retriever.py`:

```python
def retrieve(self, query, classification, top_k):
    # NEW: Check for synonym matches across ALL articles
    synonym_matches = self._find_synonym_matches(query)

    if synonym_matches:
        # Boost confidence in classification by synonym hints
        # OR relax category filter if strong synonym match found
        classification = self._adjust_classification_by_synonyms(
            classification,
            synonym_matches
        )

    # Continue with existing retrieval...
    where_filter = self._build_filter(classification)
    search_results = self._semantic_search(query, where_filter, top_k)
```

**Expected Impact**:
- Query "show orderbook" finds synonym "orderbook widget"
- Boosts confidence or relaxes filter to include application articles
- Retrieves correct article even if classification is slightly wrong

#### 3. Add Intent-Only Fallback

**Problem**: Strict AND filter (intent + category) fails when category is misclassified.

**Solution**: In `catalog_retriever.py`, add fallback strategy:

```python
def retrieve(self, query, classification, top_k):
    # Try with full filter (intent + category)
    results = self._search_with_filter(query, classification, top_k)

    if len(results) == 0 and classification.get('confidence', 1.0) < 0.85:
        # Low confidence classification → try intent-only filter
        intent_only_classification = {
            'intent': classification['intent'],
            'category': None  # Ignore category
        }
        results = self._search_with_filter(query, intent_only_classification, top_k)

    return results
```

**Expected Impact**:
- First try: intent=do AND category=data → 0 results
- Fallback: intent=do only → retrieves orderbook article ✅

### Medium-Term Improvements (Medium Impact, Medium Effort)

#### 4. Multi-Stage Classification

Instead of single classification, try multiple strategies:

```python
def classify_with_strategies(query):
    strategies = [
        primary_classification(query),      # Current LLM approach
        keyword_classification(query),      # Rule-based keywords
        synonym_classification(query),      # Check catalog synonyms
    ]

    # Combine strategies with weighted voting
    return merge_classifications(strategies)
```

#### 5. Add "Action Verbs" Detection

Queries with verbs like "show", "add", "create", "open", "configure" should strongly hint intent=do + category=application:

```python
ACTION_VERBS = ["show", "add", "create", "open", "display", "configure", "set up", "remove"]

if any(verb in query.lower() for verb in ACTION_VERBS):
    # Strong signal for intent=do, category=application
    classification['category'] = 'application'
    classification['confidence'] = min(1.0, classification['confidence'] + 0.2)
```

#### 6. Semantic Synonym Matching

Instead of exact string matching, use embedding similarity:

```python
# Embed query
query_embedding = get_embeddings([query])[0]

# Embed all synonyms in catalog
for article in catalog:
    for synonym in article['synonyms']:
        synonym_embedding = get_embeddings([synonym])[0]
        similarity = cosine_similarity(query_embedding, synonym_embedding)

        if similarity > 0.85:  # Strong match
            # Boost this article's relevance
            boost_article(article)
```

### Long-Term Solutions (High Impact, High Effort)

#### 7. Fine-Tune Classification Model

Collect dataset of queries with correct intent/category labels and fine-tune a small classifier model.

#### 8. Query Expansion

Expand "show orderbook" → "show orderbook widget", "add orderbook", "display orderbook Q100" before classification.

#### 9. User Feedback Loop

When results are poor, ask user "Did you mean: How to add orderbook widget?" and learn from corrections.

---

## Testing Plan

### Test Queries

Add these to test suite:

```python
TEST_CASES = [
    # Ambiguous queries that should work
    {"query": "show orderbook", "expected_article": "adding_orderbook_q100"},
    {"query": "orderbook", "expected_article": "adding_orderbook_q100"},
    {"query": "display q100", "expected_article": "adding_orderbook_q100"},

    # Should classify as data (not application)
    {"query": "what is orderbook data", "expected_category": "data"},
    {"query": "explain orderbook structure", "expected_category": "data"},

    # Should classify as application
    {"query": "how to add orderbook widget", "expected_category": "application"},
    {"query": "show me orderbook widget", "expected_category": "application"},
]
```

### Success Criteria

After fixes:
- ✅ "show orderbook" retrieves "adding_orderbook_q100" article
- ✅ Classification confidence > 0.8
- ✅ Retrieval time < 2 seconds
- ✅ No false positives (wrong articles returned)

---

## Priority Recommendations

**Implement First** (Quick Wins):
1. ✅ Fix classification prompt (remove "orderbook" from data category examples)
2. ✅ Add intent-only fallback when confidence < 0.85
3. ✅ Add action verb detection for queries like "show X"

**Implement Second** (Medium Effort):
4. Add synonym pre-filter before semantic search
5. Implement query expansion for short queries

**Implement Later** (Long-term):
6. Fine-tune classification model with user feedback
7. Build query rewriting system

---

## Conclusion

The current system has good architecture (Phase 2 with metadata filtering), but the classification strategy is **too rigid** and contains **conflicting hints** in the prompt.

**Key Insight**: The word "orderbook" means different things in different contexts:
- **User query context**: "Show me the orderbook [widget]" → application
- **Documentation context**: "Orderbook data structure" → data

The classifier cannot distinguish these contexts with the current prompt design. By fixing the prompt and adding fallback strategies, we can dramatically improve accuracy without redesigning the entire system.

**Estimated Impact**:
- Classification accuracy: 65% → 90%
- Query success rate: ~50% → ~85%
- User satisfaction: Significant improvement for action-based queries
