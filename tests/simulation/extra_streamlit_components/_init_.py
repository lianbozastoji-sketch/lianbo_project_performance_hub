COOKIES = {}


class CookieManager:
    def __init__(self, key=None):
        self.key = key

    def get_all(self, *a, **k):
        return dict(COOKIES)

    def get(self, name, *a, **k):
        return COOKIES.get(name)

    def set(self, name, value, *a, **k):
        COOKIES[name] = value

    def delete(self, name, *a, **k):
        COOKIES.pop(name, None)
