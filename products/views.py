from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404
from django.core.paginator import Paginator, EmptyPage

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination

from .models import Product
from .serializers import ProductSerializer


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProductViewSet(viewsets.ModelViewSet):
    """
    API ViewSet for Product CRUD operations.
    Only returns non-deleted products.
    DELETE performs soft delete (sets is_delete=True).
    """
    serializer_class = ProductSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [OrderingFilter, SearchFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['id', 'name', 'price', 'created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        """Return only non-deleted products"""
        return Product.objects.filter(is_delete=False)

    def perform_destroy(self, instance):
        """Soft delete: set is_delete=True instead of actually deleting"""
        instance.is_delete = True
        instance.save()

    @action(detail=False, methods=['get'])
    def deleted(self, request):
        """Endpoint to view deleted (soft-deleted) products"""
        deleted_products = Product.objects.filter(is_delete=True)
        page = self.paginate_queryset(deleted_products)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(deleted_products, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """Restore a soft-deleted product"""
        product = get_object_or_404(Product, pk=pk)
        if not product.is_delete:
            return Response(
                {'detail': 'Product is not deleted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        product.is_delete = False
        product.save()
        serializer = self.get_serializer(product)
        return Response(serializer.data)


# HTML Views (Server-rendered pages - unchanged)
def product_page(request):
    # Server-rendered page showing non-deleted products with pagination and sorting
    page = request.GET.get('page', '1')
    page_size = request.GET.get('page_size', '10')
    sort_by = request.GET.get('sort', 'created_at')
    sort_dir = request.GET.get('dir', 'desc')
    
    try:
        page = int(page)
        page_size = int(page_size)
    except ValueError:
        page = 1
        page_size = 10

    # Validate sort parameters
    valid_sorts = ['id', 'name', 'price', 'created_at']
    if sort_by not in valid_sorts:
        sort_by = 'created_at'
    if sort_dir not in ['asc', 'desc']:
        sort_dir = 'desc'

    # Build order_by string
    order_prefix = '' if sort_dir == 'asc' else '-'
    order_by = f'{order_prefix}{sort_by}'

    qs = Product.objects.filter(is_delete=False).order_by(order_by)
    paginator = Paginator(qs, page_size)
    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = paginator.page(1)

    # Pre-compute sort URLs for template
    sort_urls = {}
    for field in valid_sorts:
        new_dir = 'asc' if sort_by == field and sort_dir == 'desc' else 'desc'
        sort_urls[field] = f'?sort={field}&dir={new_dir}&page=1'

    return render(request, 'products/list.html', {
        'page_obj': page_obj,
        'paginator': paginator,
        'sort_by': sort_by,
        'sort_dir': sort_dir,
        'sort_urls': sort_urls,
    })


def product_add(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        price = request.POST.get('price')
        description = request.POST.get('description', '')
        image = request.FILES.get('image')
        if not name or not price:
            return render(request, 'products/add.html', {'error': 'Name and price are required', 'name': name, 'price': price, 'description': description})
        p = Product.objects.create(name=name, price=price, description=description, image=image)
        return redirect('product-page')
    return render(request, 'products/add.html')


def product_edit(request, pk):
    p = get_object_or_404(Product, pk=pk)
    if p.is_delete:
        raise Http404('Product not found')
    if request.method == 'POST':
        print(request.FILES)
        name = request.POST.get('name')
        price = request.POST.get('price')
        description = request.POST.get('description', '')
        image = request.FILES.get('image')
        print('image', image)

        if name:
            p.name = name
        if price:
            p.price = price
        if image:
            p.image = image
        p.description = description
        p.save()
        return redirect('product-page')
    return render(request, 'products/edit.html', {'product': p})


def product_delete(request, pk):
    p = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        p.is_delete = True
        p.save()
        return redirect('product-page')
    return render(request, 'products/delete.html', {'product': p})

