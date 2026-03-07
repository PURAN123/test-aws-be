from django.contrib import admin
from .models import ImageToPdfConversion


@admin.register(ImageToPdfConversion)
class ImageToPdfConversionAdmin(admin.ModelAdmin):
    list_display = [
        'pdf_filename', 'image_count', 'page_size', 'orientation',
        'total_original_size_kb', 'pdf_size_kb', 'status', 'created_at'
    ]
    list_filter = ['status', 'page_size', 'orientation']
    search_fields = ['pdf_filename', 'ip_address']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']