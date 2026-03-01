"""Tests for scheduler startup: SCHEDULER_ENABLED guard and basic lifecycle."""

import pytest
from unittest.mock import patch, MagicMock


class TestSchedulerEnabledGuard:
    """The scheduler should respect the SCHEDULER_ENABLED config flag."""

    def test_scheduler_starts_when_enabled(self) -> None:
        """When SCHEDULER_ENABLED is True the scheduler should start."""
        with patch("scheduler.get_scheduler") as mock_get:
            mock_sched = MagicMock()
            mock_get.return_value = mock_sched

            with patch("config.SCHEDULER_ENABLED", True):
                from scheduler import start_scheduler
                start_scheduler()

            mock_sched.start.assert_called_once()

    def test_scheduler_skips_when_disabled(self) -> None:
        """When SCHEDULER_ENABLED is False the scheduler should NOT start."""
        with patch("scheduler.get_scheduler") as mock_get:
            mock_sched = MagicMock()
            mock_get.return_value = mock_sched

            with patch("config.SCHEDULER_ENABLED", False):
                from scheduler import start_scheduler
                start_scheduler()

            mock_sched.start.assert_not_called()


class TestSchedulerHealthCheck:
    """The /healthz endpoint should report scheduler status."""

    def test_healthz_reports_scheduler_status(self) -> None:
        """Health check should include scheduler status in the response."""
        from starlette.testclient import TestClient
        from app import app

        with TestClient(app) as c:
            resp = c.get("/healthz")
            assert resp.status_code == 200
            data = resp.json()
            assert "scheduler" in data


class TestSchedulerMisfireGrace:
    """Scheduler jobs should have misfire_grace_time configured."""

    def test_jobs_have_misfire_grace_time(self) -> None:
        """Both cron jobs should be added with misfire_grace_time."""
        with patch("scheduler.get_scheduler") as mock_get:
            mock_sched = MagicMock()
            mock_get.return_value = mock_sched

            with patch("config.SCHEDULER_ENABLED", True):
                from scheduler import start_scheduler
                start_scheduler()

            # Check that add_job was called with misfire_grace_time
            for call in mock_sched.add_job.call_args_list:
                kwargs = call.kwargs if call.kwargs else {}
                assert kwargs.get("misfire_grace_time", 0) > 0, (
                    f"Job missing misfire_grace_time: {call}"
                )