"""Application services orchestrating pure domain functions through injected ports."""

from .compiler import CompilerPorts, CompilerSteps, compile_sources
from .configuration import (
    ConfigurationPorts,
    ConfigurationRequest,
    load_configuration,
)
from .registry_commands import (
    finalize_registry_workspace,
    prepare_artifact_scaffold,
    prepare_registry_build,
    prepare_registry_format,
    prepare_registry_init,
    prepare_registry_lock,
)
from .registry_maintenance import finalize_registry_mutation, prepare_native_promotion
from .source_management import (
    SourceManagementReceipt,
    finalize_source_addition,
    finalize_source_management,
)
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
    "SourceManagementReceipt",
    "ReferenceUpdatePorts",
    "ReferenceUpdateRequest",
    "StoreGcPorts",
    "collect_garbage",
    "finalize_registry_mutation",
    "finalize_registry_workspace",
    "finalize_source_addition",
    "finalize_source_management",
    "object_status",
    "compile_sources",
    "load_configuration",
    "prepare_native_promotion",
    "prepare_artifact_scaffold",
    "prepare_registry_build",
    "prepare_registry_format",
    "prepare_registry_init",
    "prepare_registry_lock",
    "source_status",
    "replace_references",
    "sync_source",
]
