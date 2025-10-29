#
# Converts .docx files in the 'docx' directory to JSONL chunk files in the 'output/chunks' directory,
# extracting images to 'output/images'.
#
from pathlib import Path
try:
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'python-docx'. Install it with 'pip install python-docx' and retry."
    ) from exc
import json, hashlib, re, zipfile, shutil, tempfile

BASE_DIR = Path(__file__).resolve().parents[1]
DOCX_DIR = BASE_DIR / "docx"
CHUNK_DIR = BASE_DIR / "output" / "chunks"
IMAGE_ROOT = BASE_DIR / "output" / "images"
CHUNK_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_ROOT.mkdir(parents=True, exist_ok=True)

def slug(s): return re.sub(r'[^a-z0-9]+','-', s.lower()).strip('-')

def extract_images(docx_path, img_dir):
    shutil.rmtree(img_dir, ignore_errors=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    # unzip the docx and copy media/* out (Word stores images in word/media)
    with zipfile.ZipFile(docx_path) as z:
        for n in z.namelist():
            if n.startswith("word/media/"):
                target = img_dir / Path(n).name
                with z.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

def iterate_topics(doc: Document):
    current = {"h1": None, "h2": None, "h3": None, "paras": []}
    for p in doc.paragraphs:
        style = (p.style.name or "").lower()
        if style.startswith("heading"):
            # yield previous topic if it has content
            if current["h1"] or current["paras"]:
                yield current
                current = {"h1": None, "h2": None, "h3": None, "paras": []}
            level = int(re.findall(r'\d+', style)[0]) if re.findall(r'\d+', style) else 1
            if level == 1: current["h1"] = p.text.strip()
            elif level == 2: current["h2"] = p.text.strip()
            else: current["h3"] = p.text.strip()
        else:
            if p.text.strip():
                current["paras"].append(p.text.strip())
    if current["h1"] or current["paras"]:
        yield current

def chunk_text(texts, target_tokens=600, overlap=80):
    # simplistic splitter by paragraph length
    chunks, buf = [], []
    count = 0
    for t in texts:
        ln = max(1, len(t.split()))
        if count + ln > target_tokens and buf:
            chunks.append("\n\n".join(buf))
            # overlap by paragraphs
            buf = buf[-max(1, overlap // 20):]
            count = sum(len(x.split()) for x in buf)
        buf.append(t); count += ln
    if buf: chunks.append("\n\n".join(buf))
    return chunks

def process_docx(docx_path: Path):
    doc = Document(docx_path)
    image_dir = IMAGE_ROOT / docx_path.stem
    extract_images(docx_path, image_dir)
    chunk_path = CHUNK_DIR / f"{docx_path.stem}.jsonl"

    with open(chunk_path, "w", encoding="utf-8") as f:
        for topic in iterate_topics(doc):
            title = " / ".join([x for x in [topic["h1"], topic["h2"], topic["h3"]] if x]) or "Untitled"
            parts = chunk_text(topic["paras"])
            for i, body in enumerate(parts):
                rec = {
                    "id": hashlib.sha1(f"{docx_path.name}:{title}#{i}".encode()).hexdigest()[:16],
                    "title": title,
                    "section_index": i,
                    "text": body,
                    "images": [],
                    "source": {"kind": "docx", "file": docx_path.name}
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    if not DOCX_DIR.exists():
        raise SystemExit(f"Missing docx directory: {DOCX_DIR}")

    docx_files = sorted(DOCX_DIR.glob("*.docx"))
    if not docx_files:
        raise SystemExit(f"No .docx files found in {DOCX_DIR}")

    for path in docx_files:
        process_docx(path)

if __name__ == "__main__":
    main()
