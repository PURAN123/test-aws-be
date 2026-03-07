from django.contrib import admin
from .models import ImageConversion


@admin.register(ImageConversion)
class ImageConversionAdmin(admin.ModelAdmin):
    list_display = [
        'original_filename', 'original_format', 'requested_format',
        'status', 'original_size_kb', 'converted_size_kb',
        'was_compressed', 'created_at'
    ]
    list_filter = ['status', 'original_format', 'requested_format', 'was_compressed']
    search_fields = ['original_filename', 'ip_address']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']