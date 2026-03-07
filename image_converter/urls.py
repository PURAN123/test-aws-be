from django.urls import path
from . import views

app_name = 'image_converter'

urlpatterns = [
    path('', views.index, name='index'),
    path('convert/', views.convert, name='convert'),
    path('download/<str:conversion_id>/', views.download, name='download'),
    path('process/<str:conversion_id>/', views.process, name='process'),
    path('history/', views.history, name='history'),
    # Standalone image editor
    path('edit/', views.edit_view, name='edit'),
    path('edit/apply/', views.edit_apply, name='edit_apply'),
    # Image compressor
    path('compress/', views.compress_view, name='compress'),
    path('compress/run/', views.compress_image_view, name='compress_run'),
    path('compress/download/<str:compression_id>/', views.compress_download, name='compress_download'),
]