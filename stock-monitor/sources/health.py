"""Auto-disable helper: if a source keeps hitting 4xx (typically 401/403 from
a free-tier API endpoint it doesn't have access to), stop calling it and log
a single summary line instead of flooding warnings every poll cycle."""
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class SourceHealth:
    THRESHOLD = 5

    def __init__(self, source_name: str):
        self._name = source_name
        self._consecutive_4xx = 0
        self._disabled = False
        self._last_status: int | None = None
        self._reason: str | None = None
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._last_duration_ms: float | None = None
        self._last_success_at: datetime | None = None
        self._last_error_at: datetime | None = None

    @property
    def disabled(self) -> bool:
        return self._disabled

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def last_status(self) -> int | None:
        return self._last_status

    def _mark_attempt(self, duration_ms: float | None = None) -> None:
        self._request_count += 1
        if duration_ms is not None:
            self._last_duration_ms = round(float(duration_ms), 2)

    def _set_error(
        self,
        *,
        reason: str,
        status: int | None = None,
        duration_ms: float | None = None,
        reset_streak: bool = True,
    ) -> None:
        self._mark_attempt(duration_ms)
        self._error_count += 1
        self._last_status = status
        self._reason = reason
        self._last_error_at = datetime.now(timezone.utc)
        if reset_streak:
            self._consecutive_4xx = 0

    def record_http_error(self, status: int, *, duration_ms: float | None = None) -> None:
        reason = (
            "permission_denied" if status in (401, 403)
            else "quota_exhausted" if status == 429
            else "client_error" if 400 <= status < 500
            else "upstream_error"
        )
        self._set_error(
            reason=reason,
            status=status,
            duration_ms=duration_ms,
            reset_streak=not (400 <= status < 500),
        )
        if self._disabled or not (400 <= status < 500) or status == 429:
            return
        self._consecutive_4xx += 1
        if self._consecutive_4xx >= self.THRESHOLD:
            self._disabled = True
            log.warning(
                "source %s disabled after %d consecutive %dx responses "
                "(likely unavailable on your API tier)",
                self._name, self._consecutive_4xx, status // 100,
            )

    def record_error(
        self,
        *,
        reason: str = "upstream_error",
        status: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        self._set_error(
            reason=reason,
            status=status,
            duration_ms=duration_ms,
        )

    def record_timeout(self, *, duration_ms: float | None = None) -> None:
        self._set_error(reason="timeout", duration_ms=duration_ms)

    def record_success(self, *, duration_ms: float | None = None) -> None:
        self._mark_attempt(duration_ms)
        if self._disabled:
            log.info("source %s recovered, re-enabling", self._name)
            self._disabled = False
        self._consecutive_4xx = 0
        self._success_count += 1
        self._last_status = None
        self._reason = None
        self._last_success_at = datetime.now(timezone.utc)

    def snapshot(self) -> dict:
        return {
            "name": self._name,
            "disabled": self._disabled,
            "reason": self._reason,
            "last_status": self._last_status,
            "request_count": self._request_count,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "consecutive_4xx": self._consecutive_4xx,
            "last_duration_ms": self._last_duration_ms,
            "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
            "last_error_at": self._last_error_at.isoformat() if self._last_error_at else None,
        }
