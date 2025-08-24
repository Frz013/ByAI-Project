import os
import sys
from flask import Flask
try:
    from flask_cors import CORS
except Exception:
    def CORS(app, *args, **kwargs):
        try:
            app.logger.warning("flask_cors not installed; proceeding without CORS")
        except Exception:
            pass
        return app

# Ensure the app directory is on sys.path so sibling modules (kbbi_simple.py) can be imported reliably
try:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)
except Exception:
    pass

# Import feature blueprints
from api import health_bp, library_bp, kbbi_bp, ytdl_bp  # noqa: E402

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Register blueprints (routes remain exactly the same)
app.register_blueprint(health_bp)
app.register_blueprint(library_bp)
app.register_blueprint(kbbi_bp)
app.register_blueprint(ytdl_bp)


if __name__ == "__main__":
    # Default to port 5000
    app.run(host="0.0.0.0", port=5000, debug=True)
