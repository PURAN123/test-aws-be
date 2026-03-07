import os
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.http import require_http_methods
from django.core.files.base import ContentFile

from .models import ImageToPdfConversion
from .utils import images_to_pdf, MAX_SINGLE_SIZE_BYTES, MAX_TOTAL_SIZE_BYTES

ALLOWED_TYPES = [
    'image/jpeg', 'image/png', 'image/webp',
    'image/gif', 'image/bmp', 'image/tiff',
]


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


PAGE_SIZE_CHOICES = [
    ('A4', 'A4'), ('A3', 'A3'), ('LETTER', 'Letter'), ('LEGAL', 'Legal'), ('FIT', 'Fit to Image'),
]

def index(request):
    recent = ImageToPdfConversion.objects.filter(status='success').order_by('-created_at')[:5]
    return render(request, 'pdf_converter/index.html', {
        'recent_conversions': recent,
        'page_sizes': PAGE_SIZE_CHOICES,
    })


@require_http_methods(["POST"])
def convert(request):
    """
    Accept multiple images, validate, convert to PDF, save to S3 + DB.
    """
    images = request.FILES.getlist('images')

    if not images:
        return JsonResponse({'status': 'error', 'message': 'Please upload at least one image.'}, status=400)

    if len(images) > 20:
        return JsonResponse({'status': 'error', 'message': 'Maximum 20 images allowed per PDF.'}, status=400)

    # Validate each file type
    for f in images:
        if f.content_type not in ALLOWED_TYPES:
            return JsonResponse({
                'status': 'error',
                'message': f'"{f.name}" is not a supported image type. Use JPG, PNG, WEBP, GIF, BMP, or TIFF.'
            }, status=400)

    # Validate sizes
    oversized = [f.name for f in images if f.size > MAX_SINGLE_SIZE_BYTES]
    if oversized:
        return JsonResponse({
            'status': 'error',
            'message': f'These images exceed the 5 MB per-file limit: {", ".join(oversized)}'
        }, status=400)

    total_size = sum(f.size for f in images)
    if total_size > MAX_TOTAL_SIZE_BYTES:
        return JsonResponse({
            'status': 'error',
            'message': f'Total upload size is {total_size // (1024*1024)} MB. Maximum total is 20 MB.'
        }, status=400)

    # PDF options
    page_size   = request.POST.get('page_size', 'A4').upper()
    orientation = request.POST.get('orientation', 'portrait').lower()
    pdf_name    = request.POST.get('pdf_filename', 'converted').strip() or 'converted'
    # Sanitise filename
    pdf_name = ''.join(c for c in pdf_name if c.isalnum() or c in (' ', '-', '_')).strip()
    pdf_filename = f"{pdf_name}.pdf"

    if page_size not in ('A4', 'A3', 'LETTER', 'LEGAL', 'FIT'):
        page_size = 'A4'
    if orientation not in ('portrait', 'landscape'):
        orientation = 'portrait'

    # Convert
    try:
        pdf_buffer = images_to_pdf(images, page_size=page_size, orientation=orientation)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'PDF generation failed: {str(e)}'}, status=500)

    pdf_size_kb = pdf_buffer.getbuffer().nbytes // 1024
    total_kb    = total_size // 1024

    # Save to DB + S3
    try:
        record = ImageToPdfConversion(
            image_count=len(images),
            original_filenames=[f.name for f in images],
            total_original_size_kb=total_kb,
            page_size=page_size,
            orientation=orientation,
            pdf_filename=pdf_filename,
            pdf_size_kb=pdf_size_kb,
            status='success',
            ip_address=get_client_ip(request),
        )
        pdf_buffer.seek(0)
        record.pdf_file.save(pdf_filename, ContentFile(pdf_buffer.read()), save=False)
        record.save()
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Failed to save PDF: {str(e)}'}, status=500)

    return JsonResponse({
        'status': 'success',
        'message': 'PDF created successfully!',
        'conversion_id': str(record.id),
        'pdf_filename': pdf_filename,
        'image_count': len(images),
        'total_original_size_kb': total_kb,
        'pdf_size_kb': pdf_size_kb,
    })


def download(request, conversion_id):
    """Proxy PDF from S3 so the browser downloads it directly."""
    import urllib.request

    try:
        record = ImageToPdfConversion.objects.get(id=conversion_id, status='success')
    except (ImageToPdfConversion.DoesNotExist, Exception):
        raise Http404("Conversion not found.")

    try:
        file_url = record.pdf_file.url
        with urllib.request.urlopen(file_url) as s3_response:
            file_data = s3_response.read()

        response = HttpResponse(file_data, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{record.pdf_filename}"'
        return response
    except Exception as e:
        raise Http404(f"File could not be retrieved: {str(e)}")


def history(request):
    conversions = ImageToPdfConversion.objects.filter(status='success').order_by('-created_at')[:20]
    data = [{
        'id': str(c.id),
        'pdf_filename': c.pdf_filename,
        'image_count': c.image_count,
        'page_size': c.page_size,
        'orientation': c.orientation,
        'total_original_size_kb': c.total_original_size_kb,
        'pdf_size_kb': c.pdf_size_kb,
        'created_at': c.created_at.strftime('%d %b %Y, %H:%M'),
    } for c in conversions]
    return JsonResponse({'conversions': data})