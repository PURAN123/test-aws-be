import json
from django.http import JsonResponse, HttpResponseNotAllowed, HttpResponseBadRequest, Http404
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator, EmptyPage
from django.shortcuts import render, redirect, get_object_or_404

from .models import Product


def serialize_product(p: Product) -> dict:
    return {
        'id': p.id,
        'name': p.name,
        'price': str(p.price),
        'description': p.description,
        'is_delete': p.is_delete,
        'created_at': p.created_at.isoformat(),
        'updated_at': p.updated_at.isoformat(),
    }


@csrf_exempt
def product_list(request):
    if request.method == 'GET':
        page = request.GET.get('page', '1')
        page_size = request.GET.get('page_size', '10')
        try:
            page = int(page)
            page_size = int(page_size)
        except ValueError:
            return HttpResponseBadRequest('Invalid pagination parameters')

        qs = Product.objects.filter(is_delete=False).order_by('-created_at')
        paginator = Paginator(qs, page_size)
        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            return JsonResponse({'products': [], 'page': page, 'page_size': page_size, 'total_pages': paginator.num_pages, 'total_items': paginator.count})

        products = [serialize_product(p) for p in page_obj.object_list]
        return JsonResponse({
            'products': products,
            'page': page,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
            'total_items': paginator.count,
        })
    elif request.method == 'POST':
        try:
            data = json.loads(request.body.decode() or '{}')
        except json.JSONDecodeError:
            return HttpResponseBadRequest('Invalid JSON')
        name = data.get('name')
        price = data.get('price')
        description = data.get('description', '')
        if name is None or price is None:
            return HttpResponseBadRequest('`name` and `price` are required')
        try:
            p = Product.objects.create(name=name, price=price, description=description)
        except Exception as e:
            return HttpResponseBadRequest(str(e))
        return JsonResponse(serialize_product(p), status=201)
    else:
        return HttpResponseNotAllowed(['GET', 'POST'])


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
        if not name or not price:
            return render(request, 'products/add.html', {'error': 'Name and price are required', 'name': name, 'price': price, 'description': description})
        p = Product.objects.create(name=name, price=price, description=description)
        return redirect('product-page')
    return render(request, 'products/add.html')


def product_edit(request, pk):
    p = get_object_or_404(Product, pk=pk)
    if p.is_delete:
        raise Http404('Product not found')
    if request.method == 'POST':
        name = request.POST.get('name')
        price = request.POST.get('price')
        description = request.POST.get('description', '')
        if name:
            p.name = name
        if price:
            p.price = price
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


@csrf_exempt
def product_detail(request, pk):
    try:
        p = Product.objects.get(pk=pk)
    except Product.DoesNotExist:
        raise Http404('Product not found')
    if request.method == 'GET':
        if p.is_delete:
            raise Http404('Product not found')
        return JsonResponse(serialize_product(p))
    elif request.method in ('PUT', 'PATCH'):
        try:
            data = json.loads(request.body.decode() or '{}')
        except json.JSONDecodeError:
            return HttpResponseBadRequest('Invalid JSON')
        name = data.get('name')
        price = data.get('price')
        description = data.get('description')
        if name is not None:
            p.name = name
        if price is not None:
            p.price = price
        if description is not None:
            p.description = description
        p.save()
        return JsonResponse(serialize_product(p))
    elif request.method == 'DELETE':
        p.is_delete = True
        p.save()
        return JsonResponse({'status': 'deleted'})
    else:
        return HttpResponseNotAllowed(['GET', 'PUT', 'PATCH', 'DELETE'])
