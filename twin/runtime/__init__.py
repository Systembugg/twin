"""Deployment layer: queue, workers, HTTP API, rate limits.

Importing this package does not pull in FastAPI or redis — import the
submodules directly so the core harness stays dependency-light.
"""
