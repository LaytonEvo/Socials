"""FastAPI routes.

Server-rendered, per BUILD_PLAN Section 3: Jinja2 templates and HTMX, no SPA.
Routes stay thin — they validate input, call `app.pipeline` or a query in
`app.models`, and render. Business logic does not live here.
"""
