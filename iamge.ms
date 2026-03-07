# Image Processing Suite — Technical Documentation

> **Project:** Django-based Image Conversion & Image-to-PDF web applications  
> **Purpose:** Interview reference — architecture, technology choices, and implementation decisions

---

## Overview

Built two Django applications as part of an existing project:

1. **`image_converter`** — Convert images between formats (JPG, PNG, WEBP, GIF, BMP, TIFF)
2. **`pdf_converter`** — Merge one or multiple images into a single downloadable PDF

Both apps share the same base template, S3 storage backend, and follow consistent patterns for file handling, database logging, and download delivery.

---

## Project Structure

```
your_project/
├── image_converter/
│   ├── models.py       # ImageConversion model (UUID pk, full audit trail)
│   ├── views.py        # index, convert (POST), download, history
│   ├── utils.py        # Pillow: format detection, compression, conversion
│   ├── forms.py        # ImageUploadForm with MIME validation
│   ├── urls.py
│   ├── admin.py
│   └── migrations/
│
├── pdf_converter/
│   ├── models.py       # ImageToPdfConversion model
│   ├── views.py        # index, convert (POST), download, history
│   ├── utils.py        # Pillow: multi-image → PDF with page sizing
│   ├── forms.py
│   ├── urls.py
│   ├── admin.py
│   └── migrations/
│
└── templates/
    ├── base.html                    # Shared nav, fonts, footer
    ├── image_converter/index.html   # Extends base.html
    └── pdf_converter/index.html     # Extends base.html
```

---

## Tech Stack

### Backend

| Technology | Version | Role |
|---|---|---|
| **Django** | 4.x / 5.x | Web framework — views, ORM, URL routing, file handling |
| **Pillow (PIL)** | ≥ 10.x | All image processing — open, convert, compress, save to PDF |
| **boto3** | via django-storages | AWS S3 file upload/download |
| **django-storages** | latest | S3-backed `FileField` — `DEFAULT_FILE_STORAGE` |
| **Python** | 3.10+ | Runtime |

### Frontend

| Technology | Role |
|---|---|
| **Tailwind CSS** (CDN) | Utility-first styling |
| **Vanilla JavaScript** | File handling, fetch API, drag & drop, blob download |
| **SortableJS** (CDN) | Drag-to-reorder image thumbnails in PDF converter |
| **Google Fonts** — Syne + DM Sans | Typography |
| **Alpine.js** (CDN) | Available in base template for reactive UI if needed |

### Infrastructure

| Service | Role |
|---|---|
| **AWS S3** | Stores original uploads and converted outputs |
| **Django ORM** | PostgreSQL / SQLite — logs every conversion |

---

## Application 1 — Image Converter

### What it does

Accepts a single image, detects its real format, lets the user pick a target format, optionally compresses if over 5 MB, converts using Pillow, saves both original and output to S3, logs the record to the database, and delivers the file as a forced browser download.

### Supported Conversions

| From ↓ \ To → | JPG | PNG | WEBP | GIF | BMP | TIFF |
|---|---|---|---|---|---|---|
| JPG | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| PNG | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| WEBP | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| GIF | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| BMP | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| TIFF | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

### Key Logic — `utils.py`

**Format detection** — uses `PIL.Image.format` (reads magic bytes from file header), not the file extension. This catches renamed files (e.g. a PNG renamed to `.jpg`).

```python
def get_image_format(file) -> str:
    file.seek(0)
    img = Image.open(file)
    return img.format  # 'JPEG', 'PNG', 'WEBP', etc.
```

**Compression** — iteratively reduces JPEG/WEBP quality from 85 down to 10 until the file fits under 5 MB. Raises an error if the image still can't be compressed enough.

```python
quality = 85
while quality >= 10:
    img.save(buffer, format=save_format, quality=quality)
    if buffer size <= 5MB:
        return buffer
    quality -= 10
```

**Color mode handling** — the most common source of conversion errors. JPEG does not support transparency (alpha channel). Any image in RGBA, LA, or Palette mode gets composited onto a white RGB background before saving as JPEG. PNG, WEBP, TIFF retain their alpha channel.

```python
# RGBA → JPEG: flatten alpha onto white background
background = Image.new('RGB', img.size, (255, 255, 255))
background.paste(img, mask=img.split()[-1])  # use alpha as mask
```

### Database Model — `ImageConversion`

```python
class ImageConversion(models.Model):
    id                  = UUIDField(primary_key=True)   # not sequential int
    original_file       = FileField(...)                # S3: conversions/original/
    original_filename   = CharField()
    original_format     = CharField()                   # detected, not from extension
    original_size_kb    = PositiveIntegerField()
    was_compressed      = BooleanField()
    compressed_size_kb  = PositiveIntegerField(null=True)
    requested_format    = CharField()
    converted_file      = FileField(...)                # S3: conversions/output/
    converted_size_kb   = PositiveIntegerField(null=True)
    status              = CharField()                   # pending / success / failed
    error_message       = TextField(null=True)
    ip_address          = GenericIPAddressField(null=True)
    created_at          = DateTimeField(auto_now_add=True)
```

**Why UUID as primary key?** Avoids exposing sequential integer IDs in URLs, which would reveal the total number of conversions and allow enumeration attacks.

### API Endpoints

| Method | URL | Purpose |
|---|---|---|
| GET | `/converter/` | Render upload page |
| POST | `/converter/convert/` | Validate, compress, convert, save, return JSON |
| GET | `/converter/download/<id>/` | Proxy file from S3 with forced download headers |
| GET | `/converter/history/` | Return last 20 conversions as JSON |

### Download Flow

S3 URLs are cross-origin. The browser's `download` attribute on an `<a>` tag is **ignored for cross-origin URLs** — the browser just navigates to the file instead of downloading it.

**Solution:** A Django proxy view fetches the file from S3 server-side and returns it with `Content-Disposition: attachment`:

```python
# views.py — download()
with urllib.request.urlopen(s3_url) as s3_response:
    file_data = s3_response.read()
response = HttpResponse(file_data, content_type='image/png')
response['Content-Disposition'] = 'attachment; filename="output.png"'
```

On the frontend, a `fetch()` → `blob()` → `URL.createObjectURL()` chain triggers the actual save dialog:

```javascript
const res  = await fetch('/converter/download/<id>/');
const blob = await res.blob();
const a    = document.createElement('a');
a.href     = URL.createObjectURL(blob);
a.download = 'output.png';
a.click();
```

---

## Application 2 — Image to PDF Converter

### What it does

Accepts multiple images (up to 20, max 5 MB each, 20 MB total), lets the user reorder them by dragging, select page size and orientation, name the output file, then merges everything into a single PDF — one image per page — and saves it to S3.

### Page Sizes Supported

| Size | Dimensions (pts) | Common Use |
|---|---|---|
| A4 | 595 × 842 | International standard |
| A3 | 842 × 1191 | Large format |
| Letter | 612 × 792 | US standard |
| Legal | 612 × 1008 | US legal documents |
| Fit to Image | Image dimensions | No whitespace, image fills page exactly |

### Key Logic — `utils.py`

**Multi-image PDF generation** using Pillow's `save_all` + `append_images`:

```python
# First page saves the PDF, rest are appended
pages[0].save(
    buffer,
    format='PDF',
    resolution=96,
    save_all=True,
    append_images=pages[1:]
)
```

**Image fitting** — each image is scaled to fit the page while preserving aspect ratio, then centered on a white canvas:

```python
scale    = min(page_w / img_w, page_h / img_h)
fitted   = img.resize((int(img_w * scale), int(img_h * scale)), Image.LANCZOS)
offset_x = (page_w - fitted.width) // 2
offset_y = (page_h - fitted.height) // 2
canvas.paste(fitted, (offset_x, offset_y))
```

**LANCZOS resampling** is used for resizing — it's the highest quality downsampling filter available in Pillow, minimizing aliasing artifacts.

**Page size conversion** — PDF dimensions are measured in points (1 pt = 1/72 inch). The code converts to pixels at 96 DPI for Pillow to work with:

```python
page_px_w = int(page_pts_w * 96 / 72)
page_px_h = int(page_pts_h * 96 / 72)
```

### Database Model — `ImageToPdfConversion`

```python
class ImageToPdfConversion(models.Model):
    id                    = UUIDField(primary_key=True)
    image_count           = PositiveIntegerField()
    original_filenames    = JSONField()              # ordered list of filenames
    total_original_size_kb = PositiveIntegerField()
    page_size             = CharField()              # A4, A3, LETTER, LEGAL, FIT
    orientation           = CharField()              # portrait / landscape
    pdf_filename          = CharField()
    pdf_file              = FileField(...)           # S3: pdf_conversions/
    pdf_size_kb           = PositiveIntegerField(null=True)
    status                = CharField()
    ip_address            = GenericIPAddressField(null=True)
    created_at            = DateTimeField(auto_now_add=True)
```

**Why `JSONField` for `original_filenames`?** A single conversion involves a variable number of images. Storing their names as a JSON array in one column is simpler than a separate `ConversionImage` table for this use case.

### Frontend — Drag to Reorder

Uses **SortableJS** to make the image grid sortable. The JS `fileList` array is reordered on every drag-end event to match the visual order, so the FormData submitted to the backend always reflects the user's intended page order.

```javascript
Sortable.create(grid, {
    animation: 150,
    onEnd(evt) {
        const moved = fileList.splice(evt.oldIndex, 1)[0];
        fileList.splice(evt.newIndex, 0, moved);
        renderGrid();  // re-renders page number badges
    }
});
```

---

## Shared Patterns

### File Storage — S3

Both apps use `django-storages` with `DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'`. `FileField.save()` automatically uploads to S3 — no manual boto3 calls needed.

S3 paths are namespaced by date to avoid directory bloat:

```
conversions/original/2026/03/07/photo.jpg
conversions/output/2026/03/07/photo_converted.png
pdf_conversions/2026/03/07/document.pdf
```

### Validation Strategy

Validation happens at two layers:

- **Client-side (JS):** Immediate feedback — file type check from MIME type, size check before upload, format-match warning. Prevents unnecessary network requests.
- **Server-side (Django view):** Re-validates everything — content type, per-file size, total size, format mismatch. Client-side checks are UX only; server-side is the actual security boundary.

### Template Inheritance

All pages extend `base.html` using Django's template inheritance system:

```
base.html              ← nav, fonts, footer, extra_styles block, extra_scripts block
    └── image_converter/index.html   ← {% extends "base.html" %}
    └── pdf_converter/index.html     ← {% extends "base.html" %}
```

Page-specific CSS animations and JavaScript are injected via `{% block extra_styles %}` and `{% block extra_scripts %}` without polluting the base template.

---

## Potential Interview Questions & Answers

**Q: Why Pillow and not ImageMagick or FFmpeg?**  
Pillow is a pure Python library — zero system dependencies, easy to install via pip, works everywhere Django runs. ImageMagick requires a system-level install and shell execution which introduces security risks. For the formats needed here (JPEG, PNG, WEBP, GIF, BMP, TIFF, PDF), Pillow handles everything natively.

**Q: Why does RGBA → JPEG need special handling?**  
JPEG is a lossy format that only supports RGB color space — it has no alpha (transparency) channel. If you try to save an RGBA image directly as JPEG, Pillow raises an error. The solution is to composite the RGBA image onto a white RGB background using the alpha channel as a mask, which effectively "flattens" the transparency before encoding.

**Q: How does format detection work — why not just read the file extension?**  
File extensions are user-controlled and unreliable. A user can rename `photo.png` to `photo.jpg` and upload it. Pillow reads the first few bytes of the file (the "magic bytes" or file header) to identify the actual format, regardless of the filename. For example, PNG files always start with the byte sequence `\x89PNG`.

**Q: Why UUID primary keys instead of auto-incrementing integers?**  
Integer IDs in URLs like `/download/1/`, `/download/2/` expose two problems: they reveal total record count, and they allow easy enumeration (anyone can iterate through IDs to discover other users' files). UUIDs are non-sequential and practically unguessable, making the download URLs safe to expose without additional authentication on each file.

**Q: Why proxy the download through Django instead of linking directly to S3?**  
The HTML `download` attribute only works for same-origin URLs. For cross-origin URLs (like S3), browsers ignore the attribute and navigate to the file instead. The proxy view fetches the file server-side and sets `Content-Disposition: attachment` in the response headers, which tells the browser to save the file rather than display it — regardless of origin.

**Q: How does the multi-image PDF maintain page order?**  
The frontend maintains a `fileList` JavaScript array. SortableJS fires an `onEnd` event after every drag, which splices the moved item to its new position in `fileList`. When the form is submitted, files are appended to `FormData` in `fileList` order. Django's `request.FILES.getlist('images')` returns them in that same order, which becomes the page order in the PDF.

**Q: What happens if compression can't get an image below 5 MB?**  
The compression function reduces JPEG/WEBP quality from 85 down to 10 in steps of 10. If the image is still over 5 MB at quality 10 (which can happen with very high-resolution images), it raises a `ValueError` which the view catches and returns as a user-friendly error message. The user is instructed to use a smaller source image.

---

## Setup Summary

```bash
# Install dependency
pip install Pillow

# Register apps in settings.py
INSTALLED_APPS = [..., 'image_converter', 'pdf_converter']

# Wire URLs in project urls.py
path('converter/', include('image_converter.urls', namespace='image_converter')),
path('pdf/',       include('pdf_converter.urls',   namespace='pdf_converter')),

# Run migrations
python manage.py migrate
```

---

*Built with Django · Pillow · AWS S3 · Tailwind CSS · SortableJS*