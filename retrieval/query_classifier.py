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

Intent rules (PRIMARY - always classify):
- "do": User wants to perform an action (show, add, create, configure, set up, remove, open, display, how to)
- "learn": User wants to understand concepts (what is, explain, definition, understand, learn about, describe)
- "trouble": User has a problem to solve (error, not working, issue, problem, fix, broken, failed, troubleshoot)

Category rules (SECONDARY - only if explicitly mentioned):
- "application": ONLY if query contains words: widget, interface, workspace, template, settings, menu, window, panel, toolbar
- "data": ONLY if query contains words: "data structure", "data format", "data content", "schema", "fields"
- "unknown": DEFAULT for all other cases

CRITICAL: Use category="unknown" unless the query literally contains the specific words listed above.

Examples:
- "show orderbook" → intent=do, category=unknown (no widget/data keywords)
- "show orderbook widget" → intent=do, category=application (contains "widget")
- "what is orderbook" → intent=learn, category=unknown (no widget/data keywords)
- "explain orderbook data structure" → intent=learn, category=data (contains "data structure")
- "add workspace" → intent=do, category=unknown ("workspace" alone is ambiguous)
- "configure workspace settings" → intent=do, category=application (contains "settings")

Topics: Extract 2-5 key terms or phrases from the query that represent the main subjects.

Confidence: 0.0-1.0 (how confident you are in the intent classification)

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

            # Apply pattern-based intent overrides (handle ambiguous grammar)
            classification = self._apply_intent_patterns(query, classification)

            # Apply strict category rules (override LLM guessing)
            classification = self._apply_category_rules(query, classification)

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

    def _apply_category_rules(self, query: str, classification: Dict) -> Dict:
        """Apply strict category rules based on keyword presence.

        Force category to "unknown" unless query explicitly contains category keywords.
        This overrides LLM guessing.

        Args:
            query: Original query string
            classification: Classification from LLM

        Returns:
            Classification with corrected category
        """
        query_lower = query.lower()

        # Application keywords
        app_keywords = ["widget", "interface", "workspace", "template", "settings",
                       "menu", "window", "panel", "toolbar"]

        # Data keywords (must be multi-word phrases)
        data_keywords = ["data structure", "data format", "data content",
                        "schema", "fields"]

        # Check for explicit application keywords
        has_app_keyword = any(kw in query_lower for kw in app_keywords)

        # Check for explicit data keywords
        has_data_keyword = any(kw in query_lower for kw in data_keywords)

        # Apply rules
        if has_app_keyword and not has_data_keyword:
            classification["category"] = "application"
        elif has_data_keyword and not has_app_keyword:
            classification["category"] = "data"
        else:
            # No explicit keywords or ambiguous -> force to unknown
            classification["category"] = "unknown"

        return classification

    def _apply_intent_patterns(self, query: str, classification: Dict) -> Dict:
        """Apply pattern-based intent overrides for ambiguous queries.

        Handles cases where grammar patterns indicate different intent than LLM classified.

        Args:
            query: Original query string
            classification: Classification from LLM

        Returns:
            Classification with corrected intent
        """
        query_lower = query.lower().strip()

        # Pattern 1: "X list" → usually means "show me the list of X" (learn)
        # Examples: "widget list", "feature list", "command list"
        if query_lower.endswith(" list") or query_lower == "list":
            classification["intent"] = "learn"
            classification["confidence"] = min(1.0, classification.get("confidence", 0.5) + 0.1)

        # Pattern 2: "list X" → imperative command (do)
        # Examples: "list widgets", "list all features"
        elif query_lower.startswith("list "):
            classification["intent"] = "do"

        # Pattern 3: Question words + "list" → seeking information (learn)
        # Examples: "what is the widget list", "show me widget list"
        question_words = ["what", "show me", "display", "view", "see", "where is"]
        if any(word in query_lower for word in question_words):
            if "list" in query_lower:
                classification["intent"] = "learn"

        # Pattern 4: Single word or code lookup → likely learn (reference)
        # Examples: "Q100", "orderbook", "workspace"
        words = query_lower.split()
        if len(words) == 1:
            # Single word could be reference lookup
            # Check if it looks like a code (uppercase + numbers)
            if any(char.isdigit() for char in query) and any(char.isupper() for char in query):
                classification["intent"] = "learn"

        # Pattern 5: "what are/is X" → clearly learn
        if query_lower.startswith(("what are", "what is", "what's")):
            classification["intent"] = "learn"

        # Pattern 6: "how to/do I" → clearly do
        if query_lower.startswith(("how to", "how do i", "how can i")):
            classification["intent"] = "do"

        return classification

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
