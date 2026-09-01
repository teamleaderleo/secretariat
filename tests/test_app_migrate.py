from __future__ import annotations

import unittest
from unittest.mock import patch

from secretariat import app


class MigrationDispatchTests(unittest.TestCase):
    def test_global_garden_option_routes_to_migration_cli(self):
        arguments = [
            "--garden",
            "/private/generated-garden.json",
            "migrate",
            "to-kdbx",
            "example-login",
            "--snapshot",
            "apple_passwords=/private/generated-apple.csv",
        ]
        with patch("secretariat.app.migration_cli.main", return_value=7) as migrate:
            self.assertEqual(app.main(arguments), 7)
        migrate.assert_called_once_with(arguments)


if __name__ == "__main__":
    unittest.main()
