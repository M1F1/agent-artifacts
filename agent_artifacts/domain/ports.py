"""Small injected callable conventions for the imperative shell boundary."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from .result import Result

RequestT = TypeVar("RequestT", contravariant=True)
CommandT = TypeVar("CommandT", contravariant=True)
ResponseT = TypeVar("ResponseT", covariant=True)
ReceiptT = TypeVar("ReceiptT", covariant=True)


@runtime_checkable
class QueryPort(Protocol[RequestT, ResponseT]):
    """Read-like boundary: request data in, typed result data out."""

    def __call__(self, request: RequestT) -> Result[ResponseT]: ...


@runtime_checkable
class CommandPort(Protocol[CommandT, ReceiptT]):
    """Effect boundary: immutable command data in, typed receipt data out."""

    def __call__(self, command: CommandT) -> Result[ReceiptT]: ...
