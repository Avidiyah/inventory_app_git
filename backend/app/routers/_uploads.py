"""Bounded reads for multipart uploads.

Layer: routers (internal helper), sibling to `_errors.py`. This is the
single place that knows how big an upload is allowed to be and what a
caller is told when it is too big. The two upload routes
(`POST /barcodes/decode`, `POST /work-orders/import`) and the one on-host
file route (`POST /integrations/netfacilities/downloads/import`) are its
only callers; anything that adds another should call this rather than
`file.file.read()`.

**What this does and does not protect (B1).** By the time a handler
runs, Starlette's `MultiPartParser` has already received the whole body
and spooled the file part to a `SpooledTemporaryFile`, which switches to
disk past 1 MB. So the cap here does *not* stop a client from
transmitting a huge upload, and it never could -- that would need a
check before the body is read. What it stops is the part that actually
hurt: `file.file.read()` with no argument materialising the entire
spooled file as one `bytes` object in memory, and then handing it to
Pillow or the CSV parser. Reading `limit + 1` bytes bounds both.

The size check is written twice on purpose. `UploadFile.size` is exact
-- the parser increments it as the part arrives -- and checking it first
means an oversized upload is refused without reading anything at all.
But it is `None` for an `UploadFile` constructed directly (scripts, unit
tests, any future non-multipart caller), so the bounded read is the
guard that cannot be bypassed. Neither one alone is sufficient: the
first is an optimisation, the second is the guarantee.

The status is **413**, raised as a plain `HTTPException` rather than
through `_errors.to_http`. An upload cap is a transport limit, not a
business rule, and `domain/errors.py` is deliberately framework-agnostic
-- putting a byte count in there would be the first HTTP concept in a
module whose whole point is not having any. `routers/work_orders.py`
(403) and `routers/auth.py` (429) already raise directly for the same
kind of reason.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

# Caps chosen well above any real file so no user reaches them: a phone
# photo of a barcode is 2-5 MB, and the mass work-order CSV export is
# orders of magnitude under 25 MB. They are constants rather than env
# vars deliberately -- a limit that differs per environment is a limit
# nobody can reason about from the code.
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CSV_UPLOAD_BYTES = 25 * 1024 * 1024

_BYTES_PER_MB = 1024 * 1024


def _too_large(what: str, limit: int) -> HTTPException:
    """Build the 413. The message states the cap in MB, derived from the
    limit itself so the copy cannot drift from the constant.

    `api.js::parseResponse` surfaces `detail` for any non-2xx and both
    upload call sites already route through it, so this renders in the
    existing error UI with no frontend change."""
    return HTTPException(
        status_code=413,
        detail=f"{what} is too large. The maximum upload size is {limit // _BYTES_PER_MB} MB.",
    )


def _log_rejection(what: str, *, limit: int, size: Optional[int]) -> None:
    """Record the refusal server-side.

    A rejected upload is otherwise invisible: the caller sees a 413 and
    the server keeps no trace, so "the scanner stopped working" would
    have nothing behind it. N1 made this a one-liner, and the request id
    on the line ties it to the same request's `event=request`.

    `size` is `None` when the bounded read caught it rather than the
    declared size, which is itself the interesting case -- it means the
    upload arrived without a parser-tracked size.
    """
    logger.warning(
        "upload.rejected_too_large",
        extra={"fields": {"what": what, "size": size, "limit": limit}},
    )


def read_capped(file: UploadFile, *, limit: int, what: str) -> bytes:
    """Read an upload, refusing anything over `limit` bytes with a 413.

    Below the cap this is byte-identical to `file.file.read()` -- same
    bytes, same type, same caller code path. Above it, nothing larger
    than `limit + 1` bytes is ever held.

    `what` names the thing in the error message ("Image", "CSV file"),
    so the caller controls the wording without owning the format.
    """
    size = file.size
    if size is not None and size > limit:
        _log_rejection(what, limit=limit, size=size)
        raise _too_large(what, limit)

    # One byte past the cap is enough to know it was exceeded, and is the
    # most this function will ever hold.
    data = file.file.read(limit + 1)
    if len(data) > limit:
        _log_rejection(what, limit=limit, size=size)
        raise _too_large(what, limit)

    return data


def read_file_capped(path: Path, *, limit: int, what: str) -> bytes:
    """Bounded read of a file already on this host.

    The CSV the live NetFacilities window saved is imported from disk rather
    than uploaded, so it bypasses the multipart parser -- and would bypass the
    cap too, unless it is applied here. Same limit, same 413, same log line as
    the upload routes. ``OSError`` (missing, unreadable) propagates: the caller
    decides what a vanished file means.
    """

    size = path.stat().st_size
    if size > limit:
        _log_rejection(what, limit=limit, size=size)
        raise _too_large(what, limit)
    with path.open("rb") as handle:
        return handle.read(limit)
