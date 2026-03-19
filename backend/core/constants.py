"""Shared constants and enums for PIKA implement workflow."""

from __future__ import annotations

from enum import StrEnum


class ImplementStatus(StrEnum):
    """Status values for implement command and batch execution."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"
    PASSED = "passed"


class BatchKind(StrEnum):
    """Kind of batch in the implement batch plan."""

    MODULE_IMPL = "module_impl"
    INTEGRATION = "integration"


class ValidationCode(StrEnum):
    """Validation violation/check codes for link plan and batch plan validation."""

    UNBOUND_REQUIRED_INTENT = "unbound_required_intent"
    DISALLOWED_KIND_FOR_REQUIRED_ROLE = "disallowed_kind_for_required_role"
    EXTERNAL_API_BOUND_TO_INTERNAL_PROVIDER = "external_api_bound_to_internal_provider"
    CROSS_MODULE_TYPE_LOCATION_OUTSIDE_PLACEMENT_PATH = (
        "cross_module_type_location_outside_placement_path"
    )


class ContractKind(StrEnum):
    """Contract kind identifiers for implement linking."""

    API_ENDPOINT = "api_endpoint"
    SERVICE_INTERFACE = "service_interface"
    EVENT_TOPIC = "event_topic"
    DB_TABLE = "db_table"
    FILE_FORMAT = "file_format"
    EXTERNAL_API = "external_api"
    TEST_SUITE = "test_suite"
