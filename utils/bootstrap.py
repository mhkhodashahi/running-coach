"""Compatibility wrappers for application bootstrap services."""

from __future__ import annotations

from services.training_context_service import AppBootstrapService, TrainingBundle, bootstrap_app, load_training_bundle

__all__ = ["AppBootstrapService", "TrainingBundle", "bootstrap_app", "load_training_bundle"]
