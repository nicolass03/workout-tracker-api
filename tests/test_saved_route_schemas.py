import unittest
from uuid import uuid4

from pydantic import ValidationError

from api.schemas.saved_routes import SavedRouteCreate


class SavedRouteSchemaTests(unittest.TestCase):
    def test_name_is_trimmed_and_internal_whitespace_collapsed(self):
        body = SavedRouteCreate(source_session_id=uuid4(), name="  Coast   loop  ")
        self.assertEqual(body.name, "Coast loop")

    def test_blank_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            SavedRouteCreate(source_session_id=uuid4(), name="   ")


if __name__ == "__main__":
    unittest.main()
