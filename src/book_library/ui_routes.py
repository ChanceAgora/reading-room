"""Adapt the shared web operations to JSON and serve the built React shell."""
from __future__ import annotations

from functools import wraps
import inspect
from pathlib import Path
import re
import secrets
from typing import Any, get_type_hints

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from .ui_models import PAGE_ADAPTER, UiAction, UiBootstrap, UiError, UiResponse

COOKIE = "book_library_csrf"
NONCE_PLACEHOLDER = "__READING_ROOM_NONCE__"


def page_response(template: str, context: dict, status_code: int = 200) -> JSONResponse:
    """Validate serializable presentation data and discard template-only helpers."""
    values = {key: value for key, value in context.items() if not callable(value)}
    payload = {
        "page": template.removesuffix(".html"),
        "title": values.pop("title", "The Reading Room"),
        "nav": values.pop("nav", ""),
        "data": jsonable_encoder(values),
    }
    page = PAGE_ADAPTER.validate_python(payload)
    return JSONResponse(page.model_dump(mode="json"), status_code=status_code)


def _api_endpoint(endpoint):
    @wraps(endpoint)
    async def dispatch(*args, **kwargs):
        response = await endpoint(*args, **kwargs)
        if isinstance(response, RedirectResponse):
            return JSONResponse({"redirect": response.headers["location"]})
        return response

    # Wrapped closures belong to several modules, and may use postponed
    # annotations. Resolve them in their defining globals before registration.
    hints = get_type_hints(endpoint)
    original = inspect.signature(endpoint)
    dispatch.__signature__ = original.replace(
        parameters=[parameter.replace(annotation=hints.get(name, parameter.annotation))
                    for name, parameter in original.parameters.items()],
        return_annotation=Any,
    )
    return dispatch


def install_ui_routes(app: FastAPI, bundle_dir: Path) -> None:
    """Retain operation handlers, replace their browser GETs with the SPA shell.

    The explicit route list prevents a broad SPA fallback from concealing missing
    APIs, downloads, or static assets. Original non-UI API shapes are untouched.
    """
    original_routes = list(app.router.routes)
    app.router.routes.clear()
    public_resources = {"source_image", "work_cover", "export_citation", "export_verified_citation", "review_state"}
    public_pages: list[APIRoute] = []
    ui_routes: list[APIRoute] = []
    for route in original_routes:
        if not isinstance(route, APIRoute) or route.path.startswith("/api/"):
            app.router.routes.append(route)
            continue
        ui_routes.append(route)
        if route.name in public_resources or "GET" not in route.methods:
            app.router.routes.append(route)
        else:
            public_pages.append(route)

    @app.get("/api/ui/bootstrap", response_model=UiBootstrap)
    async def bootstrap(request: Request):
        token = request.cookies.get(COOKIE, "")
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            token = secrets.token_hex(32)
        response = JSONResponse({"csrf": token})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/")
        return response

    for route in ui_routes:
        path = "/api/ui" + route.path
        binary = route.name in {"source_image", "work_cover", "export_citation", "export_verified_citation"}
        status_only = route.path.endswith("/state")
        extra = None
        if route.methods.intersection({"POST", "PUT", "PATCH", "DELETE"}):
            extra = {
                "requestBody": {"required": True, "content": {"application/json": {"schema": UiAction.model_json_schema()}}},
                "parameters": [{"in": "header", "name": "X-CSRF-Token", "required": True, "schema": {"type": "string"}}],
            }
        app.add_api_route(
            path, _api_endpoint(route.endpoint), methods=route.methods,
            response_model=None if binary or status_only else UiResponse,
            response_class=Response if binary else JSONResponse,
            name="ui_" + route.name, operation_id="ui_" + route.name + "_" + next(iter(sorted(route.methods))).lower() + "_" + re.sub(r"\W+", "_", route.path).strip("_"),
            responses={400: {"model": UiError}, 403: {"model": UiError}, 404: {"model": UiError}, 409: {"model": UiResponse | UiError}},
            openapi_extra=extra,
        )

    # Register static resources before the explicit shell routes. Assets never
    # fall through to HTML, including before the first frontend build exists.
    if (bundle_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=bundle_dir / "assets"), name="frontend-assets")
    else:
        @app.get("/assets/{asset_path:path}", include_in_schema=False)
        async def missing_asset(asset_path: str):
            raise HTTPException(404, "That asset is not available.")

    @app.get("/reading-room-mark.svg", include_in_schema=False)
    async def frontend_mark():
        path = bundle_dir / "reading-room-mark.svg"
        if not path.is_file():
            path = Path(__file__).parent / "static" / "reading-room-mark.svg"
        if not path.is_file():
            raise HTTPException(404, "That asset is not available.")
        return FileResponse(path, media_type="image/svg+xml")

    @app.get("/theme-init.js", include_in_schema=False)
    async def theme_script():
        path = bundle_dir / "theme-init.js"
        if not path.is_file():
            raise HTTPException(404, "That asset is not available.")
        return FileResponse(path, media_type="text/javascript")

    async def shell(request: Request):
        path = bundle_dir / "index.html"
        if not path.is_file():
            return HTMLResponse(
                '<!doctype html><html lang="en"><meta charset="utf-8"><title>Build the Reading Room</title>'
                '<main><h1>The frontend needs a build</h1><p>Run <code>npm --prefix frontend run build</code> '
                'from the application directory, then reload this page.</p></main></html>', status_code=503)
        nonce = secrets.token_urlsafe(24)
        response = HTMLResponse(path.read_text(encoding="utf-8").replace(NONCE_PLACEHOLDER, nonce))
        response.headers["X-Reading-Room-Nonce"] = nonce
        return response

    for route in public_pages:
        app.add_api_route(route.path, shell, methods=["GET"], name="frontend_" + route.name, include_in_schema=False)

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        page_schema = PAGE_ADAPTER.json_schema(ref_template="#/components/schemas/{model}")
        components.update(page_schema.pop("$defs", {}))
        components["UiPage"] = page_schema
        components["UiAction"] = UiAction.model_json_schema()
        return schema

    app.openapi = openapi
