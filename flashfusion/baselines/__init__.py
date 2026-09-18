"""Flash-Fusion baselines package.

``run_llmsense_paper`` is resolved lazily. Importing it eagerly here made the
package import ``pipeline.runner``, which now imports ``flash_fusion_policy``
from this package — a cycle. Every baseline module is still importable by its
own path, and the attribute below keeps ``from flashfusion.baselines import
run_llmsense_paper`` working.
"""

from typing import Any

__all__ = ["run_llmsense_paper"]


def __getattr__(name: str) -> Any:
    if name == "run_llmsense_paper":
        from flashfusion.baselines.llmsense_paper import run_llmsense_paper

        return run_llmsense_paper
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
