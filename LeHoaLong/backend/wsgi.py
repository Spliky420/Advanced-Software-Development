"""WSGI entry point.

    gunicorn --bind 0.0.0.0:5000 wsgi:app

The container runs gunicorn against this module; `python wsgi.py` starts the
Flask development server instead, which is handy on a laptop but is never
what the image does.
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Only the laptop path reaches here -- the container runs gunicorn against
    # `app` above and never executes this block. It defaults to 8061, the host
    # port this feature owns, because that is what the Vite dev server proxies
    # /api to (see frontend/vite.config.js). Defaulting to the container's
    # internal 5000 instead would mean `npm run dev` silently failing to reach
    # a backend that is plainly running.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8061)), debug=True)
