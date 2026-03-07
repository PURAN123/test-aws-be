from django.db import models
import uuid


class ImageToPdfConversion(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    PAGE_SIZE_CHOICES = [
        ('A4', 'A4'),
        ('A3', 'A3'),
        ('LETTER', 'Letter'),
        ('LEGAL', 'Legal'),
        ('FIT', 'Fit to Image'),
    ]

    ORIENTATION_CHOICES = [
        ('portrait', 'Portrait'),
        ('landscape', 'Landscape'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # What user uploaded (multiple images stored as JSON list of S3 paths)
    image_count = models.PositiveIntegerField(default=1)
    original_filenames = models.JSONField(default=list, help_text="List of original filenames in order")
    total_original_size_kb = models.PositiveIntegerField(help_text="Total size of all uploaded images in KB")

    # PDF options user chose
    page_size = models.CharField(max_length=10, choices=PAGE_SIZE_CHOICES, default='A4')
    orientation = models.CharField(max_length=10, choices=ORIENTATION_CHOICES, default='portrait')
    pdf_filename = models.CharField(max_length=255, default='converted.pdf')

    # Output
    pdf_file = models.FileField(upload_to='pdf_conversions/%Y/%m/%d/', null=True, blank=True)
    pdf_size_kb = models.PositiveIntegerField(null=True, blank=True)

    # Status
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    # Meta
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Image to PDF Conversion'
        verbose_name_plural = 'Image to PDF Conversions'

    def __str__(self):
        return f"{self.image_count} image(s) → {self.pdf_filename} ({self.status})"