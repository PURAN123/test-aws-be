from PIL import Image
import io

# Page dimensions in points (1 pt = 1/72 inch)
PAGE_SIZES = {
    'A4':     (595, 842),
    'A3':     (842, 1191),
    'LETTER': (612, 792),
    'LEGAL':  (612, 1008),
}

MAX_SINGLE_SIZE_BYTES = 5 * 1024 * 1024   # 5 MB per image
MAX_TOTAL_SIZE_BYTES  = 20 * 1024 * 1024  # 20 MB total


def open_and_normalize(file) -> Image.Image:
    """Open image and convert to RGB (required for PDF embedding)."""
    file.seek(0)
    img = Image.open(file)
    img.load()  # force load before file handle closes

    if img.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        if img.mode in ('RGBA', 'LA'):
            background.paste(img, mask=img.split()[-1])
        else:
            background.paste(img)
        return background
    elif img.mode != 'RGB':
        return img.convert('RGB')
    return img


def fit_image_to_page(img: Image.Image, page_w: int, page_h: int) -> Image.Image:
    """Scale image to fit within page dimensions while preserving aspect ratio."""
    img_w, img_h = img.size
    scale = min(page_w / img_w, page_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


def images_to_pdf(image_files, page_size: str = 'A4', orientation: str = 'portrait') -> io.BytesIO:
    """
    Convert a list of image file objects into a single PDF.
    Each image becomes one page.

    Args:
        image_files: list of file-like objects (InMemoryUploadedFile etc.)
        page_size: 'A4', 'A3', 'LETTER', 'LEGAL', or 'FIT'
        orientation: 'portrait' or 'landscape'

    Returns:
        BytesIO buffer of the resulting PDF
    """
    if not image_files:
        raise ValueError("No images provided.")

    pages = []

    for f in image_files:
        img = open_and_normalize(f)

        if page_size == 'FIT':
            # Page size matches image size exactly
            pages.append(img)
        else:
            pw, ph = PAGE_SIZES[page_size]
            if orientation == 'landscape':
                pw, ph = ph, pw

            # Convert page pts to pixels at 96 dpi (1pt = 96/72 px ≈ 1.333 px)
            dpi = 96
            page_px_w = int(pw * dpi / 72)
            page_px_h = int(ph * dpi / 72)

            # Create white page canvas
            canvas = Image.new('RGB', (page_px_w, page_px_h), (255, 255, 255))

            # Fit & center image on page
            fitted = fit_image_to_page(img, page_px_w, page_px_h)
            offset_x = (page_px_w - fitted.width) // 2
            offset_y = (page_px_h - fitted.height) // 2
            canvas.paste(fitted, (offset_x, offset_y))
            pages.append(canvas)

    buffer = io.BytesIO()
    if len(pages) == 1:
        pages[0].save(buffer, format='PDF', resolution=96)
    else:
        pages[0].save(
            buffer,
            format='PDF',
            resolution=96,
            save_all=True,
            append_images=pages[1:]
        )

    buffer.seek(0)
    return buffer