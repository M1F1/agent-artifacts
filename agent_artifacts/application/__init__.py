"""Application services orchestrating pure domain functions through injected ports."""

from .compiler import CompilerPorts, CompilerSteps, compile_sources
from .configuration import (
    ConfigurationPorts,
    ConfigurationRequest,
    load_configuration,
)
from .importers import finalize_legacy_import, prepare_legacy_import
from .registry_maintenance import finalize_registry_mutation, prepare_native_promotion
from .sources import (
    SourceStatusRequest,
    SourceSyncPorts,
    SourceSyncRequest,
    source_status,
    sync_source,
)
from .store import (
    ReferenceUpdatePorts,
    ReferenceUpdateRequest,
    StoreGcPorts,
    collect_garbage,
    object_status,
    replace_references,
)

__all__ = [
    "CompilerPorts",
    "CompilerSteps",
    "ConfigurationPorts",
    "ConfigurationRequest",
    "SourceSyncPorts",
    "SourceSyncRequest",
    "SourceStatusRequest",
    "ReferenceUpdatePorts",
    "ReferenceUpdateRequest",
    "StoreGcPorts",
    "collect_garbage",
    "finalize_legacy_import",
    "finalize_registry_mutation",
    "object_status",
    "compile_sources",
    "load_configuration",
    "prepare_legacy_import",
    "prepare_native_promotion",
    "source_status",
    "replace_references",
    "sync_source",
]
