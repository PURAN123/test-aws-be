from PIL import Image
import io
import os

MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

FORMAT_EXTENSION_MAP = {
    'JPEG': 'jpg',
    'PNG': 'png',
    'WEBP': 'webp',
    'GIF': 'gif',
    'BMP': 'bmp',
    'TIFF': 'tiff',
}

# Formats that support transparency (RGBA)
TRANSPARENCY_FORMATS = {'PNG', 'WEBP', 'GIF', 'TIFF'}


def get_image_format(file) -> str:
    """
    Detect true image format using Pillow (not file extension).
    Returns Pillow format string e.g. 'JPEG', 'PNG', 'WEBP'
    """
    file.seek(0)
    img = Image.open(file)
    fmt = img.format  # 'JPEG', 'PNG', etc.
    file.seek(0)
    return fmt


def get_file_size_bytes(file) -> int:
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)
    return size


def compress_image(file, target_format: str = None, max_bytes: int = MAX_SIZE_BYTES) -> io.BytesIO:
    """
    Compress image iteratively until it's under max_bytes.
    Returns a BytesIO buffer of the compressed image.
    """
    file.seek(0)
    img = Image.open(file)
    original_format = img.format or 'JPEG'
    save_format = target_format or original_format

    # Convert RGBA to RGB if saving to JPEG
    if save_format == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = background

    quality = 85
    while quality >= 10:
        buffer = io.BytesIO()
        save_kwargs = {'format': save_format}
        if save_format in ('JPEG', 'WEBP'):
            save_kwargs['quality'] = quality
        img.save(buffer, **save_kwargs)
        buffer.seek(0)
        if buffer.getbuffer().nbytes <= max_bytes:
            buffer.seek(0)
            return buffer
        quality -= 10

    # If still too large at minimum quality, raise
    raise ValueError("Image cannot be compressed below 5MB. Please use a smaller image.")


def convert_image(file, target_format: str) -> io.BytesIO:
    """
    Convert image to target_format.
    target_format: Pillow format string e.g. 'PNG', 'WEBP', 'JPEG'
    Returns BytesIO buffer of converted image.
    """
    file.seek(0)
    img = Image.open(file)

    # Handle palette/transparency modes
    if target_format == 'JPEG':
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
    elif target_format == 'PNG':
        if img.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
            img = img.convert('RGBA')
    elif target_format == 'GIF':
        img = img.convert('P')
    elif target_format in ('WEBP', 'TIFF', 'BMP'):
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

    buffer = io.BytesIO()
    save_kwargs = {'format': target_format}
    if target_format in ('JPEG', 'WEBP'):
        save_kwargs['quality'] = 90
    img.save(buffer, **save_kwargs)
    buffer.seek(0)
    return buffer


def get_converted_filename(original_filename: str, target_format: str) -> str:
    """
    Generate output filename with new extension.
    e.g. photo.jpg + PNG → photo_converted.png
    """
    base = os.path.splitext(original_filename)[0]
    ext = FORMAT_EXTENSION_MAP.get(target_format, target_format.lower())
    return f"{base}_converted.{ext}"


# ─────────────────────────────────────────────
# Post-processing operations (called after conversion)
# All accept a file-like object + params, return (BytesIO, save_format)
# ─────────────────────────────────────────────

def _open_for_processing(file) -> tuple:
    """Open file, return (Image, save_format string)."""
    file.seek(0)
    img = Image.open(file)
    img.load()
    fmt = img.format or 'JPEG'
    return img, fmt


def _save_to_buffer(img: Image.Image, fmt: str) -> io.BytesIO:
    """Save Pillow image to BytesIO, handling JPEG color mode."""
    if fmt == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        img = bg
    elif fmt == 'JPEG' and img.mode != 'RGB':
        img = img.convert('RGB')

    buf = io.BytesIO()
    kwargs = {'format': fmt}
    if fmt in ('JPEG', 'WEBP'):
        kwargs['quality'] = 90
    img.save(buf, **kwargs)
    buf.seek(0)
    return buf


def resize_image(file, width: int = None, height: int = None, keep_ratio: bool = True) -> io.BytesIO:
    """
    Resize image to given width/height.
    If keep_ratio=True and only one dimension given, scale proportionally.
    """
    img, fmt = _open_for_processing(file)
    orig_w, orig_h = img.size

    if keep_ratio:
        if width and not height:
            ratio = width / orig_w
            height = int(orig_h * ratio)
        elif height and not width:
            ratio = height / orig_h
            width = int(orig_w * ratio)
        elif width and height:
            # Fit within box, preserve ratio
            ratio = min(width / orig_w, height / orig_h)
            width = int(orig_w * ratio)
            height = int(orig_h * ratio)

    if not width or not height:
        raise ValueError("Please provide at least one dimension (width or height).")

    resized = img.resize((width, height), Image.LANCZOS)
    return _save_to_buffer(resized, fmt)


def rotate_image(file, degrees: int, expand: bool = True) -> io.BytesIO:
    """
    Rotate image by degrees (90, 180, 270, or any angle).
    expand=True resizes canvas to fit the rotated image.
    """
    img, fmt = _open_for_processing(file)
    rotated = img.rotate(-degrees, expand=expand, fillcolor=(255, 255, 255) if fmt == 'JPEG' else None)
    return _save_to_buffer(rotated, fmt)


def flip_image(file, direction: str = 'horizontal') -> io.BytesIO:
    """Flip image horizontally or vertically."""
    from PIL import ImageOps
    img, fmt = _open_for_processing(file)
    if direction == 'horizontal':
        flipped = ImageOps.mirror(img)
    else:
        flipped = ImageOps.flip(img)
    return _save_to_buffer(flipped, fmt)


def grayscale_image(file) -> io.BytesIO:
    """Convert image to grayscale. Output is always JPEG-safe RGB."""
    img, fmt = _open_for_processing(file)
    gray = img.convert('L')
    # Convert back to RGB so JPEG saving works without issues
    rgb_gray = gray.convert('RGB')
    return _save_to_buffer(rgb_gray, fmt)


def crop_image(file, left: int, top: int, right: int, bottom: int) -> io.BytesIO:
    """
    Crop image to the box defined by (left, top, right, bottom) in real image pixels.
    """
    img, fmt = _open_for_processing(file)
    w, h = img.size

    # Clamp to image bounds
    left   = max(0, min(left,  w))
    top    = max(0, min(top,   h))
    right  = max(0, min(right, w))
    bottom = max(0, min(bottom, h))

    if right <= left or bottom <= top:
        raise ValueError("Invalid crop area — selection has zero size.")

    cropped = img.crop((left, top, right, bottom))
    return _save_to_buffer(cropped, fmt)


def compress_image_quality(file, quality: int = 60) -> io.BytesIO:
    """
    Compress image to a specific quality level (1–95).
    Works best for JPEG and WEBP. PNG uses lossless so quality is ignored.
    """
    img, fmt = _open_for_processing(file)
    if fmt == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        img = bg
    elif fmt == 'JPEG' and img.mode != 'RGB':
        img = img.convert('RGB')

    buf = io.BytesIO()
    kwargs = {'format': fmt}
    if fmt in ('JPEG', 'WEBP'):
        kwargs['quality'] = max(1, min(95, quality))
    img.save(buf, **kwargs)
    buf.seek(0)
    return buf