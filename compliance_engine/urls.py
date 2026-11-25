"""App-level routes are mounted from orin_config.urls; kept for reuse."""
from django.urls import path

from . import views

urlpatterns = [path("health", views.health, name="health")]
