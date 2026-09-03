"""WSGI entry point.

    gunicorn --bind 0.0.0.0:5000 wsgi:app

The container runs gunicorn against this module; `python wsgi.py` starts the
Flask development server instead, which is handy on a laptop but is never
what the image does.
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
