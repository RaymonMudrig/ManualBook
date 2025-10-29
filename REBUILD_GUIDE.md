# Complete Rebuild Guide

## 🔄 Full Rebuild Process (Use --reset for both)

When you need to rebuild everything from scratch:

```bash
# 1. Build articles + catalog + copy images
.venv/bin/python3 Ingress/build_catalog.py --reset

# 2. Build vector index
.venv/bin/python3 Ingress/vectorize_catalog.py --reset --batch-size 8

# 3. Restart app
lsof -ti:8800 | xargs kill -9 2>/dev/null || true
.venv/bin/python3 Backend/app.py
```

## 📋 What Each Step Does

### Step 1: Build Catalog (with --reset)
**Command**: `build_catalog.py --reset`

**Removes**:
- `output/catalog/articles/` (all article .md files)
- `output/catalog/articles/*_images/` (all image directories)
- `output/catalog/catalog.json`
- `output/catalog/relationships.json`

**Creates**:
- Individual article `.md` files in `output/catalog/articles/`
- Copies image directories (e.g., `IDX_Terminal_images/`) to `output/catalog/articles/`
- `catalog.json` - Article index with metadata
- `relationships.json` - Article relationship graph

**Input**: `md/*.md` files
**Output**: File-based catalog with articles and images

---

### Step 2: Vectorize Catalog (with --reset)
**Command**: `vectorize_catalog.py --reset --batch-size 8`

**Removes**:
- ChromaDB collection `manual_chunks`

**Creates**:
- Vector embeddings for all article chunks
- Stores in ChromaDB collection `manual_chunks`
- Includes metadata filters (intent, category)

**Input**: `output/catalog/` directory
**Output**: `output/vector_index/` with ChromaDB database

---

### Step 3: Restart App
**Command**: `Backend/app.py`

**Loads**:
- ChromaDB collection from `output/vector_index/`
- Catalog data from `output/catalog/`
- Serves images from `/articles/` route

**Endpoints**:
- `http://localhost:8800/` - Web UI
- `http://localhost:8800/api/query` - Query API
- `http://localhost:8800/articles/` - Static images

---

## 🎯 Key Changes from Previous Version

| Feature | Old | New |
|---------|-----|-----|
| **Catalog flag** | `--clean` | `--reset` ✅ |
| **Vector flag** | `--reset` | `--reset` ✅ |
| **Image copying** | Manual | **Automatic** ✅ |
| **Image location** | `output/images/` | `output/catalog/articles/` ✅ |
| **Image serving** | `/images/` | `/articles/` ✅ |

---

## ✅ Consistency Benefits

1. **Same flag everywhere**: `--reset` for both build_catalog and vectorize_catalog
2. **Images auto-copied**: No manual copying needed
3. **Clean slate**: All old data removed before rebuild
4. **Self-contained catalog**: Articles + images in one directory

---

## 📂 Directory Structure After Rebuild

```
output/
├── catalog/
│   ├── articles/
│   │   ├── adding_orderbook_q100.md
│   │   ├── adding_widget_command.md
│   │   ├── ...
│   │   └── IDX_Terminal_images/
│   │       ├── IDX_Terminal_img_31.png
│   │       ├── IDX_Terminal_img_32.png
│   │       └── ...
│   ├── catalog.json
│   └── relationships.json
└── vector_index/
    └── chroma.sqlite3
```

---

## 🔧 Troubleshooting

### Images not showing in browser?
1. Check if images were copied: `ls output/catalog/articles/IDX_Terminal_images/`
2. Check if backend is serving: `curl -I http://localhost:8800/articles/IDX_Terminal_images/IDX_Terminal_img_31.png`
3. Expected result: `200 OK`

### Old data still appearing?
- Make sure you used `--reset` flag for both steps
- Verify directories were cleaned: `ls output/catalog/articles/`

### Vector search not working?
- Rebuild with `--reset` to ensure fresh embeddings
- Check ChromaDB collection: Should have 150+ vectors for 43 articles

---

## 📊 Expected Output

### Step 1: Build Catalog
```
======================================================================
Article Catalog Builder
======================================================================
Input: 1 markdown file(s)
Output: /path/to/output/catalog
======================================================================

Processing: IDX_Terminal.md
  ✓ Extracted 43 articles
  ✓ Copied images: IDX_Terminal_images/

======================================================================
CATALOG BUILD COMPLETE
======================================================================
  Files processed: 1
  Files failed: 0
  Total articles: 43
```

### Step 2: Vectorize
```
======================================================================
Catalog Vectorization
======================================================================
Progress: [43/43] 100.0% | Articles: 43 | Chunks: 152

======================================================================
VECTORIZATION COMPLETE
======================================================================
  Total articles: 43
  Total chunks: 152
  Total time: 180s (3 min)
```

### Step 3: App Start
```
✓ Loaded environment from .env
✓ Catalog system initialized (Phase 2 mode)
INFO: Uvicorn running on http://0.0.0.0:8800
```

---

## 🚀 Quick Test After Rebuild

```bash
# Test query with images
curl -X POST http://localhost:8800/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "how to add intraday chart", "top_k": 1}'

# Expected result:
# - mode: "catalog_rag"
# - sources: 1 article with full content and images
# - answer: Generated from truncated context

# Test image serving
curl -I http://localhost:8800/articles/IDX_Terminal_images/IDX_Terminal_img_31.png

# Expected result:
# HTTP/1.1 200 OK
```

---

## 📝 Notes

- **Always use --reset** when rebuilding to ensure data consistency
- **Images are auto-copied** during catalog build
- **No manual steps** required for image management
- **All-in-one catalog** directory contains both articles and images
