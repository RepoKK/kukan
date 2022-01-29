"""kukansite URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from kukansite import settings
from django.contrib.auth import views as auth_views
from django.conf.urls import url

urlpatterns = [
    path('wtrack/', include('wtrack.urls')),
    path('', include('kukan.urls')),
    url(r'^login/$', auth_views.LoginView.as_view(), name='login'),
    url(r'^logout/$', auth_views.LogoutView.as_view(), {'next_page': 'login'}, name='logout'),
    path('admin/', admin.site.urls),
]
urlpatterns += static(settings.CERT_URL, document_root=settings.CERT_ROOT)
