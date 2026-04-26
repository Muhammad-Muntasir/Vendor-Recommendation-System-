"""
AWS Lambda entry point.

Bootstraps:
1. sys.path — adds /var/task/vendor so bundled packages (requests, etc.) are importable
2. backend.lambda.* stub packages — maps importlib paths to actual modules at /var/task
"""

from __future__ import annotations
import os
import sys
import types


def _bootstrap():
    task_dir = os.path.dirname(os.path.abspath(__file__))

    # Add vendor directory to path so bundled packages are importable
    vendor_dir = os.path.join(task_dir, "vendor")
    if vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)

    if "backend" in sys.modules:
        return

    # Stub 'backend' package
    backend = types.ModuleType("backend")
    backend.__path__ = [os.path.join(task_dir, "_stub")]
    backend.__package__ = "backend"
    sys.modules["backend"] = backend

    # Stub 'backend.lambda' → /var/task
    bl = types.ModuleType("backend.lambda")
    bl.__path__ = [task_dir]
    bl.__package__ = "backend.lambda"
    sys.modules["backend.lambda"] = bl

    # Stub all sub-packages
    for subpkg in ["handlers", "models", "services", "utils"]:
        m = types.ModuleType(f"backend.lambda.{subpkg}")
        m.__path__ = [os.path.join(task_dir, subpkg)]
        m.__package__ = f"backend.lambda.{subpkg}"
        sys.modules[f"backend.lambda.{subpkg}"] = m


_bootstrap()

import importlib  # noqa: E402


def lambda_handler(event: dict, context) -> dict:
    router = importlib.import_module("backend.lambda.router")
    return router.route(event, context)
