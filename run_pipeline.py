#!/usr/bin/env python3
"""
End-to-end pipeline runner for ManualBook system.

SMART WORKFLOW:
1. Check if English .md files exist
   - If YES: Skip to step 2 (saves time!)
   - If NO: Convert DOCX → .md → rename to .mdx → translate to .md (using Google Translate)
2. Parse and chunk (always cleans old chunks/images first)
3. Vectorize (auto-resets index if chunks are fresh)

File naming convention:
  - *.mdx  = Original language (preserved)
  - *.md   = English translated version (used by pipeline)

TRANSLATION:
- Uses Google Translate API (gtranslate_md.py) for line-by-line translation
- Preserves markdown syntax: tables, code blocks, images, lists
- No content merging or buffering

FEATURES:
- ✅ Progress indicators for translation and vectorization
- ✅ Automatic cleanup of old chunks/images before parsing
- ✅ Smart skip: if .md exists, no re-conversion needed
- ✅ Auto-reset vector index when chunks are regenerated

Usage:
    python run_pipeline.py [options]

Options:
    --skip-docx         Skip DOCX conversion/translation check
    --skip-translate    Skip translation step
    --skip-parse        Skip parsing/chunking step
    --skip-vectorize    Skip vectorization step
    --reset-index       Force reset vector index
    --start-server      Start the web server after pipeline completes
    --translate-only FILE  Only translate specified file

Examples:
    # Full pipeline (smart: skips if .md exists)
    python run_pipeline.py --start-server

    # Force re-conversion from DOCX
    rm md/*.md && python run_pipeline.py

    # Only re-vectorize existing chunks
    python run_pipeline.py --skip-parse --reset-index
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


BASE_DIR = Path(__file__).resolve().parent
INGRESS_DIR = BASE_DIR / "Ingress"
BACKEND_DIR = BASE_DIR / "Backend"
DOCX_DIR = BASE_DIR / "docx"
MD_DIR = BASE_DIR / "md"


def run_command(cmd: List[str], description: str, cwd: Optional[Path] = None) -> bool:
    """Run a command and return success status."""
    print(f"\n{'='*70}")
    print(f"STEP: {description}")
    print(f"{'='*70}")
    print(f"Running: {' '.join(str(c) for c in cmd)}")
    print()

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or BASE_DIR,
            check=True,
            capture_output=False,
            text=True,
        )
        print(f"\n✓ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"\n✗ {description} failed with exit code {exc.returncode}")
        return False
    except FileNotFoundError:
        print(f"\n✗ Command not found: {cmd[0]}")
        print("Make sure Python is in your PATH")
        return False


def check_prerequisites() -> bool:
    """Check if required directories and files exist."""
    print("Checking prerequisites...")

    checks = [
        (INGRESS_DIR.exists(), f"Ingress directory exists: {INGRESS_DIR}"),
        (BACKEND_DIR.exists(), f"Backend directory exists: {BACKEND_DIR}"),
        ((INGRESS_DIR / "docx_to_md.py").exists(), "docx_to_md.py exists"),
        ((INGRESS_DIR / "translate_md.py").exists(), "translate_md.py exists"),
        ((INGRESS_DIR / "parse_md.py").exists(), "parse_md.py exists"),
        ((INGRESS_DIR / "vectorize.py").exists(), "vectorize.py exists"),
        ((BACKEND_DIR / "app.py").exists(), "app.py exists"),
    ]

    all_passed = True
    for check, message in checks:
        status = "✓" if check else "✗"
        print(f"  {status} {message}")
        if not check:
            all_passed = False

    print()
    return all_passed


def count_files(directory: Path, pattern: str) -> int:
    """Count files matching pattern in directory."""
    if not directory.exists():
        return 0
    return len(list(directory.glob(pattern)))


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete ManualBook pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--skip-docx",
        action="store_true",
        help="Skip DOCX to Markdown conversion",
    )
    parser.add_argument(
        "--skip-translate",
        action="store_true",
        help="Skip translation step",
    )
    parser.add_argument(
        "--skip-parse",
        action="store_true",
        help="Skip Markdown parsing/chunking",
    )
    parser.add_argument(
        "--skip-vectorize",
        action="store_true",
        help="Skip vectorization step",
    )
    parser.add_argument(
        "--reset-index",
        action="store_true",
        help="Clear existing vector index before vectorizing",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="Start the web server after pipeline completes",
    )
    parser.add_argument(
        "--translate-only",
        type=str,
        metavar="FILE",
        help="Only translate specified Markdown file (skip all other steps)",
    )
    args = parser.parse_args()

    print("\n" + "="*70)
    print("ManualBook Pipeline Runner")
    print("="*70)

    # Check prerequisites
    if not check_prerequisites():
        print("\n✗ Prerequisite check failed. Please fix the issues above.")
        return 1

    # Handle translate-only mode
    if args.translate_only:
        input_file = Path(args.translate_only)
        if not input_file.exists():
            input_file = MD_DIR / args.translate_only
        if not input_file.exists():
            print(f"\n✗ File not found: {args.translate_only}")
            return 1

        output_file = input_file.with_suffix(".en.md")
        cmd = [
            sys.executable,
            str(INGRESS_DIR / "translate_md.py"),
            "--input", str(input_file),
            "--output", str(output_file),
        ]
        success = run_command(cmd, f"Translating {input_file.name}")
        return 0 if success else 1

    # Step 1: Check if .md files exist, otherwise convert and translate
    md_count = count_files(MD_DIR, "*.md")

    if md_count > 0 and not args.skip_docx:
        print("\n" + "="*70)
        print("STEP: Check existing files")
        print("="*70)
        print(f"✓ Found {md_count} existing .md file(s)")
        print("  Skipping DOCX conversion and translation")
        print("  (Use --skip-docx to force skip this check)")
    else:
        if not args.skip_docx:
            # Convert DOCX to MD
            docx_count = count_files(DOCX_DIR, "*.docx")
            if docx_count == 0:
                print("\n⚠ No .docx files found in docx/ directory")
                print("  Cannot proceed without source files")
                return 1

            print(f"\nFound {docx_count} .docx file(s) to convert")
            cmd = [sys.executable, str(INGRESS_DIR / "docx_to_md.py")]
            if not run_command(cmd, "Convert DOCX to Markdown"):
                return 1

            # After conversion, rename .md files to .mdx (preserve original language)
            print("\n" + "="*70)
            print("STEP: Preserve original language files (.md → .mdx)")
            print("="*70)

            md_files = sorted(MD_DIR.glob("*.md"))
            renamed_count = 0
            for md_file in md_files:
                mdx_file = md_file.with_suffix(".mdx")
                if not mdx_file.exists():
                    md_file.rename(mdx_file)
                    print(f"  Renamed: {md_file.name} → {mdx_file.name}")
                    renamed_count += 1

            if renamed_count > 0:
                print(f"\n✓ Renamed {renamed_count} file(s) to .mdx")
            else:
                print("\n⚠ No .md files to rename")

        # Step 1b: Translation (required if no .md files exist)
        if not args.skip_translate:
            md_count = count_files(MD_DIR, "*.md")
            mdx_count = count_files(MD_DIR, "*.mdx")

            if md_count > 0:
                print("\n✓ English .md files already exist, skipping translation")
            elif mdx_count == 0:
                print("\n⚠ No .mdx files found to translate")
                print("  Cannot proceed without source files")
                return 1
            else:
                print(f"\nFound {mdx_count} .mdx file(s) to translate")

                # Translate all .mdx files to .md (English) using Google Translate
                for mdx_file in sorted(MD_DIR.glob("*.mdx")):
                    output_file = mdx_file.with_suffix(".md")

                    cmd = [
                        sys.executable,
                        str(INGRESS_DIR / "translate_md.py"),
                        "--input", str(mdx_file),
                        "--output", str(output_file),
                    ]
                    if not run_command(cmd, f"Translate {mdx_file.name} → {output_file.name}"):
                        print(f"\n⚠ Translation of {mdx_file.name} failed")
                        print("  Cannot proceed without English files")
                        return 1

    # Step 2: Parse and chunk Markdown (with cleanup)
    if not args.skip_parse:
        md_count = count_files(MD_DIR, "*.md")
        if md_count == 0:
            print("\n✗ No Markdown files found in md/ directory")
            return 1

        # Clean up old chunks and images before parsing
        print("\n" + "="*70)
        print("STEP: Cleanup old chunks and images")
        print("="*70)

        chunks_dir = BASE_DIR / "output" / "chunks"
        images_dir = BASE_DIR / "output" / "images"

        if chunks_dir.exists():
            print(f"  Removing old chunks: {chunks_dir}")
            shutil.rmtree(chunks_dir)
            chunks_dir.mkdir(parents=True, exist_ok=True)
            print("  ✓ Old chunks removed")
        else:
            chunks_dir.mkdir(parents=True, exist_ok=True)
            print("  ✓ Chunks directory created")

        if images_dir.exists():
            print(f"  Removing old images: {images_dir}")
            shutil.rmtree(images_dir)
            images_dir.mkdir(parents=True, exist_ok=True)
            print("  ✓ Old images removed")
        else:
            images_dir.mkdir(parents=True, exist_ok=True)
            print("  ✓ Images directory created")

        print("\n✓ Cleanup complete\n")

        # Now parse with fresh directories
        print(f"Found {md_count} Markdown file(s) to parse")
        cmd = [sys.executable, str(INGRESS_DIR / "parse_md.py")]
        if not run_command(cmd, "Parse and chunk Markdown files"):
            return 1

    # Step 3: Vectorize chunks
    if not args.skip_vectorize:
        chunk_count = count_files(BASE_DIR / "output" / "chunks", "*.jsonl")
        if chunk_count == 0:
            print("\n✗ No chunk files found in output/chunks/")
            return 1

        print(f"\nFound {chunk_count} chunk file(s) to vectorize")

        # Always reset index when we've re-parsed (fresh chunks)
        # Or use --reset-index flag explicitly
        should_reset = args.reset_index or not args.skip_parse

        cmd = [sys.executable, str(INGRESS_DIR / "vectorize.py")]
        if should_reset:
            cmd.append("--reset")
            if not args.skip_parse:
                print("Note: Auto-resetting vector index (fresh chunks generated)")
            else:
                print("Note: Resetting vector index (--reset-index flag)")

        if not run_command(cmd, "Vectorize chunks into ChromaDB"):
            return 1

    # Final summary
    print("\n" + "="*70)
    print("PIPELINE COMPLETE!")
    print("="*70)
    print("\nSummary:")
    print(f"  • DOCX files: {count_files(DOCX_DIR, '*.docx')}")
    print(f"  • MDX files (original language): {count_files(MD_DIR, '*.mdx')}")
    print(f"  • MD files (English): {count_files(MD_DIR, '*.md')}")
    print(f"  • Chunk files: {count_files(BASE_DIR / 'output' / 'chunks', '*.jsonl')}")
    print(f"  • Vector index: {BASE_DIR / 'output' / 'vector_index'}")

    # Step 5: Start server (optional)
    if args.start_server:
        print("\n" + "="*70)
        print("Starting Web Server")
        print("="*70)
        print("\nThe server will run at http://localhost:8800")
        print("Press Ctrl+C to stop\n")

        cmd = [sys.executable, str(BACKEND_DIR / "app.py")]
        try:
            subprocess.run(cmd, cwd=BACKEND_DIR, check=True)
        except KeyboardInterrupt:
            print("\n\nServer stopped by user")
        except subprocess.CalledProcessError as exc:
            print(f"\n✗ Server failed with exit code {exc.returncode}")
            return 1
    else:
        print("\nTo start the web server, run:")
        print(f"  cd {BACKEND_DIR}")
        print("  python app.py")
        print("\nOr run this script with --start-server flag")

    return 0


if __name__ == "__main__":
    sys.exit(main())
