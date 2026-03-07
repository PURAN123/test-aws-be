from django.db import models
import uuid


class ImageConversion(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    FORMAT_CHOICES = [
        ('JPEG', 'JPG'),
        ('PNG', 'PNG'),
        ('WEBP', 'WEBP'),
        ('GIF', 'GIF'),
        ('BMP', 'BMP'),
        ('TIFF', 'TIFF'),
    ]

    # What user uploaded
    original_file = models.FileField(upload_to='image_converter/original/%Y/%m/%d/')
    original_filename = models.CharField(max_length=255)
    original_format = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    original_size_kb = models.PositiveIntegerField(help_text="Size in KB")
    was_compressed = models.BooleanField(default=False)
    compressed_size_kb = models.PositiveIntegerField(null=True, blank=True)

    # What user requested
    requested_format = models.CharField(max_length=10, choices=FORMAT_CHOICES)

    # What we returned
    converted_file = models.FileField(
        upload_to='image_converter/output/%Y/%m/%d/',
        null=True, blank=True
    )
    converted_size_kb = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    # Meta
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Image Conversion'
        verbose_name_plural = 'Image Conversions'

    def __str__(self):
        return f"{self.original_filename} → {self.requested_format} ({self.status})"

    @property
    def size_saved_kb(self):
        if self.original_size_kb and self.converted_size_kb:
            return self.original_size_kb - self.converted_size_kb
        return None