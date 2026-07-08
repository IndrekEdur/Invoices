from django.contrib import admin
from django.urls import include, path

from apps.core.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    path("workspace/", include("apps.workspace.urls")),
]
