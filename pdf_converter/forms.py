from django import forms

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

ALLOWED_CONTENT_TYPES = [
    'image/jpeg', 'image/png', 'image/webp',
    'image/gif', 'image/bmp', 'image/tiff',
]


class ImageToPdfForm(forms.Form):
    page_size = forms.ChoiceField(choices=PAGE_SIZE_CHOICES, initial='A4')
    orientation = forms.ChoiceField(choices=ORIENTATION_CHOICES, initial='portrait')
    pdf_filename = forms.CharField(
        max_length=200,
        required=False,
        initial='converted',
        help_text="Output filename (without .pdf)"
    )