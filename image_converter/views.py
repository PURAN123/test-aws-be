import os
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.views.decorators.http import require_http_methods

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


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# ─────────────────────────────────────────────
# Format Converter  (/converter/)
# ─────────────────────────────────────────────

def index(request):
    """Render the main format converter page."""
    form = ImageUploadForm()
    recent_conversions = ImageConversion.objects.filter(status='success').order_by('-created_at')[:5]
    return render(request, 'image_converter/index.html', {
        'form': form,
        'recent_conversions': recent_conversions,
    })


@require_http_methods(["POST"])
def convert(request):
    """
    Convert an image from one format to another.
    Saves original + converted file to S3, saves a DB record.
    Returns JSON with conversion_id for subsequent download/edit.
    """
    form = ImageUploadForm(request.POST, request.FILES)

    if not form.is_valid():
        errors = {field: error[0] for field, error in form.errors.items()}
        return JsonResponse({'status': 'error', 'errors': errors}, status=400)

    image_file      = request.FILES['image']
    target_format   = form.cleaned_data['target_format']
    compress_confirmed = form.cleaned_data.get('compress_confirmed', False)

    # Detect real format via magic bytes
    try:
        detected_format = get_image_format(image_file)
    except Exception:
        return JsonResponse({
            'status': 'error',
            'message': 'Could not read the image file. Please upload a valid image.'
        }, status=400)

    if detected_format == 'JPG':
        detected_format = 'JPEG'

    # Same format guard
    if detected_format == target_format:
        return JsonResponse({
            'status': 'warning',
            'message': f'Your image is already in {target_format} format. Please choose a different format.'
        }, status=200)

    # Size check
    file_size        = get_file_size_bytes(image_file)
    original_size_kb = file_size // 1024
    was_compressed   = False
    compressed_size_kb = None

    if file_size > MAX_SIZE_BYTES:
        if not compress_confirmed:
            return JsonResponse({
                'status': 'size_exceeded',
                'message': f'Your image is {original_size_kb / 1024:.1f} MB which exceeds the 5 MB limit. Would you like to compress it before converting?',
                'size_mb': round(file_size / (1024 * 1024), 2),
            }, status=200)
        try:
            image_file         = compress_image(image_file, target_format=detected_format)
            compressed_size_kb = image_file.getbuffer().nbytes // 1024
            was_compressed     = True
        except ValueError as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    # Convert
    try:
        converted_buffer = convert_image(image_file, target_format)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Conversion failed: {str(e)}'}, status=500)

    converted_size_kb  = converted_buffer.getbuffer().nbytes // 1024
    original_filename  = request.FILES['image'].name
    converted_filename = get_converted_filename(original_filename, target_format)

    # Save to DB + S3
    try:
        image_file.seek(0)
        record = ImageConversion(
            original_filename  = original_filename,
            original_format    = detected_format,
            original_size_kb   = original_size_kb,
            was_compressed     = was_compressed,
            compressed_size_kb = compressed_size_kb if was_compressed else None,
            requested_format   = target_format,
            converted_size_kb  = converted_size_kb,
            status             = 'success',
            ip_address         = get_client_ip(request),
        )
        original_content = ContentFile(image_file.read() if hasattr(image_file, 'read') else image_file.getvalue())
        record.original_file.save(original_filename, original_content, save=False)

        converted_buffer.seek(0)
        converted_content = ContentFile(converted_buffer.read())
        record.converted_file.save(converted_filename, converted_content, save=False)

        record.save()
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Failed to save files: {str(e)}'}, status=500)

    try:
        download_url = record.converted_file.url
    except Exception:
        download_url = None

    return JsonResponse({
        'status'            : 'success',
        'message'           : 'Image converted successfully!',
        'conversion_id'     : str(record.id),
        'original_filename' : original_filename,
        'converted_filename': converted_filename,
        'original_format'   : detected_format,
        'converted_format'  : target_format,
        'original_size_kb'  : original_size_kb,
        'converted_size_kb' : converted_size_kb,
        'was_compressed'    : was_compressed,
        'download_url'      : download_url,
    })


def download(request, conversion_id):
    """
    Proxy the S3 converted file back through Django so the browser
    triggers a download instead of redirecting to the raw S3 URL.
    """
    import urllib.request
    from django.http import HttpResponse, Http404

    try:
        record = ImageConversion.objects.get(id=conversion_id, status='success')
    except (ImageConversion.DoesNotExist, Exception):
        raise Http404("Conversion not found.")

    try:
        file_url = record.converted_file.url
        with urllib.request.urlopen(file_url) as s3_response:
            file_data = s3_response.read()

        ext = os.path.splitext(record.converted_file.name)[-1].lower()
        content_type_map = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png',  '.webp': 'image/webp',
            '.gif': 'image/gif',  '.bmp':  'image/bmp',
            '.tiff': 'image/tiff','.tif':  'image/tiff',
        }
        content_type = content_type_map.get(ext, 'application/octet-stream')
        filename     = os.path.basename(record.converted_file.name)

        response = HttpResponse(file_data, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        from django.http import Http404
        raise Http404(f"File could not be retrieved: {str(e)}")


@require_http_methods(["POST"])
def process(request, conversion_id):
    """
    Legacy post-conversion single-operation endpoint.
    Fetches converted file from S3, applies one operation, streams result.
    Does NOT save a new DB record.
    """
    import urllib.request
    from django.http import HttpResponse, Http404
    import io

    try:
        record = ImageConversion.objects.get(id=conversion_id, status='success')
    except (ImageConversion.DoesNotExist, Exception):
        raise Http404("Conversion not found.")

    operation = request.POST.get('operation', 'none')

    try:
        file_url = record.converted_file.url
        with urllib.request.urlopen(file_url) as s3_resp:
            file_bytes = s3_resp.read()
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Could not fetch file: {str(e)}'}, status=500)

    file_obj = io.BytesIO(file_bytes)

    ext = os.path.splitext(record.converted_file.name)[-1].lower()
    content_type_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png',  '.webp': 'image/webp',
        '.gif': 'image/gif',  '.bmp':  'image/bmp',
        '.tiff': 'image/tiff','.tif':  'image/tiff',
    }
    content_type = content_type_map.get(ext, 'application/octet-stream')
    base_name    = os.path.splitext(record.converted_file.name.split('/')[-1])[0]

    try:
        if operation == 'none':
            result_buf = file_obj

        elif operation == 'crop':
            left   = int(request.POST.get('left',   0))
            top    = int(request.POST.get('top',    0))
            right  = int(request.POST.get('right',  0))
            bottom = int(request.POST.get('bottom', 0))
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
            result_buf = resize_image(file_obj, width=width, height=height, keep_ratio=keep)
            base_name  = f"{base_name}_resized"

        elif operation == 'rotate':
            degrees = int(request.POST.get('degrees', 90))
            result_buf = rotate_image(file_obj, degrees=degrees)
            base_name  = f"{base_name}_rotated{degrees}"

        elif operation == 'flip':
            direction = request.POST.get('direction', 'horizontal')
            result_buf = flip_image(file_obj, direction=direction)
            base_name  = f"{base_name}_flipped"

        elif operation == 'grayscale':
            result_buf = grayscale_image(file_obj)
            base_name  = f"{base_name}_grayscale"

        elif operation == 'compress':
            quality    = int(request.POST.get('quality', 60))
            result_buf = compress_image_quality(file_obj, quality=quality)
            base_name  = f"{base_name}_compressed"

        else:
            return JsonResponse({'status': 'error', 'message': f'Unknown operation: {operation}'}, status=400)

    except ValueError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Operation failed: {str(e)}'}, status=500)

    result_buf.seek(0)
    response = HttpResponse(result_buf.read(), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{base_name}{ext}"'
    return response


def history(request):
    """Return recent conversion history as JSON."""
    conversions = ImageConversion.objects.filter(status='success').order_by('-created_at')[:20]
    data = [{
        'id'               : str(c.id),
        'original_filename': c.original_filename,
        'original_format'  : c.original_format,
        'requested_format' : c.requested_format,
        'original_size_kb' : c.original_size_kb,
        'converted_size_kb': c.converted_size_kb,
        'was_compressed'   : c.was_compressed,
        'created_at'       : c.created_at.strftime('%d %b %Y, %H:%M'),
    } for c in conversions]
    return JsonResponse({'conversions': data})


# ─────────────────────────────────────────────
# Image Editor  (/converter/edit/)
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# Image Compressor  (/converter/compress/)
# ─────────────────────────────────────────────

def compress_view(request):
    """Render the standalone image compressor page."""
    return render(request, 'image_converter/compress.html')


@require_http_methods(["POST"])
def compress_image_view(request):
    """
    POST params:
      image         — uploaded file
      mode          — 'quality' | 'target'
      quality       — int 1-95        (quality mode)
      target_kb     — int > 0         (target mode)
      output_format — 'original' | 'JPEG' | 'PNG' | 'WEBP'

    Returns JSON with size stats + a temporary download token (the record id).
    File is streamed on /converter/compress/download/<id>/
    """
    from .utils import (
        get_image_format, compress_image_quality_fmt,
        compress_to_target_size, FORMAT_EXTENSION_MAP,
    )
    from django.core.files.base import ContentFile
    from .models import ImageConversion   # reuse existing model to store files

    image_file = request.FILES.get('image')
    if not image_file:
        return JsonResponse({'status': 'error', 'message': 'No image uploaded.'}, status=400)

    MAX_COMPRESS_BYTES = 20 * 1024 * 1024
    if image_file.size > MAX_COMPRESS_BYTES:
        return JsonResponse({'status': 'error', 'message': 'File too large — max 20 MB.'}, status=400)

    try:
        detected = get_image_format(image_file)
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Cannot read image file.'}, status=400)
    if detected == 'JPG':
        detected = 'JPEG'

    original_size_kb  = image_file.size // 1024
    original_filename = image_file.name

    mode           = request.POST.get('mode', 'quality')
    output_fmt_raw = request.POST.get('output_format', 'original')
    output_format  = None if output_fmt_raw == 'original' else output_fmt_raw.upper()

    quality_used = None

    try:
        if mode == 'target':
            target_kb = int(request.POST.get('target_kb', 100))
            if target_kb < 1:
                return JsonResponse({'status': 'error', 'message': 'Target must be ≥ 1 KB.'}, status=400)
            compressed_buf, quality_used, save_format = compress_to_target_size(
                image_file, target_kb=target_kb, output_format=output_format
            )
        else:
            quality = max(1, min(95, int(request.POST.get('quality', 75))))
            compressed_buf, save_format = compress_image_quality_fmt(
                image_file, quality=quality, output_format=output_format
            )
            quality_used = quality
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Compression failed: {e}'}, status=500)

    compressed_size_kb = compressed_buf.getbuffer().nbytes // 1024
    ext      = FORMAT_EXTENSION_MAP.get(save_format, save_format.lower())
    out_name = f"{os.path.splitext(original_filename)[0]}_compressed.{ext}"

    # Piggyback on ImageConversion model — store as a "compress" record
    # requested_format = save_format, original_format = detected
    try:
        image_file.seek(0)
        record = ImageConversion(
            original_filename = original_filename,
            original_format   = detected,
            original_size_kb  = original_size_kb,
            requested_format  = save_format,
            converted_size_kb = compressed_size_kb,
            was_compressed    = True,
            compressed_size_kb= compressed_size_kb,
            status            = 'success',
            ip_address        = get_client_ip(request),
        )
        record.original_file.save(original_filename, ContentFile(image_file.read()), save=False)
        compressed_buf.seek(0)
        record.converted_file.save(out_name, ContentFile(compressed_buf.read()), save=False)
        record.save()
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Failed to save: {e}'}, status=500)

    saving_kb  = original_size_kb - compressed_size_kb
    saving_pct = round((1 - compressed_size_kb / original_size_kb) * 100, 1) if original_size_kb else 0

    return JsonResponse({
        'status'            : 'success',
        'compression_id'    : str(record.id),
        'original_filename' : original_filename,
        'out_filename'      : out_name,
        'original_size_kb'  : original_size_kb,
        'compressed_size_kb': compressed_size_kb,
        'saving_kb'         : saving_kb,
        'saving_pct'        : saving_pct,
        'quality_used'      : quality_used,
        'output_format'     : save_format,
        'larger'            : compressed_size_kb >= original_size_kb,
    })


def compress_download(request, compression_id):
    """Download the compressed file — proxied through Django (same as main download view)."""
    import urllib.request as urllib_req
    from django.http import Http404
    from .models import ImageConversion

    try:
        record = ImageConversion.objects.get(id=compression_id, status='success')
    except (ImageConversion.DoesNotExist, Exception):
        raise Http404("Not found.")

    try:
        url = record.converted_file.url
        with urllib_req.urlopen(url) as r:
            data = r.read()
        ext = os.path.splitext(record.converted_file.name)[-1].lower()
        ct_map = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png',
                  '.webp':'image/webp','.gif':'image/gif','.bmp':'image/bmp','.tiff':'image/tiff'}
        ct   = ct_map.get(ext, 'application/octet-stream')
        name = os.path.basename(record.converted_file.name)
        from django.http import HttpResponse
        resp = HttpResponse(data, content_type=ct)
        resp['Content-Disposition'] = f'attachment; filename="{name}"'
        return resp
    except Exception as e:
        from django.http import Http404
        raise Http404(f"Could not retrieve file: {e}")


def edit_view(request):
    """Render the standalone image editor page."""
    return render(request, 'image_converter/editor.html')


@require_http_methods(["POST"])
def edit_apply(request):
    """
    Accepts:
      - image  : the image file (original upload or post-conversion blob)
      - ops    : JSON array of {type, params} operations in order
      - format : 'original' | 'JPEG' | 'PNG' | 'WEBP'
      - quality: 1–100 (applies to JPEG/WEBP)

    Replays all ops server-side with Pillow at full resolution.
    Returns the final image as an attachment download.
    No DB record is saved.
    """
    from PIL import Image as PILImage, ImageOps, ImageEnhance
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

    # Replay each operation in order
    for op in ops:
        op_type = op.get('type')
        params  = op.get('params', {})
        try:
            if op_type == 'crop':
                left   = max(0, min(int(params.get('left',   0)), img.width))
                top    = max(0, min(int(params.get('top',    0)), img.height))
                right  = max(0, min(int(params.get('right',  img.width)),  img.width))
                bottom = max(0, min(int(params.get('bottom', img.height)), img.height))
                if right > left and bottom > top:
                    img = img.crop((left, top, right, bottom))

            elif op_type == 'flip':
                if params.get('direction') == 'horizontal':
                    img = ImageOps.mirror(img)
                else:
                    img = ImageOps.flip(img)

            elif op_type == 'rotate':
                img = img.rotate(-int(params.get('degrees', 90)), expand=True)

            elif op_type == 'grayscale':
                img = img.convert('L').convert('RGB')

            elif op_type == 'brightness':
                bright   = float(params.get('brightness', 0))
                contrast = float(params.get('contrast',   0))
                if bright != 0:
                    img = ImageEnhance.Brightness(img).enhance(max(0.0, 1 + bright / 100.0))
                if contrast != 0:
                    img = ImageEnhance.Contrast(img).enhance(max(0.0, 1 + contrast / 100.0))

            elif op_type == 'resize':
                w = max(1, min(10000, int(params.get('width',  img.width))))
                h = max(1, min(10000, int(params.get('height', img.height))))
                img = img.resize((w, h), PILImage.LANCZOS)

        except Exception as e:
            return JsonResponse({'message': f'Operation "{op_type}" failed: {e}'}, status=500)

    # Mode normalisation before save
    if save_format == 'JPEG':
        if img.mode in ('RGBA', 'LA', 'P'):
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg = PILImage.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
    elif save_format == 'PNG':
        if img.mode not in ('RGB', 'RGBA', 'L', 'P'):
            img = img.convert('RGBA')
    elif save_format == 'WEBP':
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
    else:
        if img.mode not in ('RGB', 'RGBA', 'L'):
            img = img.convert('RGB')

    buf         = io.BytesIO()
    save_kwargs = {'format': save_format}
    if save_format in ('JPEG', 'WEBP'):
        save_kwargs['quality'] = quality

    try:
        img.save(buf, **save_kwargs)
    except Exception as e:
        return JsonResponse({'message': f'Save failed: {e}'}, status=500)

    buf.seek(0)

    ext_map      = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif', 'BMP': 'bmp', 'TIFF': 'tiff'}
    ext          = ext_map.get(save_format, save_format.lower())
    base_name    = os.path.splitext(image_file.name)[0]
    out_filename = f"{base_name}_edited.{ext}"

    from django.http import HttpResponse
    ct_map = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
        'webp': 'image/webp', 'gif': 'image/gif', 'bmp': 'image/bmp', 'tiff': 'image/tiff',
    }
    response = HttpResponse(buf.read(), content_type=ct_map.get(ext, 'application/octet-stream'))
    response['Content-Disposition'] = f'attachment; filename="{out_filename}"'
    return response