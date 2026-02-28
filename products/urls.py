from django.urls import path
from . import views

urlpatterns = [
    path('api/', views.product_list, name='product-list'),
    path('api/product/<int:pk>/', views.product_detail, name='product-detail'),
    path('add/', views.product_add, name='product-add'),
    path('edit/<int:pk>/', views.product_edit, name='product-edit'),
    path('delete/<int:pk>/', views.product_delete, name='product-delete'),
    path('', views.product_page, name='product-page'),
]
