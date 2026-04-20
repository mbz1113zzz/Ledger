"""Auto-disable helper: if a source keeps hitting 4xx (typically 401/403 from
a free-tier API endpoint it doesn't have access to), stop calling it and log
a single summary line instead of flooding warnings every poll cycle."""
import logging

log = logging.getLogger(__name__)


class SourceHealth:
    THRESHOLD = 5

    def __init__(self, source_name: str):
        self._name = source_name
        self._consecutive_4xx = 0
        self._disabled = False
        self._last_status: int | None = None
        self._reason: str | None = None

    @property
    def disabled(self) -> bool:
        return self._disabled

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def last_status(self) -> int | None:
        return self._last_status

    def record_4xx(self, status: int) -> None:
        if self._disabled:
            return
        self._consecutive_4xx += 1
        self._last_status = status
        self._reason = "permission_denied" if status in (401, 403) else "client_error"
        if self._consecutive_4xx >= self.THRESHOLD:
            self._disabled = True
            log.warning(
                "source %s disabled after %d consecutive %dx responses "
                "(likely unavailable on your API tier)",
                self._name, self._consecutive_4xx, status // 100,
            )

    def record_success(self) -> None:
        if self._disabled:
            log.info("source %s recovered, re-enabling", self._name)
            self._disabled = False
        self._consecutive_4xx = 0
        self._last_status = None
        self._reason = None
