from django.contrib import admin
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from strawberry.django.views import GraphQLView

from compliance_engine import views
from compliance_engine.schema import schema


class OrinGraphQLView(GraphQLView):
    """GraphiQL in the browser + the same endpoint the demo UI posts to."""

    graphql_ide = "graphiql"
    allow_queries_via_get = True


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.index, name="index"),
    path("health", views.health, name="health"),
    path("graphql", csrf_exempt(OrinGraphQLView.as_view(schema=schema))),
]
