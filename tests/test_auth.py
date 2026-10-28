import unittest
from unittest.mock import patch

from jwt import PyJWKClient

from api.auth import _ThrottledJWKClient


class JWKSThrottleTests(unittest.TestCase):
    def test_unknown_kid_refreshes_at_most_once_a_minute(self):
        client = _ThrottledJWKClient("https://example.supabase.co/auth/v1/.well-known/jwks.json")
        with patch.object(PyJWKClient, "get_signing_keys", return_value=[]) as fetch, \
                patch("api.auth.time.monotonic", side_effect=[100.0, 130.0, 161.0]):
            for _ in range(3):
                client.get_signing_keys(refresh=True)
        self.assertEqual(
            [call.kwargs["refresh"] for call in fetch.call_args_list], [True, False, True]
        )


if __name__ == "__main__":
    unittest.main()
