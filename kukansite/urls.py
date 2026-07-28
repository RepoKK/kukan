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
# `from django.conf import settings`, not `from kukansite import settings`:
# the latter imported the settings module directly, bypassing Django's lazy
# settings object and breaking the moment settings became a package.
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path

urlpatterns = [
    path('bustime/', include('bustime.urls')),
    path('', include('kukan.urls')),
    re_path(r'^login/$', auth_views.LoginView.as_view(), name='login'),
    re_path(r'^logout/$', auth_views.LogoutView.as_view(),
            {'next_page': 'login'}, name='logout'),
    path('admin/', admin.site.urls),
    path('tempmon/', include('tempmon.urls')),
]
urlpatterns += static(settings.CERT_URL, document_root=settings.CERT_ROOT)
