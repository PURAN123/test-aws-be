from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# DRF Router for API endpoints
router = DefaultRouter()
router.register(r'products', views.ProductViewSet, basename='product')

urlpatterns = [
    # API routes with /api/ prefix
    path('api/', include(router.urls)),
    
    # HTML views
    path('', views.product_page, name='product-page'),
    path('add/', views.product_add, name='product-add'),
    path('<int:pk>/', views.product_edit, name='product-edit'),
    path('<int:pk>/delete/', views.product_delete, name='product-delete'),

]
