from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

try:
    import requests
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'requests'. Install it with 'pip install requests' and retry."
    ) from exc

try:
    import chromadb
    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'chromadb'. Install it with 'pip install chromadb' and retry."
    ) from exc

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    BASE_DIR_TEMP = Path(__file__).resolve().parents[1]
    env_path = BASE_DIR_TEMP / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, skip

# Add parent directory to path for llm module import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm import get_embeddings, get_gloss, LLMServiceError


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"
CHUNK_DIR = OUTPUT_DIR / "chunks"
INDEX_DIR = OUTPUT_DIR / "vector_index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_COLLECTION = os.environ.get("VECTOR_COLLECTION", "manual_chunks")


@dataclass
class ChunkRecord:
    id: str
    text: str
    title: str
    section_index: int
    images: Sequence[str]
    source: Dict[str, str]
    gloss: Optional[str] = None
    # New semantic chunking fields
    chunk_type: Optional[str] = None
    heading_level: Optional[int] = None
    heading_hierarchy: Optional[List[str]] = None
    section_title: Optional[str] = None
    token_count: Optional[int] = None
    has_children: Optional[bool] = None
    parent_title: Optional[str] = None


def iter_chunk_records(chunk_dir: Path) -> Iterator[ChunkRecord]:
    if not chunk_dir.exists():
        raise SystemExit(f"Missing chunk directory: {chunk_dir}")

    for file_path in sorted(chunk_dir.glob("*.jsonl")):
        with file_path.open("r", encoding="utf-8") as handle:
            line_number = 0
            for line in handle:
                line_number += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(
                        f"Invalid JSON in {file_path}:{line_number}: {exc}"
                    ) from exc

                yield ChunkRecord(
                    id=str(payload["id"]),
                    text=str(payload["text"]),
                    title=str(payload.get("title") or ""),
                    section_index=int(payload.get("section_index", line_number - 1)),
                    images=payload.get("images", []),
                    source=payload.get("source", {}),
                    gloss=payload.get("gloss"),
                    chunk_type=payload.get("chunk_type"),
                    heading_level=payload.get("heading_level"),
                    heading_hierarchy=payload.get("heading_hierarchy"),
                    section_title=payload.get("section_title"),
                    token_count=payload.get("token_count"),
                    has_children=payload.get("has_children"),
                    parent_title=payload.get("parent_title"),
                )


def batched(iterable: Iterable[ChunkRecord], size: int) -> Iterator[List[ChunkRecord]]:
    batch: List[ChunkRecord] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


# Embedding and gloss functions now use centralized llm service


def ensure_collection(client: ClientAPI, name: str, reset: bool) -> Collection:
    if reset:
        try:
            client.delete_collection(name)
        except Exception:
            pass
    return client.get_or_create_collection(name=name)


def format_metadata(record: ChunkRecord) -> Dict[str, object]:
    metadata: Dict[str, object] = {
        "title": record.title,
        "section_index": record.section_index,
    }
    images = [str(path) for path in record.images or []]
    if images:
        metadata["images"] = ";".join(images)
    if record.gloss:
        metadata["gloss"] = record.gloss

    # Add semantic chunking metadata
    if record.chunk_type:
        metadata["chunk_type"] = record.chunk_type
    if record.heading_level is not None:
        metadata["heading_level"] = record.heading_level
    if record.heading_hierarchy:
        metadata["heading_hierarchy"] = " > ".join(record.heading_hierarchy)
    if record.section_title:
        metadata["section_title"] = record.section_title
    if record.token_count is not None:
        metadata["token_count"] = record.token_count
    if record.has_children is not None:
        metadata["has_children"] = str(record.has_children)
    if record.parent_title:
        metadata["parent_title"] = record.parent_title

    for key, value in record.source.items():
        metadata[f"source_{key}"] = str(value)
    return metadata


def process_chunks(
    collection: Collection,
    records: Iterable[ChunkRecord],
    batch_size: int,
    pause: float,
) -> None:
    """Process chunks with progress indicator."""
    # Convert to list to get total count
    records_list = list(records)
    total_records = len(records_list)
    total_batches = (total_records + batch_size - 1) // batch_size
    processed = 0

    print(f"\nProcessing {total_records} chunks in {total_batches} batches...")
    print(f"Batch size: {batch_size}")
    print("=" * 70)

    start_time = time.time()

    for batch_idx, batch in enumerate(batched(records_list, batch_size), 1):
        batch_start = time.time()

        # Show progress
        progress = (batch_idx / total_batches) * 100
        print(f"\n[Batch {batch_idx}/{total_batches}] {progress:.1f}% | Processing {len(batch)} chunks...")

        texts: List[str] = []
        gloss_count = 0

        for idx, record in enumerate(batch, 1):
            if not record.gloss:
                try:
                    print(f"  └─ Generating gloss for chunk {idx}/{len(batch)}: {record.title[:50]}...")
                    record.gloss = get_gloss(record.text)
                    gloss_count += 1
                except Exception as exc:
                    print(f"  └─ Warning: Gloss generation failed: {exc}")
                    record.gloss = None

            augmented = record.text
            if record.gloss:
                augmented = f"{augmented.strip()}\n\nOne-line gloss: {record.gloss.strip()}"
            texts.append(augmented)

        if gloss_count > 0:
            print(f"  ✓ Generated {gloss_count} new glosses")

        # Embed with retry logic
        print(f"  → Generating embeddings for batch {batch_idx}...")
        attempts = 0
        while True:
            attempts += 1
            try:
                embeddings = get_embeddings(texts)
                print(f"  ✓ Embeddings generated (dimension: {len(embeddings[0])})")
                break
            except LLMServiceError as exc:
                if attempts >= 3:
                    print(f"  ✗ Failed after {attempts} attempts")
                    raise
                print(f"  ⚠ Attempt {attempts} failed, retrying in {pause * attempts}s...")
                time.sleep(pause * attempts)
            except requests.RequestException as exc:
                if attempts >= 3:
                    print(f"  ✗ Failed after {attempts} attempts")
                    raise RuntimeError(
                        f"Failed to contact embedding service after retries: {exc}"
                    ) from exc
                print(f"  ⚠ Attempt {attempts} failed, retrying in {pause * attempts}s...")
                time.sleep(pause * attempts)

        # Store in vector DB
        print(f"  → Storing {len(batch)} chunks in ChromaDB...")
        ids = [record.id for record in batch]
        metadatas = [format_metadata(record) for record in batch]
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        processed += len(batch)
        batch_time = time.time() - batch_start
        elapsed = time.time() - start_time
        avg_time_per_batch = elapsed / batch_idx
        remaining_batches = total_batches - batch_idx
        eta = remaining_batches * avg_time_per_batch

        print(f"  ✓ Batch {batch_idx} complete in {batch_time:.1f}s")
        print(f"  📊 Progress: {processed}/{total_records} chunks | Elapsed: {elapsed:.1f}s | ETA: {eta:.1f}s")

    total_time = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"✓ All {total_records} chunks processed successfully!")
    print(f"  Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
    print(f"  Average: {total_time/total_records:.2f}s per chunk")
    print("=" * 70)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vectorize chunked markdown/docx data into a Chroma index."
    )
    parser.add_argument(
        "--chunk-dir",
        type=Path,
        default=CHUNK_DIR,
        help="Directory containing chunk JSONL files.",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=INDEX_DIR,
        help="Path to Chroma persistent index directory.",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help="Chroma collection name.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Number of chunks to embed per request (embeddings endpoint).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop existing collection before inserting.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=2.0,
        help="Base pause (seconds) between retry attempts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.index_dir.mkdir(parents=True, exist_ok=True)
    if args.chunk_dir != CHUNK_DIR or args.index_dir != INDEX_DIR:
        os.environ["CHROMA_DB_IMPL"] = "duckdb+parquet"

    client = chromadb.PersistentClient(path=str(args.index_dir))
    collection = ensure_collection(client, args.collection, reset=args.reset)

    records = iter_chunk_records(args.chunk_dir)
    process_chunks(collection, records, batch_size=args.batch_size, pause=args.pause)


if __name__ == "__main__":
    main()
