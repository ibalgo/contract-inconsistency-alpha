"""AlphaAgent — main entry point.

Usage:
    python main.py           # run pipeline once
    python main.py --serve   # start API server
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def run_pipeline() -> None:
    """Run the full agentic pipeline once."""
    from alphaagent.db.session import create_tables
    from alphaagent.agents.scout import run_scout

    create_tables()
    await run_scout()


def serve() -> None:
    """Start the FastAPI server."""
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    import spacy

    from alphaagent.db.session import create_tables
    from alphaagent.api.routes import router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        create_tables()
        # Verify spacy model is available
        try:
            spacy.load("en_core_web_sm")
        except OSError:
            logger.error(
                "spaCy model 'en_core_web_sm' not found. "
                "Run: python -m spacy download en_core_web_sm"
            )
            sys.exit(1)
        yield

    app = FastAPI(title="AlphaAgent", lifespan=lifespan)
    app.include_router(router)

    uvicorn.run(app, host="0.0.0.0", port=8000)


def main() -> None:
    parser = argparse.ArgumentParser(description="AlphaAgent")
    parser.add_argument("--serve", action="store_true", help="Start the API server")
    args = parser.parse_args()

    if args.serve:
        serve()
    else:
        asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
