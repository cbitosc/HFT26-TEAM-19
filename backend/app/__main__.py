"""``python -m app`` starts the server on loopback (see .env.example for settings)."""

import logging

import uvicorn

from .config import Settings
from .main import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    settings.check_bind()
    app = create_app(settings)
    where = f"http://{settings.host}:{settings.port}"
    served = "with the built frontend" if settings.frontend_dist else "API only (run `npm run build` in frontend/ to serve the UI)"
    logging.getLogger("visionguard").info("VisionGuard on %s, %s. Adapter: %s", where, served, settings.adapter)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
