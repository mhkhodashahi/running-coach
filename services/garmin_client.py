"""Garmin connector abstractions and CSV implementation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from services import garmin_normalization as gn
from services.garmin_normalization import (
    extract_activity_laps,
    extract_activity_track_points,
)

_extract_recovery_time_hours = gn.normalize_recovery_time_hours

try:
    from garth.exc import GarthHTTPError
except ImportError:  # garminconnect 0.3.x no longer depends on garth.
    class GarthHTTPError(Exception):
        """Compatibility placeholder for older garth-backed login failures."""


def _status_code_from_exception(exc: Exception) -> int | None:
    candidates = [exc]
    visited: set[int] = set()

    while candidates:
        current = candidates.pop(0)
        if current is None:
            continue

        current_id = id(current)
        if current_id in visited:
            continue
        visited.add(current_id)

        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

        error = getattr(current, "error", None)
        if isinstance(error, BaseException):
            candidates.append(error)

        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            candidates.append(cause)

        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            candidates.append(context)

    message = " ".join(str(candidate).lower() for candidate in visited_exceptions(exc))
    if "429" in message or "too many requests" in message or "rate limit" in message:
        return 429
    if "401" in message or "unauthorized" in message or "authentication" in message:
        return 401
    return None


def _retry_after_delta(exc: Exception) -> timedelta | None:
    for current in visited_exceptions(exc):
        response = getattr(current, "response", None)
        headers = getattr(response, "headers", None) or {}
        retry_after = headers.get("Retry-After")
        if retry_after and str(retry_after).isdigit():
            return timedelta(seconds=int(retry_after))
    return None


def visited_exceptions(exc: Exception) -> list[BaseException]:
    items: list[BaseException] = []
    queue: list[BaseException] = [exc]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        items.append(current)

        error = getattr(current, "error", None)
        if isinstance(error, BaseException):
            queue.append(error)

        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            queue.append(cause)

        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            queue.append(context)

    return items


class GarminClient(ABC):
    """Abstract Garmin data source."""

    @abstractmethod
    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        """Load activity rows from a source."""

    @abstractmethod
    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        """Load health metric rows from a source."""

    def sync_recent_data(self, user_id: int, days: int, health_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Sync recent data directly from Garmin when supported."""

        raise NotImplementedError("This Garmin client does not support direct sync.")

    def sync_activity_details(
        self,
        user_id: int,
        activity_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Sync GPS stream points and laps for activities when supported."""

        raise NotImplementedError("This Garmin client does not support activity detail sync.")


class CSVGarminClient(GarminClient):
    """CSV-based Garmin importer."""

    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        df = pd.read_csv(source)
        if df.empty:
            return []

        date_series = pd.to_datetime(
            df.get("date", df.get("startTimeLocal", df.get("start_time"))),
            errors="coerce",
        )

        records: list[dict[str, Any]] = []
        for index, row in df.iterrows():
            record = gn.normalize_csv_activity_row(
                row,
                user_id=user_id,
                index=index,
                parsed_date=date_series.iloc[index],
            )
            if record is not None:
                records.append(record)
        return records

    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        df = pd.read_csv(source)
        if df.empty:
            return []

        date_series = pd.to_datetime(df.get("date"), errors="coerce")
        records: list[dict[str, Any]] = []
        for index, row in df.iterrows():
            record = gn.normalize_csv_health_row(row, user_id=user_id, parsed_date=date_series.iloc[index])
            if record is not None:
                records.append(record)
        return records

    def sync_activity_details(
        self,
        user_id: int,
        activity_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        return {}


class FutureGarminAPIClient(GarminClient):
    """Placeholder API connector for future Garmin integrations."""

    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("API connector is reserved for a future Garmin integration.")

    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("API connector is reserved for a future Garmin integration.")


class GarminAPIClient(GarminClient):
    """Live Garmin Connect client using username and password from configuration."""

    def __init__(
        self,
        email: str,
        password: str,
        token_dir: str | Path | None = None,
        rate_limit_cooldown_minutes: int = 30,
    ) -> None:
        if not email or not password:
            raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD must be configured for live sync.")
        self.email = email
        self.password = password
        self.token_dir = Path(token_dir).resolve() if token_dir else None
        self.rate_limit_cooldown = timedelta(minutes=max(rate_limit_cooldown_minutes, 1))
        self._client: Garmin | None = None

    def _token_store_files_exist(self) -> bool:
        if self.token_dir is None:
            return False
        return any(
            (self.token_dir / filename).exists()
            for filename in ("garmin_tokens.json", "oauth1_token.json", "oauth2_token.json")
        )

    def _rate_limit_path(self) -> Path | None:
        if self.token_dir is None:
            return None
        return self.token_dir / "rate_limit.json"

    def _ensure_token_dir(self) -> None:
        if self.token_dir is not None:
            self.token_dir.mkdir(parents=True, exist_ok=True)

    def _clear_rate_limit(self) -> None:
        rate_limit_path = self._rate_limit_path()
        if rate_limit_path and rate_limit_path.exists():
            rate_limit_path.unlink()

    def _clear_token_store(self) -> None:
        if self.token_dir is None:
            return
        for filename in ("garmin_tokens.json", "oauth1_token.json", "oauth2_token.json"):
            token_file = self.token_dir / filename
            if token_file.exists():
                token_file.unlink()

    def _read_rate_limit_deadline(self) -> datetime | None:
        rate_limit_path = self._rate_limit_path()
        if rate_limit_path is None or not rate_limit_path.exists():
            return None
        try:
            payload = json.loads(rate_limit_path.read_text())
            raw_retry_after = payload.get("retry_after")
            if not raw_retry_after:
                return None
            deadline = datetime.fromisoformat(raw_retry_after)
            return deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _guard_rate_limit(self) -> None:
        deadline = self._read_rate_limit_deadline()
        if deadline is None:
            return

        now = datetime.now(UTC)
        if deadline <= now:
            self._clear_rate_limit()
            return

        local_deadline = deadline.astimezone()
        raise RuntimeError(
            "Garmin sign-in is temporarily rate-limited. "
            f"Wait until {local_deadline.strftime('%Y-%m-%d %H:%M %Z')} before retrying."
        )

    def _record_rate_limit(self, exc: Exception) -> None:
        rate_limit_path = self._rate_limit_path()
        if rate_limit_path is None:
            return

        self._ensure_token_dir()
        retry_after = _retry_after_delta(exc) or self.rate_limit_cooldown
        deadline = datetime.now(UTC) + retry_after
        payload = {"retry_after": deadline.isoformat()}
        rate_limit_path.write_text(json.dumps(payload))

    def _persist_tokens(self, client: Garmin) -> None:
        if self.token_dir is None:
            return
        self._ensure_token_dir()
        native_client = getattr(client, "client", None)
        native_dump = getattr(native_client, "dump", None)
        if callable(native_dump):
            native_dump(str(self.token_dir))
            return

        garth_client = getattr(client, "garth", None)
        garth_dump = getattr(garth_client, "dump", None)
        if callable(garth_dump):
            garth_dump(str(self.token_dir))

    def _raise_login_error(self, exc: Exception) -> None:
        status_code = _status_code_from_exception(exc)
        if status_code == 429:
            self._record_rate_limit(exc)
            deadline = self._read_rate_limit_deadline()
            if deadline is not None:
                local_deadline = deadline.astimezone()
                raise RuntimeError(
                    "Garmin rate limit reached. "
                    f"Wait until {local_deadline.strftime('%Y-%m-%d %H:%M %Z')} before syncing again."
                ) from exc
            raise RuntimeError("Garmin rate limit reached. Wait and try syncing again later.") from exc
        if status_code == 401:
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        raise RuntimeError("Garmin authentication failed during login.") from exc

    def _login(self, client: Garmin) -> None:
        tokenstore = str(self.token_dir) if self.token_dir is not None else None
        try:
            if tokenstore:
                client.login(tokenstore=tokenstore)
            else:
                client.login()
            self._persist_tokens(client)
            return
        except FileNotFoundError:
            # Older garth-backed versions raise when the token files do not exist yet.
            pass
        except GarminConnectAuthenticationError as exc:
            if _status_code_from_exception(exc) == 429:
                self._raise_login_error(exc)
            if not self._token_store_files_exist():
                self._raise_login_error(exc)
            self._clear_token_store()
        except (GarminConnectTooManyRequestsError, GarthHTTPError) as exc:
            self._raise_login_error(exc)
        except Exception as exc:
            status_code = _status_code_from_exception(exc)
            if status_code == 429:
                self._raise_login_error(exc)
            if status_code == 401 and self._token_store_files_exist():
                self._clear_token_store()
            elif status_code == 401:
                self._raise_login_error(exc)
            else:
                raise RuntimeError("Garmin authentication failed during login.") from exc

        try:
            client.login()
            self._persist_tokens(client)
        except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError, GarthHTTPError) as retry_exc:
            self._raise_login_error(retry_exc)
        except Exception as retry_exc:
            status_code = _status_code_from_exception(retry_exc)
            if status_code in {401, 429}:
                self._raise_login_error(retry_exc)
            raise RuntimeError("Garmin authentication failed during login.") from retry_exc

    def _raise_mapped_error(self, exc: Exception, *, context: str) -> None:
        status_code = _status_code_from_exception(exc)
        if status_code == 401:
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        if status_code == 429:
            self._record_rate_limit(exc)
            deadline = self._read_rate_limit_deadline()
            if deadline is not None:
                local_deadline = deadline.astimezone()
                raise RuntimeError(
                    "Garmin rate limit reached. "
                    f"Wait until {local_deadline.strftime('%Y-%m-%d %H:%M %Z')} before syncing again."
                ) from exc
            raise RuntimeError("Garmin rate limit reached. Wait and try syncing again later.") from exc
        raise RuntimeError(f"Could not connect to Garmin Connect while fetching {context}.") from exc

    def _call_api(self, request, *, default: Any, context: str, suppress_errors: bool) -> Any:
        try:
            return request()
        except (GarminConnectTooManyRequestsError, GarthHTTPError) as exc:
            self._raise_mapped_error(exc, context=context)
        except GarminConnectAuthenticationError as exc:
            status_code = _status_code_from_exception(exc)
            if status_code == 429:
                self._raise_mapped_error(exc, context=context)
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        except GarminConnectConnectionError as exc:
            if suppress_errors:
                return default
            raise RuntimeError(f"Could not connect to Garmin Connect while fetching {context}.") from exc
        except Exception as exc:
            status_code = _status_code_from_exception(exc)
            if status_code in {401, 429}:
                self._raise_mapped_error(exc, context=context)
            if suppress_errors:
                return default
            raise RuntimeError(f"Garmin request failed while fetching {context}.") from exc

    def _get_client(self) -> Garmin:
        if self._client is not None:
            return self._client

        self._guard_rate_limit()
        client = Garmin(self.email, self.password)
        print("Logging in to Garmin Connect...")
        try:
            self._login(client)
        except GarminConnectAuthenticationError as exc:
            status_code = _status_code_from_exception(exc)
            if status_code == 429:
                self._raise_mapped_error(exc, context="sign-in")
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        except GarminConnectTooManyRequestsError as exc:
            self._raise_mapped_error(exc, context="sign-in")
        except GarminConnectConnectionError as exc:
            raise RuntimeError("Could not connect to Garmin Connect.") from exc
        except GarthHTTPError as exc:
            self._raise_mapped_error(exc, context="sign-in")
        except Exception as exc:
            status_code = _status_code_from_exception(exc)
            if status_code in {401, 429}:
                self._raise_mapped_error(exc, context="sign-in")
            raise RuntimeError("Could not connect to Garmin Connect.") from exc

        self._persist_tokens(client)
        self._clear_rate_limit()
        self._client = client
        return client

    def get_authenticated_client(self) -> Garmin:
        """Return an authenticated Garmin client, reusing cached tokens when available."""

        return self._get_client()

    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("Use sync_recent_data for the live Garmin connector.")

    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("Use sync_recent_data for the live Garmin connector.")

    def sync_recent_data(self, user_id: int, days: int, health_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        client = self._get_client()
        today = date.today()
        activities_start = today - timedelta(days=max(days - 1, 0))
        activities_raw = self._call_api(
            lambda: client.get_activities_by_date(
                activities_start.strftime("%Y-%m-%d"),
                today.strftime("%Y-%m-%d"),
            ),
            default=[],
            context="activities",
            suppress_errors=False,
        )

        activity_rows: list[dict[str, Any]] = []
        for row in activities_raw:
            activity_row = gn.normalize_live_activity_row(row, user_id=user_id)
            if activity_row is not None:
                activity_rows.append(activity_row)

        health_rows: list[dict[str, Any]] = []
        health_start = today - timedelta(days=max(health_days - 1, 0))
        for offset in range((today - health_start).days + 1):
            current_day = health_start + timedelta(days=offset)
            current_day_str = current_day.strftime("%Y-%m-%d")
            stats = self._call_api(
                lambda current_day_str=current_day_str: client.get_stats(current_day_str) or {},
                default={},
                context=f"stats for {current_day_str}",
                suppress_errors=True,
            )
            sleep = self._call_api(
                lambda current_day_str=current_day_str: client.get_sleep_data(current_day_str) or {},
                default={},
                context=f"sleep data for {current_day_str}",
                suppress_errors=True,
            )
            body_battery = self._call_api(
                lambda current_day_str=current_day_str: client.get_body_battery(current_day_str, current_day_str) or [],
                default=[],
                context=f"body battery for {current_day_str}",
                suppress_errors=True,
            )
            hrv = self._call_api(
                lambda current_day_str=current_day_str: client.get_hrv_data(current_day_str) or {},
                default={},
                context=f"HRV data for {current_day_str}",
                suppress_errors=True,
            )
            max_metrics = self._call_api(
                lambda current_day_str=current_day_str: client.get_max_metrics(current_day_str) or {},
                default={},
                context=f"VO2 max data for {current_day_str}",
                suppress_errors=True,
            )
            training_readiness = self._call_api(
                lambda current_day_str=current_day_str: (
                    client.get_morning_training_readiness(current_day_str)
                    or client.get_training_readiness(current_day_str)
                    or {}
                ),
                default={},
                context=f"training readiness for {current_day_str}",
                suppress_errors=True,
            )
            training_status = self._call_api(
                lambda current_day_str=current_day_str: client.get_training_status(current_day_str) or {},
                default={},
                context=f"training status for {current_day_str}",
                suppress_errors=True,
            )

            health_row = gn.normalize_live_health_row(
                user_id=user_id,
                current_day=current_day,
                stats=stats,
                sleep=sleep,
                body_battery=body_battery,
                hrv=hrv,
                max_metrics=max_metrics,
                training_readiness=training_readiness,
                training_status=training_status,
            )
            if health_row is not None:
                health_rows.append(health_row)

        return activity_rows, health_rows

    def sync_activity_details(
        self,
        user_id: int,
        activity_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Fetch Garmin activity detail streams and split/lap data."""

        client = self._get_client()
        details_by_external_id: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for row in activity_rows:
            external_id = str(row.get("external_id") or "")
            if not external_id:
                continue

            details = self._call_api(
                lambda activity_id=external_id: client.get_activity_details(activity_id) or {},
                default={},
                context=f"activity details for {external_id}",
                suppress_errors=True,
            )
            splits = self._call_api(
                lambda activity_id=external_id: client.get_activity_splits(activity_id) or {},
                default={},
                context=f"activity splits for {external_id}",
                suppress_errors=True,
            )
            split_summaries = self._call_api(
                lambda activity_id=external_id: client.get_activity_split_summaries(activity_id) or {},
                default={},
                context=f"activity split summaries for {external_id}",
                suppress_errors=True,
            )
            typed_splits = self._call_api(
                lambda activity_id=external_id: client.get_activity_typed_splits(activity_id) or {},
                default={},
                context=f"typed activity splits for {external_id}",
                suppress_errors=True,
            )

            track_points = extract_activity_track_points(details if isinstance(details, dict) else {})
            laps = extract_activity_laps(splits, split_summaries, typed_splits)
            if track_points or laps:
                details_by_external_id[external_id] = {
                    "track_points": track_points,
                    "laps": laps,
                }
        return details_by_external_id
