# Metadata Guide for ManualBook Articles

Quick reference for adding metadata to your markdown documentation.

## Basic Format

```markdown
<!--METADATA
intent: do
id: your_article_id
category: application
-->

## Your Article Title

Article content goes here...
```

---

## Field Reference

### `intent` (Required)

**Purpose:** Indicates the type of information

| Value | When to Use | Example |
|-------|-------------|---------|
| `do` | Step-by-step instructions, how-to guides | "How to configure workspace" |
| `learn` | Concepts, explanations, reference material | "Understanding orderbook data" |
| `trouble` | Troubleshooting, problem-solving | "Fixing connection errors" |

**Examples:**
```markdown
intent: do       # For tutorials
intent: learn    # For concepts
intent: trouble  # For troubleshooting
```

### `id` (Required)

**Purpose:** Unique identifier for the article

**Rules:**
- Must be unique across all articles
- Lowercase only
- Use underscores or hyphens to separate words
- Letters, numbers, underscore, hyphen only

**Good IDs:**
```markdown
id: editing_palette
id: workspace-setup
id: orderbook_data
id: widget_config_01
```

**Bad IDs:**
```markdown
id: Editing Palette    # ✗ No spaces, no uppercase
id: editing.palette    # ✗ No dots
id: editing/palette    # ✗ No slashes
id: editing palette    # ✗ No spaces
```

### `category` (Required)

**Purpose:** High-level categorization

| Value | When to Use |
|-------|-------------|
| `application` | Application features, UI, configuration, workspace |
| `data` | Data types, market data, information structure |

**Examples:**
```markdown
category: application  # For UI, menus, widgets, workspace
category: data        # For orderbook, price data, trades
```

### `see` (Optional)

**Purpose:** List related articles (creates cross-references)

**Format:**
```markdown
see:
    - article_id_1
    - article_id_2
    - article_id_3
```

**When to use:**
- Link to prerequisites ("You should understand X first")
- Link to related concepts
- Link to alternative approaches
- Link to next steps

**Example:**
```markdown
<!--METADATA
intent: do
id: creating_watchlist
category: application
see:
    - watchlist_basics    # Prerequisites
    - adding_symbols      # Related task
    - workspace_setup     # Related concept
-->
```

---

## Complete Examples

### Example 1: How-To Guide

```markdown
<!--METADATA
intent: do
id: workspace_customization
category: application
see:
    - workspace_basics
    - template_usage
    - widget_management
-->

## Customizing Your Workspace

Step-by-step guide to customize your trading workspace.

### Prerequisites

Before starting, make sure you understand workspace basics.

### Steps

1. Open workspace settings
2. Select layout template
3. Add desired widgets
4. Save configuration

![Workspace Settings](images/workspace_settings.png)

### Next Steps

See [Widget Management](#widget_management) for details on managing widgets.
```

### Example 2: Concept Explanation

```markdown
<!--METADATA
intent: learn
id: orderbook_structure
category: data
see:
    - price_data
    - trade_data
    - market_depth
-->

## Orderbook Structure

Understanding how the orderbook organizes market data.

### Overview

The orderbook displays pending buy and sell orders.

### Components

- **Bid Side**: Buy orders sorted by price (highest first)
- **Ask Side**: Sell orders sorted by price (lowest first)
- **Spread**: Difference between best bid and ask

![Orderbook Diagram](images/orderbook.png)

### Related Concepts

- Price Data
- Trade Execution
- Market Depth
```

### Example 3: Troubleshooting

```markdown
<!--METADATA
intent: trouble
id: connection_timeout
category: application
see:
    - network_settings
    - authentication_issues
-->

## Troubleshooting Connection Timeouts

What to do when the application can't connect to the server.

### Symptoms

- "Connection timeout" error message
- Unable to load market data
- Workspace shows "Disconnected" status

### Solutions

#### 1. Check Internet Connection

Verify you have a stable internet connection.

#### 2. Verify Server Status

Check if the server is operational.

#### 3. Review Firewall Settings

Ensure port 8080 is not blocked.

### Still Not Working?

Contact support with:
- Error message screenshot
- Connection log file
- Your user ID
```

---

## Article Hierarchy with Metadata

Articles are organized by heading structure + metadata:

```markdown
<!--METADATA
intent: learn
id: trading_system
category: application
-->
# Trading System Overview

Main topic - H1 level, no parent.

<!--METADATA
intent: do
id: order_entry
category: application
see:
    - order_types
-->
## Order Entry

Subtopic - H2 level, parent: trading_system

<!--METADATA
intent: do
id: market_orders
category: application
-->
### Market Orders

Sub-subtopic - H3 level, parent: order_entry

<!--METADATA
intent: learn
id: order_types
category: application
-->
## Order Types

Another subtopic - H2 level, parent: trading_system
```

This creates the hierarchy:
```
trading_system (H1)
├── order_entry (H2)
│   └── market_orders (H3)
└── order_types (H2)
```

Plus cross-reference:
```
order_entry → see also → order_types
```

---

## Best Practices

### ✅ DO

- ✅ Add metadata to every major section
- ✅ Use descriptive, consistent IDs
- ✅ Add "see" links to related content
- ✅ Match intent to content type
- ✅ Keep one article per heading with metadata
- ✅ Include images with descriptive alt text

### ❌ DON'T

- ❌ Skip metadata for important sections
- ❌ Use duplicate IDs
- ❌ Add metadata to minor subsections
- ❌ Reference non-existent article IDs in "see"
- ❌ Mix intent types in one article
- ❌ Use special characters in IDs

---

## Quick Checklist

Before committing your markdown:

- [ ] All major sections have `<!--METADATA-->`
- [ ] All `id` values are unique
- [ ] All `id` values are lowercase with underscores/hyphens
- [ ] `intent` matches content (do/learn/trouble)
- [ ] `category` is correct (application/data)
- [ ] `see` references use correct article IDs
- [ ] No syntax errors in metadata block

---

## Testing Your Metadata

Build the catalog to validate:

```bash
python Ingress/build_catalog.py --input md/your_file.md --verbose
```

Look for:
- ✓ "Extracted N articles" (success)
- ✗ "Metadata error: ..." (fix the error)
- ✗ "No articles with metadata found" (add metadata)

---

## Common Mistakes

### Mistake 1: Missing Required Fields

```markdown
<!-- ✗ WRONG -->
<!--METADATA
id: my_article
-->

<!-- ✓ CORRECT -->
<!--METADATA
intent: do
id: my_article
category: application
-->
```

### Mistake 2: Invalid ID Format

```markdown
<!-- ✗ WRONG -->
id: My Article Name

<!-- ✓ CORRECT -->
id: my_article_name
```

### Mistake 3: Incorrect Intent

```markdown
<!-- ✗ WRONG: Tutorial but marked as "learn" -->
<!--METADATA
intent: learn
id: creating_workspace
category: application
-->
## How to Create a Workspace
Step 1: ...

<!-- ✓ CORRECT -->
<!--METADATA
intent: do
id: creating_workspace
category: application
-->
```

### Mistake 4: Broken See References

```markdown
<!-- ✗ WRONG: References non-existent ID -->
<!--METADATA
intent: do
id: my_article
category: application
see:
    - some_random_article  # This ID doesn't exist!
-->

<!-- ✓ CORRECT: Reference existing articles -->
<!--METADATA
intent: do
id: my_article
category: application
see:
    - workspace_setup  # This article exists
-->
```

---

## Template

Copy-paste this template:

```markdown
<!--METADATA
intent: do
id: your_unique_id
category: application
see:
    - related_article_id
-->

## Your Article Title

Your content here...
```

---

## Getting Help

- Check `schemas/article_metadata.json` for validation rules
- Run `python Ingress/build_catalog.py --verbose` for detailed errors
- See `PHASE1_COMPLETE.md` for examples
- Review `md/test_catalog.md` for working examples
