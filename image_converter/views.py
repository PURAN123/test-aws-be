import os
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .forms import ImageUploadForm
from .models import ImageConversion
from .utils import (
    get_image_format,
    get_file_size_bytes,
    compress_image,
    convert_image,
    get_converted_filename,
    MAX_SIZE_BYTES,
    resize_image,
    rotate_image,
    flip_image,
    grayscale_image,
    compress_image_quality,
    crop_image,
)


def index(request):
    """Render the main image converter page."""
    form = ImageUploadForm()
    recent_conversions = ImageConversion.objects.filter(status='success').order_by('-created_at')[:5]
    return render(request, 'image_converter/index.html', {
        'form': form,
        'recent_conversions': recent_conversions,
    })


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@require_http_methods(["POST"])
def convert(request):
    """
    Main conversion endpoint.
    Handles:
    - File validation
    - Size check (>5MB → ask to compress)
    - Same format check
    - Conversion via Pillow
    - Save original + converted to S3
    - Save DB record
    """
    form = ImageUploadForm(request.POST, request.FILES)

    if not form.is_valid():
        errors = {field: error[0] for field, error in form.errors.items()}
        return JsonResponse({'status': 'error', 'errors': errors}, status=400)

    image_file = request.FILES['image']
    target_format = form.cleaned_data['target_format']
    compress_confirmed = form.cleaned_data.get('compress_confirmed', False)

    # --- Detect real format ---
    try:
        detected_format = get_image_format(image_file)
    except Exception:
        return JsonResponse({
            'status': 'error',
            'message': 'Could not read the image file. Please upload a valid image.'
        }, status=400)

    # Normalize JPEG variants
    if detected_format == 'JPG':
        detected_format = 'JPEG'

    # --- Same format check ---
    if detected_format == target_format:
        return JsonResponse({
            'status': 'warning',
            'message': f'Your image is already in {target_format} format. Please choose a different format.'
        }, status=200)

    # --- Size check ---
    file_size = get_file_size_bytes(image_file)
    original_size_kb = file_size // 1024
    was_compressed = False
    compressed_size_kb = None

    if file_size > MAX_SIZE_BYTES:
        if not compress_confirmed:
            return JsonResponse({
                'status': 'size_exceeded',
                'message': f'Your image is {original_size_kb / 1024:.1f} MB which exceeds the 5MB limit. Would you like to compress it before converting?',
                'size_mb': round(file_size / (1024 * 1024), 2),
            }, status=200)

        # User confirmed compression
        try:
            image_file = compress_image(image_file, target_format=detected_format)
            compressed_size_kb = image_file.getbuffer().nbytes // 1024
            was_compressed = True
        except ValueError as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    # --- Convert image ---
    try:
        converted_buffer = convert_image(image_file, target_format)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Conversion failed: {str(e)}'
        }, status=500)

    converted_size_kb = converted_buffer.getbuffer().nbytes // 1024
    original_filename = request.FILES['image'].name
    converted_filename = get_converted_filename(original_filename, target_format)

    # --- Save to DB + S3 ---
    try:
        image_file.seek(0)
        record = ImageConversion(
            original_filename=original_filename,
            original_format=detected_format,
            original_size_kb=original_size_kb,
            was_compressed=was_compressed,
            compressed_size_kb=compressed_size_kb if was_compressed else None,
            requested_format=target_format,
            converted_size_kb=converted_size_kb,
            status='success',
            ip_address=get_client_ip(request),
        )

        # Save original file to S3
        original_content = ContentFile(image_file.read() if hasattr(image_file, 'read') else image_file.getvalue())
        record.original_file.save(original_filename, original_content, save=False)

        # Save converted file to S3
        converted_buffer.seek(0)
        converted_content = ContentFile(converted_buffer.read())
        record.converted_file.save(converted_filename, converted_content, save=False)

        record.save()

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Failed to save files: {str(e)}'
        }, status=500)

    # --- Return download info ---
    try:
        download_url = record.converted_file.url
    except Exception:
        download_url = None

    return JsonResponse({
        'status': 'success',
        'message': 'Image converted successfully!',
        'conversion_id': str(record.id),
        'original_filename': original_filename,
        'converted_filename': converted_filename,
        'original_format': detected_format,
        'converted_format': target_format,
        'original_size_kb': original_size_kb,
        'converted_size_kb': converted_size_kb,
        'was_compressed': was_compressed,
        'download_url': download_url,
    })


def download(request, conversion_id):
    """
    Proxy the S3 file through Django so the browser downloads it
    instead of redirecting to the S3 URL.
    """
    import urllib.request
    from django.http import HttpResponse, Http404

    try:
        record = ImageConversion.objects.get(id=conversion_id, status='success')
    except (ImageConversion.DoesNotExist, Exception):
        raise Http404("Conversion not found.")

    try:
        file_url = record.converted_file.url  # presigned or public S3 URL
        with urllib.request.urlopen(file_url) as s3_response:
            file_data = s3_response.read()

        ext = os.path.splitext(record.converted_file.name)[-1].lower()
        content_type_map = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png', '.webp': 'image/webp',
            '.gif': 'image/gif', '.bmp': 'image/bmp',
            '.tiff': 'image/tiff', '.tif': 'image/tiff',
        }
        content_type = content_type_map.get(ext, 'application/octet-stream')
        filename = os.path.basename(record.converted_file.name)

        response = HttpResponse(file_data, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        from django.http import Http404
        raise Http404(f"File could not be retrieved: {str(e)}")


@require_http_methods(["POST"])
def process(request, conversion_id):
    """
    Post-conversion operations: resize, rotate, flip, grayscale, compress.
    Fetches the already-converted file from S3, applies the operation,
    streams the result back directly — does NOT save a new DB record.
    If operation='none', proxies the original converted file as-is.
    """
    import urllib.request
    from django.http import HttpResponse, Http404
    from PIL import Image
    import io

    try:
        record = ImageConversion.objects.get(id=conversion_id, status='success')
    except (ImageConversion.DoesNotExist, Exception):
        raise Http404("Conversion not found.")

    operation = request.POST.get('operation', 'none')

    # Fetch the converted file from S3
    try:
        file_url = record.converted_file.url
        with urllib.request.urlopen(file_url) as s3_resp:
            file_bytes = s3_resp.read()
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Could not fetch file: {str(e)}'}, status=500)

    file_obj = io.BytesIO(file_bytes)

    # Detect content type for response
    ext = os.path.splitext(record.converted_file.name)[-1].lower()
    content_type_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png',  '.webp': 'image/webp',
        '.gif': 'image/gif',  '.bmp':  'image/bmp',
        '.tiff': 'image/tiff','.tif':  'image/tiff',
    }
    content_type = content_type_map.get(ext, 'application/octet-stream')
    base_name = os.path.splitext(record.converted_file.name.split('/')[-1])[0]

    try:
        if operation == 'none':
            result_buf = file_obj

        elif operation == 'crop':
            try:
                left   = int(request.POST.get('left',   0))
                top    = int(request.POST.get('top',    0))
                right  = int(request.POST.get('right',  0))
                bottom = int(request.POST.get('bottom', 0))
            except (ValueError, TypeError):
                return JsonResponse({'status': 'error', 'message': 'Invalid crop coordinates.'}, status=400)
            result_buf = crop_image(file_obj, left=left, top=top, right=right, bottom=bottom)
            base_name  = f"{base_name}_cropped"

        elif operation == 'resize':
            width  = request.POST.get('width', '').strip()
            height = request.POST.get('height', '').strip()
            keep   = request.POST.get('keep_ratio', 'true') == 'true'
            width  = int(width)  if width  else None
            height = int(height) if height else None
            if not width and not height:
                return JsonResponse({'status': 'error', 'message': 'Enter at least one dimension.'}, status=400)
            if (width and width < 1) or (height and height < 1):
                return JsonResponse({'status': 'error', 'message': 'Dimensions must be positive numbers.'}, status=400)
            if (width and width > 10000) or (height and height > 10000):
                return JsonResponse({'status': 'error', 'message': 'Maximum dimension is 10,000 px.'}, status=400)
            result_buf = resize_image(file_obj, width=width, height=height, keep_ratio=keep)
            base_name  = f"{base_name}_resized"

        elif operation == 'rotate':
            degrees = int(request.POST.get('degrees', 90))
            if degrees not in (90, 180, 270):
                return JsonResponse({'status': 'error', 'message': 'Rotation must be 90, 180, or 270 degrees.'}, status=400)
            result_buf = rotate_image(file_obj, degrees=degrees)
            base_name  = f"{base_name}_rotated{degrees}"

        elif operation == 'flip':
            direction = request.POST.get('direction', 'horizontal')
            if direction not in ('horizontal', 'vertical'):
                return JsonResponse({'status': 'error', 'message': 'Direction must be horizontal or vertical.'}, status=400)
            result_buf = flip_image(file_obj, direction=direction)
            base_name  = f"{base_name}_flipped"

        elif operation == 'grayscale':
            result_buf = grayscale_image(file_obj)
            base_name  = f"{base_name}_grayscale"

        elif operation == 'compress':
            quality = int(request.POST.get('quality', 60))
            result_buf = compress_image_quality(file_obj, quality=quality)
            base_name  = f"{base_name}_compressed"

        else:
            return JsonResponse({'status': 'error', 'message': f'Unknown operation: {operation}'}, status=400)

    except ValueError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Operation failed: {str(e)}'}, status=500)

    result_buf.seek(0)
    download_filename = f"{base_name}{ext}"
    response = HttpResponse(result_buf.read(), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{download_filename}"'
    return response


def history(request):
    """Return recent conversion history."""
    conversions = ImageConversion.objects.filter(status='success').order_by('-created_at')[:20]
    data = [{
        'id': str(c.id),
        'original_filename': c.original_filename,
        'original_format': c.original_format,
        'requested_format': c.requested_format,
        'original_size_kb': c.original_size_kb,
        'converted_size_kb': c.converted_size_kb,
        'was_compressed': c.was_compressed,
        'created_at': c.created_at.strftime('%d %b %Y, %H:%M'),
    } for c in conversions]
    return JsonResponse({'conversions': data})


# ─────────────────────────────────────────────
# Image Editor  (/edit/)
# ─────────────────────────────────────────────

def edit_view(request):
    """Render the standalone image editor page."""
    return render(request, 'image_converter/editor.html')


@require_http_methods(["POST"])
def edit_apply(request):
    """
    Accepts:
      - image  : the original uploaded file
      - ops    : JSON array of {type, params} operations in order
      - format : 'original' | 'JPEG' | 'PNG' | 'WEBP'
      - quality: 1-100 (for JPEG/WEBP)

    Replays all ops server-side with Pillow and returns the final image
    as a download response. No DB record is saved.
    """
    from PIL import Image as PILImage
    import io

    image_file = request.FILES.get('image')
    if not image_file:
        return JsonResponse({'message': 'No image provided.'}, status=400)

    ops_raw = request.POST.get('ops', '[]')
    try:
        ops = json.loads(ops_raw)
    except Exception:
        return JsonResponse({'message': 'Invalid ops payload.'}, status=400)

    target_format = request.POST.get('format', 'original').upper()
    try:
        quality = int(request.POST.get('quality', 90))
        quality = max(1, min(100, quality))
    except ValueError:
        quality = 90

    try:
        image_file.seek(0)
        img = PILImage.open(image_file)
        img.load()
        original_format = img.format or 'JPEG'
    except Exception as e:
        return JsonResponse({'message': f'Could not open image: {e}'}, status=400)

    save_format = original_format if target_format == 'ORIGINAL' else target_format

    # Replay operations
    for op in ops:
        op_type = op.get('type')
        params  = op.get('params', {})

        try:
            if op_type == 'crop':
                left   = int(params.get('left',   0))
                top    = int(params.get('top',    0))
                right  = int(params.get('right',  img.width))
                bottom = int(params.get('bottom', img.height))
                left   = max(0, min(left,   img.width))
                top    = max(0, min(top,    img.height))
                right  = max(0, min(right,  img.width))
                bottom = max(0, min(bottom, img.height))
                if right > left and bottom > top:
                    img = img.crop((left, top, right, bottom))

            elif op_type == 'flip':
                from PIL import ImageOps
                if params.get('direction') == 'horizontal':
                    img = ImageOps.mirror(img)
                else:
                    img = ImageOps.flip(img)

            elif op_type == 'rotate':
                deg = int(params.get('degrees', 90))
                img = img.rotate(-deg, expand=True)

            elif op_type == 'grayscale':
                img = img.convert('L').convert('RGB')

            elif op_type == 'brightness':
                from PIL import ImageEnhance
                bright   = float(params.get('brightness', 0))
                contrast = float(params.get('contrast',   0))
                # Map -100..100 → Pillow enhance factor 0..2 (1 = unchanged)
                b_factor = 1 + (bright   / 100.0)
                c_factor = 1 + (contrast / 100.0)
                if bright != 0:
                    img = ImageEnhance.Brightness(img).enhance(max(0.0, b_factor))
                if contrast != 0:
                    img = ImageEnhance.Contrast(img).enhance(max(0.0, c_factor))

            elif op_type == 'resize':
                w = int(params.get('width',  img.width))
                h = int(params.get('height', img.height))
                w = max(1, min(10000, w))
                h = max(1, min(10000, h))
                img = img.resize((w, h), PILImage.LANCZOS)

        except Exception as e:
            return JsonResponse({'message': f'Operation "{op_type}" failed: {e}'}, status=500)

    # Prepare for save
    if save_format == 'JPEG':
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = PILImage.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
    elif save_format == 'PNG':
        if img.mode not in ('RGB', 'RGBA', 'L', 'P'):
            img = img.convert('RGBA')
    elif save_format in ('WEBP',):
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
    else:
        if img.mode not in ('RGB', 'RGBA', 'L'):
            img = img.convert('RGB')

    buf = io.BytesIO()
    save_kwargs = {'format': save_format}
    if save_format in ('JPEG', 'WEBP'):
        save_kwargs['quality'] = quality

    try:
        img.save(buf, **save_kwargs)
    except Exception as e:
        return JsonResponse({'message': f'Save failed: {e}'}, status=500)

    buf.seek(0)

    ext_map = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif', 'BMP': 'bmp', 'TIFF': 'tiff'}
    ext          = ext_map.get(save_format, save_format.lower())
    base_name    = os.path.splitext(image_file.name)[0]
    out_filename = f"{base_name}_edited.{ext}"

    from django.http import HttpResponse
    ct_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
              'webp': 'image/webp', 'gif': 'image/gif', 'bmp': 'image/bmp', 'tiff': 'image/tiff'}
    content_type = ct_map.get(ext, 'application/octet-stream')

    response = HttpResponse(buf.read(), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{out_filename}"'
    return response