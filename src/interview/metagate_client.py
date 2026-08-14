"""InterView's binding to the shared MetaGate bootstrap client.

The client lives in the LegiVellum shared package so the gates do not each grow
their own copy. All this module contributes is the one genuinely
InterView-specific thing: which primitive types map to which settings.

Loading is by file path rather than `from legivellum.metagate_bootstrap import
...` on purpose. That statement executes legivellum/__init__.py, which pulls in
the control plane's dependency tree (ulid, sqlalchemy, fastapi) that a gate has
no reason to install. The bootstrap client itself needs only httpx, which every
gate already has, so it is loaded as a standalone module.

The load is best-effort: a gate must start whether or not a LegiVellum checkout
is beside it, consistent with bootstrap never being allowed to block startup.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SHARED_RELPATH = Path("LegiVellum") / "shared" / "legivellum" / "metagate_bootstrap.py"

# (primitive type in the manifest, settings attribute it fills)
_BINDING_SPECS: tuple[tuple[str, str], ...] = (
    ("receiptgate", "receiptgate_url"),
    ("asyncgate", "asyncgate_url"),
    ("depotgate", "depotgate_url"),
)

COMPONENT_KEY = "interview"


def _load_shared_bootstrap() -> Optional[ModuleType]:
    """Load the shared client as a standalone module, or return None."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _SHARED_RELPATH
        if not candidate.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                "legivellum_metagate_bootstrap", candidate
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            # Register before executing: @dataclass resolves annotations via
            # sys.modules[cls.__module__], which is None for a module loaded by
            # path alone, and fails with "'NoneType' object has no attribute
            # '__dict__'".
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as exc:  # noqa: BLE001 - never block startup
            logger.warning("metagate_bootstrap_load_failed path=%s error=%s", candidate, exc)
            return None
    return None


_shared = _load_shared_bootstrap()

BOOTSTRAP_BINDINGS = (
    tuple(
        _shared.EndpointBinding(primitive_type=ptype, setting=setting)
        for ptype, setting in _BINDING_SPECS
    )
    if _shared is not None
    else ()
)


async def bootstrap_from_metagate(settings: Any) -> Any:
    """Resolve InterView's peer endpoints from MetaGate."""
    if _shared is None:
        logger.warning(
            "metagate_bootstrap_unavailable: shared client not found beside this checkout; "
            "continuing with configured values"
        )
        return None
    return await _shared.bootstrap_from_metagate(
        settings, bindings=BOOTSTRAP_BINDINGS, component_key=COMPONENT_KEY
    )


async def acknowledge_startup(settings: Any, result: Any) -> bool:
    """Close the startup session MetaGate opened during bootstrap."""
    if _shared is None or result is None:
        return False
    return await _shared.acknowledge_startup(settings, result)
