# Document Viewer Feature

This document describes the new Document Viewer feature added to ManualBook.

## Features

✅ **Tree Table of Contents (TOC)** - Left sidebar with hierarchical document structure
✅ **Full Document Display** - Content area with markdown rendering
✅ **Smooth Scrolling** - Click TOC items to jump to sections
✅ **Active Highlighting** - Current section highlighted in TOC
✅ **Image Support** - Properly handles images from `md/*_images/` directories
✅ **Document Selector** - Dropdown to switch between documents
✅ **Navigation** - Links between Semantic Query and Document Viewer

## Architecture

### Backend (Backend/app.py)

**New API Endpoints:**

1. `GET /api/documents` - Lists all available markdown documents
2. `GET /api/documents/{doc_id}` - Returns document content and TOC
3. `GET /viewer` - Serves the viewer HTML page

**New Functions:**

- `parse_markdown_toc()` - Extracts heading hierarchy from markdown
- `clean_markdown_content()` - Removes METADATA comments
- `fix_image_paths()` - Updates image paths to use `/md/` prefix

**Static File Mounting:**

- `/md` - Serves markdown files and their image directories

### Frontend

**New Files:**

1. `Backend/static/viewer.html` - Document viewer page
2. `Backend/static/viewer.css` - Styling for the viewer
3. `Backend/static/viewer.js` - JavaScript for TOC and scrolling

**Key Features:**

- Responsive layout with fixed TOC sidebar
- Hierarchical TOC with indentation (H1-H6)
- Smooth scroll to sections on click
- Active section highlighting based on scroll position
- Markdown rendering using `marked.js`
- Image path fixing for proper display

## Usage

### Starting the Server

```bash
cd Backend
python app.py
```

The server will start at `http://localhost:8800`

### Accessing the Document Viewer

1. **From Home Page:** Click "📚 Browse Documents" link
2. **Direct URL:** Navigate to `http://localhost:8800/viewer`

### Using the Viewer

1. **Select a Document:** Use the dropdown in the header
2. **Navigate:** Click any heading in the TOC to jump to that section
3. **Browse:** Scroll through the document content
4. **Return:** Click "🔍 Semantic Query" to go back to the query interface

## File Structure

```
Backend/
├── static/
│   ├── viewer.html      # Document viewer page
│   ├── viewer.css       # Viewer styles
│   ├── viewer.js        # Viewer logic
│   ├── index.html       # Updated with navigation link
│   ├── script.js        # Existing query interface
│   └── styles.css       # Existing styles
└── app.py               # Updated with new endpoints

md/
├── *.md                 # Markdown documents
└── *_images/            # Image directories for each document
```

## How It Works

### 1. Document Loading

```
User selects document
    ↓
GET /api/documents/{doc_id}
    ↓
Backend reads .md file
    ↓
Parse TOC from headings
    ↓
Clean METADATA comments
    ↓
Fix image paths
    ↓
Return JSON {content, toc, metadata}
```

### 2. TOC Generation

- Extracts H1-H6 headings from markdown
- Generates unique IDs for each heading
- Creates hierarchical structure
- Renders with indentation based on level

### 3. Smooth Scrolling

- TOC items are clickable links
- Clicking scrolls to heading with `scrollIntoView()`
- Active item highlighted based on scroll position
- Bidirectional navigation (TOC ↔ Content)

### 4. Image Handling

- Images referenced in markdown: `![alt](image.png)`
- Backend transforms to: `![alt](/md/{doc_id}_images/image.png)`
- FastAPI serves from mounted `/md` directory
- Works with existing `md/*_images/` structure

## Customization

### Styling

Edit `Backend/static/viewer.css` to customize:

- Sidebar width: `--sidebar-width: 280px`
- Colors: `--color-primary`, `--color-bg`, etc.
- TOC indentation: `.toc-item[data-level="N"]`
- Content width: `#document-article { max-width: 900px }`

### TOC Behavior

Edit `Backend/static/viewer.js` to customize:

- Active item detection: `handleScroll()` function
- Scroll offset: `scroll-margin-top` in CSS
- Animation timing: `setTimeout()` delays

### Markdown Rendering

- Uses `marked.js` library (v11.1.1)
- Configure in `marked.parse()` calls
- Add custom renderers if needed

## Responsive Design

- Desktop: Fixed TOC sidebar, scrollable content
- Mobile: Collapsible TOC (can be enhanced)
- Tablet: Optimized for medium screens

## Security

- Path traversal protection in doc_id
- File type validation (.md only)
- Static file serving with FastAPI safeguards

## Future Enhancements

Potential improvements:

- [ ] Search within document
- [ ] Print-friendly view
- [ ] Dark mode toggle
- [ ] Collapsible TOC sections
- [ ] Breadcrumb navigation
- [ ] Document metadata display
- [ ] Export to PDF
- [ ] Mobile menu toggle for TOC

## Testing

Test the implementation:

```bash
# Start server
cd Backend
python app.py

# Open browser
# Navigate to http://localhost:8800/viewer
# Select "IDX Terminal" from dropdown
# Click TOC items to test scrolling
# Verify images are displaying correctly
```

## Troubleshooting

**Documents not loading:**
- Check `md/` directory exists
- Verify .md files are present
- Check backend logs for errors

**Images not displaying:**
- Verify `md/*_images/` directories exist
- Check image paths in markdown
- Confirm `/md` mount in app.py

**TOC not working:**
- Check markdown has headings (# to ######)
- Verify heading IDs are being generated
- Check browser console for errors

**Scrolling issues:**
- Clear browser cache
- Check `scroll-behavior: smooth` in CSS
- Verify heading IDs match TOC links
