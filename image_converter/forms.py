from django import forms

FORMAT_CHOICES = [
    ('', '-- Select Format --'),
    ('JPEG', 'JPG'),
    ('PNG', 'PNG'),
    ('WEBP', 'WEBP'),
    ('GIF', 'GIF'),
    ('BMP', 'BMP'),
    ('TIFF', 'TIFF'),
]

ALLOWED_CONTENT_TYPES = [
    'image/jpeg', 'image/png', 'image/webp',
    'image/gif', 'image/bmp', 'image/tiff',
]


class ImageUploadForm(forms.Form):
    image = forms.ImageField(
        label='Upload Image',
        error_messages={'required': 'Please select an image to upload.'}
    )
    target_format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        label='Convert To',
        error_messages={'required': 'Please select a target format.'}
    )
    compress_confirmed = forms.BooleanField(required=False)

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            if image.content_type not in ALLOWED_CONTENT_TYPES:
                raise forms.ValidationError("Unsupported file type. Please upload a valid image.")
        return image

    def clean_target_format(self):
        fmt = self.cleaned_data.get('target_format')
        if not fmt:
            raise forms.ValidationError("Please select a target format.")
        return fmt