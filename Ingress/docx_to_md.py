#
# Converts .docx files in the 'docx' directory to markdown files in the 'md' directory,
# extracting images and saving them in corresponding image directories.
#
from pathlib import Path
import re
import shutil

try:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'python-docx'. Install it with 'pip install python-docx' and retry."
    ) from exc


BASE_DIR = Path(__file__).resolve().parents[1]
DOCX_DIR = BASE_DIR / "docx"
MD_DIR = BASE_DIR / "md"
MD_DIR.mkdir(parents=True, exist_ok=True)

WHITESPACE_RE = re.compile(r"\s+")


def iter_block_items(parent):
    """Yield paragraphs and tables in document order."""
    parent_elm = parent.element.body
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def clean_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def sanitize_alt(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def normalize_run_text(text: str) -> str:
    return text.replace("\xa0", " ").replace("\r", "").replace("\n", " ")


def extract_images_from_run(run, ctx) -> list[str]:
    outputs: list[str] = []
    blips = run.element.xpath(".//*[local-name()='blip']")
    for blip in blips:
        r_id = blip.get(qn("r:embed"))
        if not r_id:
            continue
        if r_id in ctx["image_map"]:
            rel_path = ctx["image_map"][r_id]
        else:
            image_part = run.part.related_parts[r_id]
            ext = image_part.partname.ext or image_part.content_type.split("/")[-1]
            filename = f"{ctx['doc_stem']}_img_{ctx['image_index']}.{ext}"
            ctx["image_index"] += 1
            target_path = ctx["image_dir"] / filename
            target_path.write_bytes(image_part.blob)
            rel_path = (ctx["image_rel_dir"] / filename).as_posix()
            ctx["image_map"][r_id] = rel_path
        doc_pr = run.element.xpath(".//*[local-name()='docPr']")
        alt = ""
        if doc_pr:
            raw_alt = doc_pr[0].get("descr") or doc_pr[0].get("title") or ""
            alt = sanitize_alt(raw_alt)
        if not alt:
            alt = sanitize_alt(Path(rel_path).stem.replace("_", " ").title())
        outputs.append(f"![{alt}]({rel_path})")
    return outputs


def format_run_text(run) -> str:
    text = normalize_run_text(run.text)
    if not text:
        return ""
    prefix_len = len(text) - len(text.lstrip())
    suffix_len = len(text) - len(text.rstrip())
    core_start = prefix_len
    core_end = len(text) - suffix_len if suffix_len else len(text)
    prefix = text[:core_start]
    suffix = text[core_end:] if suffix_len else ""
    core = text[core_start:core_end]
    if not core:
        return prefix + suffix

    formatted = core
    if run.bold and run.italic:
        formatted = f"***{core}***"
    elif run.bold:
        formatted = f"**{core}**"
    elif run.italic:
        formatted = f"*{core}*"
    return f"{prefix}{formatted}{suffix}"


def render_runs(paragraph: Paragraph, ctx) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for run in paragraph.runs:
        images = extract_images_from_run(run, ctx)
        for image in images:
            tokens.append(("image", image))
        formatted_text = format_run_text(run)
        if formatted_text:
            tokens.append(("text", formatted_text))
    if not tokens:
        fallback = normalize_run_text(paragraph.text)
        if fallback.strip():
            tokens.append(("text", fallback))
    return tokens


def paragraph_is_list(paragraph: Paragraph) -> bool:
    p = paragraph._p
    p_pr = p.pPr
    return bool(p_pr is not None and p_pr.numPr is not None)


def normalize_line(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def paragraph_to_markdown(paragraph: Paragraph, ctx) -> list[str]:
    tokens = render_runs(paragraph, ctx)
    if not tokens:
        return []

    style_name = (paragraph.style.name or "").lower()
    lines: list[str] = []
    text_buffer = ""
    emitted_primary = False

    def flush_text(buffer: str, primary: bool) -> None:
        nonlocal lines, emitted_primary
        normalized = normalize_line(buffer)
        if not normalized:
            return
        if primary:
            if style_name.startswith("heading"):
                level_match = re.findall(r"\d+", style_name)
                level = int(level_match[0]) if level_match else 1
                level = max(1, min(level, 6))
                lines.append(f"{'#' * level} {normalized}")
            elif paragraph_is_list(paragraph):
                lines.append(f"- {normalized}")
            else:
                lines.append(normalized)
        else:
            if paragraph_is_list(paragraph):
                lines.append(f"  {normalized}")
            else:
                lines.append(normalized)
        emitted_primary = emitted_primary or primary

    for kind, value in tokens:
        if kind == "text":
            text_buffer += value
        else:  # image
            if text_buffer:
                flush_text(text_buffer, primary=not emitted_primary)
                text_buffer = ""
            lines.append(value)
            emitted_primary = True

    if text_buffer:
        flush_text(text_buffer, primary=not emitted_primary)

    return lines


def table_to_markdown(table: Table) -> list[str]:
    rows = []
    for row in table.rows:
        cells = [clean_text(cell.text) for cell in row.cells]
        rows.append(cells)

    if not rows or all(not any(cell for cell in row) for row in rows):
        return []

    header = rows[0]
    if any(header):
        separator = ["---" if cell else "---" for cell in header]
        md_lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ]
        body_rows = rows[1:]
    else:
        md_lines = []
        body_rows = rows

    for body in body_rows:
        md_lines.append("| " + " | ".join(body) + " |")

    return md_lines


def convert_docx_to_markdown(docx_path: Path) -> str:
    doc = Document(docx_path)
    lines = []
    image_dir = MD_DIR / f"{docx_path.stem}_images"
    shutil.rmtree(image_dir, ignore_errors=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    ctx = {
        "doc_stem": docx_path.stem,
        "image_dir": image_dir,
        "image_rel_dir": Path(f"{docx_path.stem}_images"),
        "image_index": 1,
        "image_map": {},
    }
    previous_was_list = False

    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            md_lines = paragraph_to_markdown(block, ctx)
            current_is_list = bool(md_lines and paragraph_is_list(block))
        else:
            md_lines = table_to_markdown(block)
            current_is_list = False

        if not md_lines:
            continue

        if lines and lines[-1] and not (previous_was_list and current_is_list):
            lines.append("")
        lines.extend(md_lines)
        previous_was_list = current_is_list

    return "\n".join(lines).rstrip() + "\n"


def main():
    if not DOCX_DIR.exists():
        raise SystemExit(f"Missing docx directory: {DOCX_DIR}")

    docx_files = sorted(
        f for f in DOCX_DIR.glob("*.docx") if not f.name.startswith("~$")
    )
    if not docx_files:
        raise SystemExit(f"No .docx files found in {DOCX_DIR}")

    for docx_file in docx_files:
        markdown = convert_docx_to_markdown(docx_file)
        target = MD_DIR / f"{docx_file.stem}.md"
        target.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
