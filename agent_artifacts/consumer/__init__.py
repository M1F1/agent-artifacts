"""Canonical multi-item consumer application boundary."""

from .application import (
    ConsumerApplicationService,
    browse_consumer_marketplace,
    finalize_consumer_action,
    prepare_consumer_action,
    prepare_consumer_setup_queue,
)
from .io import LocalConsumerAdapter
from .model import (
    ConsumerActionRequest,
    ConsumerContext,
    ConsumerOutcome,
    ConsumerReview,
    ConsumerReviewEffect,
    ConsumerReviewItem,
    ConsumerSetupFailure,
    ConsumerSetupQueue,
    ConsumerTerminalItem,
    render_consumer_outcome,
    render_consumer_review,
    review_source_freshness,
)

__all__ = [
    "ConsumerActionRequest",
    "ConsumerApplicationService",
    "ConsumerContext",
    "ConsumerOutcome",
    "ConsumerReview",
    "ConsumerReviewEffect",
    "ConsumerReviewItem",
    "ConsumerSetupFailure",
    "ConsumerSetupQueue",
    "ConsumerTerminalItem",
    "LocalConsumerAdapter",
    "browse_consumer_marketplace",
    "finalize_consumer_action",
    "prepare_consumer_action",
    "prepare_consumer_setup_queue",
    "render_consumer_outcome",
    "render_consumer_review",
    "review_source_freshness",
]
