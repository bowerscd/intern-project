"""Test-suite constants, environment overrides, and claim combinatorics."""
from typing import Dict


TEST_REDIRECT = "http://api.localhost/auth"
TEST_CLIENT_ID = "client_id1"
TEST_CLIENT_SECRET = "definitely_a_secret"

TEST_ENV_VAR_PREFIX = "TEST"

__REDIRECT_URI_ENV_VAR = f"{TEST_ENV_VAR_PREFIX}_REDIRECT_URI"
__CLIENT_SECRET_ENV_VAR = f"{TEST_ENV_VAR_PREFIX}_CLIENT_SECRET"
__CLIENT_ID_ENV_VAR = f"{TEST_ENV_VAR_PREFIX}_CLIENT_ID"

ENV_VAR_OVERRIDES: Dict[str, str] = {
    "DEV": "1",
    __REDIRECT_URI_ENV_VAR: TEST_REDIRECT,
    __CLIENT_SECRET_ENV_VAR: TEST_CLIENT_SECRET,
    __CLIENT_ID_ENV_VAR: TEST_CLIENT_ID,
    # Google provider env vars (needed for auth router lifespan)
    "GOOGLE_REDIRECT_URI": TEST_REDIRECT,
    "GOOGLE_CLIENT_SECRET": "google_test_secret",
    "GOOGLE_CLIENT_ID": "google_test_client_id",
}
