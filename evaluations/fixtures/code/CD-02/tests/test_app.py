import unittest
from app import UserCache, UserHandler, UserRepository, UserService


class UserServiceTests(unittest.TestCase):
    def setUp(self):
        self.repository = UserRepository()
        self.cache = UserCache()
        self.service = UserService(self.repository, self.cache)
        self.handler = UserHandler(self.service)

    def test_active_user_is_returned(self):
        self.assertEqual(self.handler.get_user_response("u-1")["status"], 200)

    def test_missing_user_is_not_found(self):
        self.assertEqual(self.handler.get_user_response("missing")["status"], 404)


if __name__ == "__main__":
    unittest.main()
