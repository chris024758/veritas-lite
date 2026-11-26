"""Authentication fixtures for API tests."""
from unittest.mock import patch

TEST_PASSWORD = "veritas-test-only-password"


def seed_demo():
    import seed
    from security import hash_password

    with patch.object(seed, "DEMO_PASSWORD_HASH", hash_password(TEST_PASSWORD)):
        seed.seed()


def sign_in(client, test_api="", username="demo123"):
    response = client.post(f"{test_api}/auth/login", json={"username": username, "password": TEST_PASSWORD})
    response.raise_for_status()
    return response
