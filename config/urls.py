
from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.http import JsonResponse, Http404
from django.views.static import serve as static_serve
from pathlib import PurePosixPath
from django.contrib.auth import views as auth_views


def health(request):
    return JsonResponse({
        "status": "ok",
        "service": "MedMitra"
    })


# Customize Django Admin headings
admin.site.site_header = "MedMitra Pharmacy Management"
admin.site.site_title = "MedMitra Administration"
admin.site.index_title = "Medicine catalogue, orders and inventory"


urlpatterns = [
    # Admin panel
    path("admin/", admin.site.urls),

    # User profiles
    path("profile/", include("profiles.urls")),

    # Pharmacy marketplace, account management and store inventory
    path("", include("marketplace.urls")),
    path("accounts/", include("accounts.urls")),
    path("pharmacy/", include("pharmacy.urls")),

    # Health check
    path("health/", health, name="health"),

    # Authentication
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html"
        ),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),

    # Password reset
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset.html"
        ),
        name="password_reset",
    ),
]

# Serve public media only in local development. Prescription files are stored under
# MEDIA_ROOT/private_prescriptions and must never be exposed by a generic media URL.
def safe_development_media(request, path):
    normalized_parts = PurePosixPath(path.replace("\\", "/")).parts
    if not normalized_parts or normalized_parts[0] == "private_prescriptions" or ".." in normalized_parts:
        raise Http404("Media file not found")
    return static_serve(request, path, document_root=settings.MEDIA_ROOT)


if settings.DEBUG:
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", safe_development_media)]
