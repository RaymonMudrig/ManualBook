#!/usr/bin/env python3
"""
Build article catalog from markdown files.

This script:
1. Reads translated markdown files (.md)
2. Extracts articles based on metadata and heading structure
3. Saves individual article files
4. Creates catalog.json index
5. Creates relationships.json graph

Usage:
    python Ingress/build_catalog.py
    python Ingress/build_catalog.py --input md/specific_file.md
    python Ingress/build_catalog.py --reset
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog.builder import CatalogBuilder
from catalog.metadata_parser import MetadataError


BASE_DIR = Path(__file__).resolve().parents[1]
MD_DIR = BASE_DIR / "md"
CATALOG_DIR = BASE_DIR / "output" / "catalog"


def main():
    parser = argparse.ArgumentParser(
        description="Build article catalog from markdown files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Build catalog from all .md files
    python Ingress/build_catalog.py

    # Build from specific file
    python Ingress/build_catalog.py --input md/manual.md

    # Reset existing catalog first
    python Ingress/build_catalog.py --reset

    # Verbose output
    python Ingress/build_catalog.py --verbose
        """
    )

    parser.add_argument(
        "--input",
        type=Path,
        help="Specific markdown file to process (default: all .md files in md/)"
    )

    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=CATALOG_DIR,
        help=f"Output directory for catalog (default: {CATALOG_DIR})"
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove existing catalog before building"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output"
    )

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("Article Catalog Builder")
    print("=" * 70)

    # Initialize builder
    builder = CatalogBuilder(args.catalog_dir)

    # Determine input files
    if args.input:
        if not args.input.exists():
            print(f"\n✗ Error: File not found: {args.input}")
            return 1
        md_files = [args.input]
    else:
        if not MD_DIR.exists():
            print(f"\n✗ Error: Directory not found: {MD_DIR}")
            return 1

        md_files = sorted(MD_DIR.glob("*.md"))

        if not md_files:
            print(f"\n✗ Error: No .md files found in {MD_DIR}")
            return 1

    print(f"\nInput: {len(md_files)} markdown file(s)")
    print(f"Output: {args.catalog_dir}")
    print("=" * 70)

    total_articles = 0
    files_processed = 0
    files_failed = 0

    for md_file in md_files:
        print(f"\nProcessing: {md_file.name}")

        try:
            # Build catalog from file
            stats = builder.build_from_markdown(
                md_file,
                clean_existing=(args.reset and files_processed == 0)
            )

            if stats['articles_count'] == 0:
                print(f"  ⚠ No articles with metadata found")
            else:
                print(f"  ✓ Extracted {stats['articles_count']} articles")
                if args.verbose:
                    print(f"    By Intent: {stats['by_intent']}")
                    print(f"    By Category: {stats['by_category']}")

                total_articles += stats['articles_count']
                files_processed += 1

        except MetadataError as e:
            print(f"  ✗ Metadata error: {e}")
            files_failed += 1

        except Exception as e:
            print(f"  ✗ Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            files_failed += 1

    # Summary
    print("\n" + "=" * 70)
    print("CATALOG BUILD COMPLETE")
    print("=" * 70)
    print(f"  Files processed: {files_processed}")
    print(f"  Files failed: {files_failed}")
    print(f"  Total articles: {total_articles}")
    print(f"\nCatalog location: {args.catalog_dir}")
    print(f"  • catalog.json        - Article index")
    print(f"  • relationships.json  - Relationship graph")
    print(f"  • articles/           - Individual article files ({total_articles} files)")

    # Show sample queries
    if total_articles > 0:
        print("\n" + "=" * 70)
        print("SAMPLE QUERIES")
        print("=" * 70)

        # Get some example articles
        try:
            do_articles = builder.search_articles(intent='do')
            learn_articles = builder.search_articles(intent='learn')
            app_articles = builder.search_articles(category='application')

            if do_articles:
                print(f"\n'How-to' articles ({len(do_articles)}):")
                for article in do_articles[:3]:
                    print(f"  • {article['title']} (id: {article['id']})")

            if learn_articles:
                print(f"\n'Concept' articles ({len(learn_articles)}):")
                for article in learn_articles[:3]:
                    print(f"  • {article['title']} (id: {article['id']})")

            if app_articles:
                print(f"\n'Application' articles ({len(app_articles)}):")
                for article in app_articles[:3]:
                    print(f"  • {article['title']} (id: {article['id']})")

        except Exception as e:
            if args.verbose:
                print(f"\nCould not generate sample queries: {e}")

    print("\n" + "=" * 70)
    print("Next steps:")
    print("  1. Review catalog.json to see article index")
    print("  2. Check relationships.json for article connections")
    print("  3. Browse articles/ directory to see individual files")
    print("  4. Run vectorization to enable semantic search")
    print("=" * 70 + "\n")

    return 0 if files_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
