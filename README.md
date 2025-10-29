# ManualBook - Semantic Document Query System

A comprehensive RAG (Retrieval-Augmented Generation) system that converts Word documents into searchable, semantically queryable knowledge bases with intelligent web search fallback.

## Features

- **Document Conversion**: Convert `.docx` files to Markdown with automatic image extraction
- **Translation**: Translate documents to English using Google Translate (line-by-line, preserves all formatting) ⭐ **NEW**
- **Semantic Chunking**: Intelligently chunk by heading structure, preserving complete sections
- **Heading Hierarchy**: Full document structure preserved with parent-child relationships
- **Vector Search**: ChromaDB-powered semantic search with configurable similarity thresholds
- **Agentic RAG**: Intelligent fallback to web search when local knowledge is insufficient
- **Web Interface**: Clean FastAPI-based web UI for querying documents
- **Image Support**: Preserves and serves embedded images from original documents

## Architecture

```
Pipeline Flow:
.docx files → docx_to_md.py → rename → translate_md.py → parse_md.py → vectorize.py → app.py (Web UI)
     ↓              ↓            ↓      (Google Translate)      ↓              ↓           ↓
   docx/         md/*.md    md/*.mdx    md/*.md       output/chunks/  vector_index/   http://localhost:8800
                         (original)  (English)
```

**File Naming Convention:**
- `*.docx` - Source Word documents
- `*.mdx` - Original language Markdown (preserved after conversion)
- `*.md` - English translated Markdown (used by pipeline)
- `*.jsonl` - Chunked data ready for vectorization

**Translation:**
- Uses `google/translate_service.py` for reliable, line-by-line translation
- Preserves all markdown syntax: tables, code blocks, images, lists
- No content loss or merging issues
- Requires `deep-translator` package

## Prerequisites

- Python 3.9+
- **One of the following LLM providers:**
  - **Option A: Local LLM Server** (LM Studio, Ollama, vLLM)
    - Free, runs on your machine
    - Requires GPU for good performance
    - Example: LM Studio running on `http://localhost:1234`
  - **Option B: Cloudflare AI Workers** (Recommended for cloud deployment)
    - Cloud-based, serverless
    - Pay-as-you-go pricing (very affordable)
    - No local GPU needed
    - Requires Cloudflare account and API token

## Installation

1. Clone the repository:
```bash
git clone <your-repo>
cd ManualBook
```

2. Install dependencies:
```bash
# Install all dependencies (recommended)
pip install -r requirements.txt

# Or install manually:
# Core dependencies
pip install python-docx requests chromadb python-dotenv

# Translation
pip install deep-translator

# Backend/Web UI
pip install fastapi uvicorn pydantic
```

3. Set up directory structure:
```bash
mkdir -p docx md output/{chunks,images,vector_index}
```

4. Configure your LLM provider (see Configuration section below)

## LLM Provider Setup

### Option A: Local LLM Server (LM Studio)

1. Download and install [LM Studio](https://lmstudio.ai/)
2. Download models:
   - Embedding: `nomic-ai/nomic-embed-text-v1.5-GGUF`
   - LLM: `qwen2.5-32b-instruct` (or any chat model)
3. Start the local server in LM Studio (default port: 1234)
4. Set environment variables:
```bash
export API_PROVIDER=openai
export EMBEDDING_API_BASE=http://localhost:1234/v1
export EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
export LLM_MODEL=qwen2.5-32b-instruct-mlx
```

### Option B: Cloudflare AI Workers (Recommended)

1. **Create Cloudflare Account**
   - Sign up at [cloudflare.com](https://dash.cloudflare.com/sign-up)
   - Free tier includes generous AI Workers usage

2. **Get Your Account ID**
   - Log in to [Cloudflare Dashboard](https://dash.cloudflare.com/)
   - Go to Workers & Pages
   - Your Account ID is shown in the right sidebar
   - Or find it in the URL: `https://dash.cloudflare.com/{ACCOUNT_ID}/...`

3. **Create API Token**
   - Go to [API Tokens](https://dash.cloudflare.com/profile/api-tokens)
   - Click "Create Token"
   - Use template: "Edit Cloudflare Workers" OR create custom token
   - Required permissions:
     - Account > Workers AI > Read
   - Copy the token (you won't see it again!)

4. **Set Environment Variables**
```bash
export API_PROVIDER=cloudflare
export CLOUDFLARE_ACCOUNT_ID=your_account_id_here
export CLOUDFLARE_API_TOKEN=your_api_token_here
export CLOUDFLARE_EMBEDDING_MODEL=@cf/baai/bge-base-en-v1.5
export CLOUDFLARE_LLM_MODEL=@cf/meta/llama-3.1-8b-instruct
```

5. **Test Connection**
```bash
python llm/service.py
```

**Available Cloudflare Models:**
- Embeddings:
  - `@cf/baai/bge-base-en-v1.5` (768 dim, balanced, **recommended**)
  - `@cf/baai/bge-small-en-v1.5` (384 dim, faster, smaller)
  - `@cf/baai/bge-large-en-v1.5` (1024 dim, highest quality)
- Text Generation:
  - `@cf/meta/llama-3.1-8b-instruct` (fast, **recommended**)
  - `@cf/meta/llama-3.1-70b-instruct` (slower, higher quality)
  - `@cf/qwen/qwen1.5-14b-chat-awq` (multilingual)
  - `@cf/mistral/mistral-7b-instruct-v0.1` (fast alternative)

See [Cloudflare AI Models Catalog](https://developers.cloudflare.com/workers-ai/models/) for full list.

### Option C: Other Providers (Ollama, vLLM, OpenAI)

<details>
<summary>Click to expand Ollama setup</summary>

1. Install [Ollama](https://ollama.ai/)
2. Pull models:
```bash
ollama pull nomic-embed-text
ollama pull llama3.1:8b
```
3. Set environment variables:
```bash
export API_PROVIDER=openai
export EMBEDDING_API_BASE=http://localhost:11434/v1
export EMBEDDING_MODEL=nomic-embed-text
export LLM_MODEL=llama3.1:8b
```
</details>

<details>
<summary>Click to expand OpenAI setup</summary>

1. Get API key from [OpenAI Platform](https://platform.openai.com/api-keys)
2. Set environment variables:
```bash
export API_PROVIDER=openai
export EMBEDDING_API_BASE=https://api.openai.com/v1
export EMBEDDING_API_KEY=sk-...your-key...
export EMBEDDING_MODEL=text-embedding-3-small
export LLM_MODEL=gpt-4o-mini
```
</details>

## Usage

### Full Pipeline (Automated)

Run the complete pipeline with one command:
```bash
python run_pipeline.py
```

### Step-by-Step Usage

#### 1. Convert DOCX to Markdown
Place your `.docx` files in the `docx/` directory, then:
```bash
python Ingress/docx_to_md.py
```
Output: `md/*.md` files with extracted images in `md/*_images/`

#### 2. Preserve Original Language
Rename `.md` to `.mdx` to preserve the original language:
```bash
# This happens automatically in run_pipeline.py
# Or manually:
mv md/YourFile.md md/YourFile.mdx
```

#### 3. Translate to English
```bash
python Ingress/translate_md.py --input md/YourFile.mdx --output md/YourFile.md
```

**Translation Options:**
```bash
# Auto-detect source language
python Ingress/translate_md.py --input file.mdx --output file.md --source auto

# Specify source language (Indonesian to English)
python Ingress/translate_md.py --input file.mdx --output file.md --source id --target en

# Other language codes: es (Spanish), fr (French), de (German), ja (Japanese), etc.
```

**How Translation Works:**
- Uses Google Translate via `google/translate_service.py`
- Line-by-line translation (no content merging or buffering)
- Preserves markdown syntax: tables, code blocks, images, lists
- Failed translations fall back to original text
- Progress indicator shows translated/failed/skipped lines

Output: English version as `md/YourFile.md`, original preserved as `md/YourFile.mdx`

#### 4. Parse and Chunk Markdown
```bash
python Ingress/parse_md.py
```
Output: `output/chunks/*.jsonl` (one JSON object per line)

#### 5. Vectorize and Index
```bash
python Ingress/vectorize.py --reset
```
Options:
- `--reset`: Clear existing index before indexing
- `--batch-size N`: Number of chunks to embed per batch (default: 8)
- `--collection NAME`: ChromaDB collection name (default: manual_chunks)

#### 6. Start Web Server
```bash
cd Backend
python app.py
```
Access at: `http://localhost:8800`

## Configuration

### Environment Variables

All configuration is done via environment variables. Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
# Edit .env with your values
nano .env  # or use your preferred editor
```

**Key Configuration Options:**

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `API_PROVIDER` | LLM provider: `openai` or `cloudflare` | `openai` | ✅ |
| `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare account ID | - | If using Cloudflare |
| `CLOUDFLARE_API_TOKEN` | Your Cloudflare API token | - | If using Cloudflare |
| `EMBEDDING_API_BASE` | OpenAI-compatible API URL | `http://localhost:1234/v1` | If using local |
| `SIMILARITY_THRESHOLD` | RAG threshold (0.0-1.0) | `0.7` | ❌ |
| `SERPER_API_KEY` | Web search API key (optional) | - | ❌ |
| `CORS_ORIGINS` | Allowed CORS origins | `*` | ❌ |

See `.env.example` for all available options and detailed examples.

### Similarity Threshold Guide

- **0.9+**: Very strict - only near-exact matches
- **0.7-0.8**: Balanced - good for most use cases (recommended)
- **0.5-0.6**: Permissive - may return loosely related content
- **<0.5**: Very permissive - likely to return irrelevant results

## API Reference

### POST /api/query

Query the knowledge base with semantic search.

**Request:**
```json
{
  "query": "How do I reset the device?",
  "top_k": 5,
  "threshold": 0.7
}
```

**Response:**
```json
{
  "query": "How do I reset the device?",
  "answer": "To reset the device, press and hold...",
  "mode": "rag",  // or "web" or "hybrid"
  "sources": [
    {
      "id": "abc123",
      "title": "Device Settings / Reset Options",
      "score": 0.87,
      "source_kind": "markdown",
      "source_file": "User_Manual_v1.md"
    }
  ],
  "steps": [...]  // Processing steps for debugging
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "ok"
}
```

## Project Structure

```
ManualBook/
├── docx/                      # Source .docx files
├── md/                        # Markdown files
│   ├── *.mdx                 # Original language (preserved)
│   ├── *.md                  # English translated (used by pipeline)
│   └── *_images/             # Extracted images
├── output/
│   ├── chunks/               # Chunked JSON data
│   ├── images/               # Copied images for web serving
│   └── vector_index/         # ChromaDB database
├── llm/                      # Centralized LLM service
│   ├── __init__.py          # Package initialization
│   └── service.py           # LLM API abstraction layer
├── Ingress/                  # Pipeline scripts
│   ├── docx_to_md.py        # DOCX → Markdown converter
│   ├── translate_md.py      # Translation utility
│   ├── parse_md.py          # Markdown → Chunks
│   └── vectorize.py         # Chunks → Vector DB
├── Backend/
│   ├── app.py               # FastAPI web server
│   ├── requirements.txt     # Python dependencies
│   └── static/              # Web UI files
├── run_pipeline.py          # End-to-end automation script
├── .env.example             # Environment configuration template
└── README.md                # This file
```

## How It Works

### Architecture Overview

ManualBook uses a **centralized LLM service** (`llm/service.py`) that abstracts all AI operations. This design:
- ✅ Eliminates code duplication across modules
- ✅ Supports multiple LLM providers (local, cloud, OpenAI-compatible)
- ✅ Makes switching providers easy (just change `API_PROVIDER`)
- ✅ Provides consistent error handling and retry logic
- ✅ Simplifies testing and maintenance

All modules (Backend, Ingress) import from the central service:
```python
from llm import get_embeddings, get_completion, translate_text, get_gloss
```

### Document Processing

1. **DOCX Parsing**: Extracts text, tables, lists, and images from Word documents
2. **Markdown Conversion**: Converts to clean Markdown with preserved formatting (`.md`)
3. **Language Preservation**: Renames original `.md` to `.mdx` to preserve source language
4. **Translation**: Translates `.mdx` to English `.md` (via `llm.translate_text()`)
5. **Semantic Chunking**: Splits by heading structure (H1-H6), preserving complete sections
   - Maintains full heading hierarchy (e.g., "Manual > Chapter 2 > Section 2.1")
   - Intelligently splits large sections at paragraph boundaries
   - Max chunk size: 2000 tokens (configurable)
6. **Glossing**: Generates one-line summaries for each chunk (via `llm.get_gloss()`)
7. **Embedding**: Creates vector embeddings for semantic search (via `llm.get_embeddings()`)
8. **Indexing**: Stores in ChromaDB with full metadata (hierarchy, level, parent, children)

**Result**:
- Original language preserved as `.mdx`
- English `.md` chunked into complete, semantically meaningful sections
- Full document structure preserved for intelligent retrieval

**See [SEMANTIC_CHUNKING.md](SEMANTIC_CHUNKING.md) for detailed explanation**

### Query Processing (Agentic RAG)

1. **Embedding**: Convert user query to vector
2. **Vector Search**: Find top-k most similar chunks
3. **Threshold Filtering**: Keep only chunks above similarity threshold
4. **RAG Generation**: If good matches found, generate answer using LLM + context
5. **Web Fallback**: If no good matches, search the web for answers
6. **Hybrid Mode**: Combine local + web results when appropriate

## Troubleshooting

### "Missing dependency" errors
```bash
pip install -r Backend/requirements.txt
pip install python-docx requests chromadb
```

### "Unable to initialize vector collection"
Make sure ChromaDB is properly installed and the index directory exists:
```bash
pip install chromadb
mkdir -p output/vector_index
```

### Images not displaying
Check that:
1. Images directory is mounted (should happen automatically)
2. Image paths in chunks are correct (relative to `output/images/`)
3. Web server has read permissions on `output/images/`

### Low quality search results
Try:
1. Increasing `SIMILARITY_THRESHOLD` (e.g., from 0.7 to 0.8)
2. Reducing `top_k` to get only the best matches
3. Re-running vectorization with `--reset` flag
4. Using a better embedding model

### LLM connection errors
Ensure your local LLM server is running:
- Check `http://localhost:1234/v1/models`
- Verify the model names match your configuration
- Check firewall settings

## Performance Tips

1. **Batch Size**: Increase `--batch-size` for faster vectorization (if your LLM supports it)
2. **Caching**: The system will cache image copies and embeddings
3. **Hardware**: Use GPU acceleration for embedding models if available
4. **Chunking**: Adjust chunk size in `parse_md.py` (line 42) for different document types

## Security Considerations

- **CORS**: Set `CORS_ORIGINS` to specific domains in production
- **Input Validation**: Query length limited to 1000 characters
- **API Keys**: Never commit API keys to version control
- **Rate Limiting**: Consider adding rate limiting for production use

## Contributing

Contributions welcome! Please:
1. Test your changes with the full pipeline
2. Update documentation for new features
3. Follow existing code style (type hints, docstrings)

## Acknowledgments

- Built with FastAPI, ChromaDB, and python-docx
- Embedding models: Nomic AI
- LLM: Qwen 2.5
