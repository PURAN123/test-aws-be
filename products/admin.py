from django.contrib import admin
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'price', 'is_delete', 'created_at')
    list_filter = ('is_delete',)
    search_fields = ('name', 'description')
