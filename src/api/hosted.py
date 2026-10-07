"""Vercel entrypoint.

Local ``python -m src.api`` stays on unprefixed routes. This module mounts the
same router at ``/api`` and serves the Vite build in ``web/dist``. A browser
request for a screen such as ``/projects/D1/register`` falls through to
``index.html``.

The fixture store is still process memory. A confirm, reject, edit, or settings
change lasts only as long as that instance does.
"""

from src.api.app import create_app

app = create_app(api_prefix="/api")
# A string literal, so the Vercel builder can see the Vite output directory.
app.frontend("/", directory="web/dist", fallback="index.html", check_dir=False)
