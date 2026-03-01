"""Tests for mealbot route issues: test provider usage, early commits."""


class TestProviderUsageInUserCreation:
    """
    v1 create_user uses ExternalAuthProvider.test, meaning
    programmatically created users can never OIDC-authenticate.

    The v2 ``POST /user`` endpoint has been removed; account creation
    now goes through the OIDC registration flow.
    """

    def test_v2_user_endpoint_removed(self) -> None:
        """Verify ``create_mealbot_user`` no longer exists on the v2 router."""
        import routes.mealbot.v2 as v2_mod

        assert not hasattr(v2_mod, "create_mealbot_user"), (
            "POST /v2/mealbot/user should have been removed"
        )
