"""Stage-specific HTTP error codes that do not change Track B's shared registry."""

from haqwa.core.errors import ErrorCode

NOT_IMPLEMENTED = ErrorCode("not_implemented", "Not implemented", 501, 3)
