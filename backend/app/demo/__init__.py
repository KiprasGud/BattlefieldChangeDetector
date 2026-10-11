"""Demo presentation layer, kept apart from the production app (docs/demo.md).

Prep mode freezes finished analysis jobs as scenes in the demo cache (store.py) through the /api/demo endpoints
(routes.py). Only the demo prep server (app.demo_app) serves them; app.main never includes them. The presentation
view reads the cache as static files and never calls the API."""
