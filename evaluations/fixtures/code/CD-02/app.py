"""Synthetic account service with a deliberately incomplete cache invalidation path."""

class UserCache:
    def __init__(self):
        self._items = {}

    def get(self, user_id):
        return self._items.get(user_id)

    def put(self, user_id, user):
        self._items[user_id] = dict(user)

    def invalidate(self, user_id):
        self._items.pop(user_id, None)


class UserRepository:
    def __init__(self):
        self.users = {"u-1": {"id": "u-1", "active": True}}

    def get(self, user_id):
        user = self.users.get(user_id)
        return dict(user) if user is not None else None

    def disable(self, user_id):
        if user_id in self.users:
            self.users[user_id]["active"] = False


class UserService:
    def __init__(self, repository, cache):
        self.repository = repository
        self.cache = cache

    def get_user(self, user_id):
        cached = self.cache.get(user_id)
        if cached is not None:
            return cached
        user = self.repository.get(user_id)
        if user is not None and user["active"]:
            self.cache.put(user_id, user)
            return user
        return None

    def disable_user(self, user_id):
        self.repository.disable(user_id)
        # BUG: cached active record is not invalidated.


class UserHandler:
    def __init__(self, service):
        self.service = service

    def get_user_response(self, user_id):
        user = self.service.get_user(user_id)
        if user is None:
            return {"status": 404, "body": None}
        return {"status": 200, "body": user}
