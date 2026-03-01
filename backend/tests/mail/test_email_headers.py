"""Tests for email header handling: deepcopy prevents mutation."""
import pytest
from email.mime.text import MIMEText
from pytest_localserver.smtp import Server as SMTPServer


class TestEmailHeaderCorruption:
    """send_email now deep-copies the message so the caller's object is never mutated."""

    @pytest.mark.asyncio
    async def test_send_email_replaces_headers(self, smtp: SMTPServer) -> None:
        """Verify that send_email does not mutate the caller's MIMEText object.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        from email.mime.text import MIMEText
        from mail.outgoing import send_email

        msg = MIMEText("Test body")
        msg["Subject"] = "Test"

        await send_email("user1@test.com", msg)

        # The original message should have NO To/From — send_email works on a copy
        to_after = msg.get_all("To") or []
        from_after = msg.get_all("From") or []
        assert len(to_after) == 0, (
            "Original message should not be mutated by send_email"
        )
        assert len(from_after) == 0, (
            "Original message should not be mutated by send_email"
        )

        # Send again — the original should still be clean
        await send_email("user2@test.com", msg)

        to_final = msg.get_all("To") or []
        from_final = msg.get_all("From") or []
        assert len(to_final) == 0, (
            "Original message still untouched after second send"
        )
        assert len(from_final) == 0, (
            "Original message still untouched after second send"
        )
