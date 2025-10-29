#!/usr/bin/env python3
"""
Query classifier for intent and category detection.

Classifies user queries to enable metadata filtering:
- Intent: do (how-to), learn (concepts), trouble (problem-solving)
- Category: application (UI/features), data (market data)
- Topics: Key terms extracted from query

Usage:
    from retrieval.query_classifier import QueryClassifier

    classifier = QueryClassifier()
    result = classifier.classify("How do I set up my workspace?")
    # Returns: {"intent": "do", "category": "application", "topics": [...], "confidence": 0.95}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm import get_completion, LLMServiceError


CLASSIFICATION_PROMPT = """You are a technical documentation query classifier.

Query: "{query}"

Classify this query and return JSON:
{{
    "intent": "do" | "learn" | "trouble",
    "category": "application" | "data" | "unknown",
    "topics": ["topic1", "topic2", ...],
    "confidence": 0.0-1.0
}}

Intent rules:
- "do": User wants step-by-step instructions (how to, guide, tutorial, set up, configure, create, add, remove)
- "learn": User wants to understand concepts (what is, explain, definition, understand, learn about)
- "trouble": User has a problem to solve (error, not working, issue, problem, fix, broken, failed)

Category rules:
- "application": About UI, features, configuration, workspace, widgets, templates, settings, interface
- "data": About market data, orderbook, prices, trades, quotes, depth, ticker, instruments
- "unknown": Cannot determine category

Topics: Extract 2-5 key terms or phrases from the query that represent the main subjects.

Confidence: 0.0-1.0 (how confident you are in the classification)

Return ONLY valid JSON, no other text.
"""


class QueryClassifier:
    """Classify user queries by intent and category."""

    def __init__(self, temperature: float = 0.1, max_tokens: int = 200):
        """Initialize classifier.

        Args:
            temperature: LLM temperature (low for consistent classification)
            max_tokens: Max tokens for classification response
        """
        self.temperature = temperature
        self.max_tokens = max_tokens

    def classify(self, query: str) -> Dict:
        """Classify a user query.

        Args:
            query: User query string

        Returns:
            Classification result:
            {
                "intent": "do" | "learn" | "trouble",
                "category": "application" | "data" | "unknown",
                "topics": ["topic1", "topic2", ...],
                "confidence": 0.0-1.0
            }

        Raises:
            LLMServiceError: If classification fails
        """
        if not query or not query.strip():
            return self._default_classification()

        try:
            # Format prompt
            prompt = CLASSIFICATION_PROMPT.format(query=query.strip())

            # Get classification from LLM
            response = get_completion(
                prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )

            # Parse JSON response
            classification = self._parse_classification(response)

            # Validate classification
            classification = self._validate_classification(classification)

            return classification

        except Exception as e:
            print(f"⚠ Classification failed: {e}")
            print(f"  Using default classification for query: {query[:50]}...")
            return self._default_classification()

    def classify_batch(self, queries: List[str]) -> List[Dict]:
        """Classify multiple queries.

        Args:
            queries: List of query strings

        Returns:
            List of classification results
        """
        results = []
        for query in queries:
            classification = self.classify(query)
            results.append(classification)
        return results

    def _parse_classification(self, response: str) -> Dict:
        """Parse classification JSON from LLM response.

        Args:
            response: Raw LLM response

        Returns:
            Parsed classification dictionary
        """
        # Try to extract JSON from response
        # Sometimes LLM adds extra text, so we need to find the JSON block
        response = response.strip()

        # Find JSON block (between { and })
        start_idx = response.find('{')
        end_idx = response.rfind('}')

        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON found in response")

        json_str = response[start_idx:end_idx + 1]

        try:
            classification = json.loads(json_str)
            return classification
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in response: {e}")

    def _validate_classification(self, classification: Dict) -> Dict:
        """Validate and fix classification result.

        Args:
            classification: Raw classification dictionary

        Returns:
            Validated classification
        """
        # Default values
        validated = {
            "intent": "learn",
            "category": "unknown",
            "topics": [],
            "confidence": 0.5
        }

        # Validate intent
        if classification.get("intent") in ["do", "learn", "trouble"]:
            validated["intent"] = classification["intent"]

        # Validate category
        if classification.get("category") in ["application", "data", "unknown"]:
            validated["category"] = classification["category"]

        # Validate topics
        if isinstance(classification.get("topics"), list):
            topics = [str(t).strip() for t in classification["topics"] if t]
            validated["topics"] = topics[:5]  # Max 5 topics

        # Validate confidence
        try:
            confidence = float(classification.get("confidence", 0.5))
            validated["confidence"] = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            validated["confidence"] = 0.5

        return validated

    def _default_classification(self) -> Dict:
        """Return default classification when query is empty or classification fails.

        Returns:
            Default classification
        """
        return {
            "intent": "learn",
            "category": "unknown",
            "topics": [],
            "confidence": 0.0
        }


def main():
    """CLI for testing query classifier."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Classify user queries by intent and category"
    )

    parser.add_argument(
        "query",
        nargs="?",
        help="Query to classify (or use --interactive)"
    )

    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive mode for multiple queries"
    )

    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="LLM temperature (default: 0.1)"
    )

    args = parser.parse_args()

    classifier = QueryClassifier(temperature=args.temperature)

    if args.interactive:
        print("\n" + "="*70)
        print("Query Classifier - Interactive Mode")
        print("="*70)
        print("Enter queries to classify (Ctrl+C or 'quit' to exit)\n")

        try:
            while True:
                query = input("Query: ").strip()

                if not query or query.lower() in ['quit', 'exit', 'q']:
                    break

                print("\nClassifying...")
                result = classifier.classify(query)

                print("\nResult:")
                print(f"  Intent: {result['intent']}")
                print(f"  Category: {result['category']}")
                print(f"  Topics: {', '.join(result['topics'])}")
                print(f"  Confidence: {result['confidence']:.2f}")
                print()

        except KeyboardInterrupt:
            print("\n\nExiting...")

    elif args.query:
        print("\n" + "="*70)
        print("Query Classifier")
        print("="*70)
        print(f"Query: {args.query}\n")

        result = classifier.classify(args.query)

        print("Classification Result:")
        print(f"  Intent: {result['intent']}")
        print(f"  Category: {result['category']}")
        print(f"  Topics: {', '.join(result['topics'])}")
        print(f"  Confidence: {result['confidence']:.2f}")
        print("="*70 + "\n")

    else:
        # Test examples
        test_queries = [
            "How do I set up my workspace?",
            "What is a widget?",
            "My orderbook is not loading",
            "How to customize templates?",
            "Explain market depth",
            "Error when adding widget"
        ]

        print("\n" + "="*70)
        print("Query Classifier - Test Examples")
        print("="*70 + "\n")

        for query in test_queries:
            print(f"Query: {query}")
            result = classifier.classify(query)
            print(f"  → Intent: {result['intent']}, Category: {result['category']}, "
                  f"Confidence: {result['confidence']:.2f}")
            print(f"  → Topics: {', '.join(result['topics'])}")
            print()


if __name__ == "__main__":
    main()
