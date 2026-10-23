class Figure:
    """Accepts any plotly call and records traces."""

    def __init__(self, *args, **kwargs):
        self.data = list(args[0]) if args and isinstance(args[0], (list, tuple)) else ([args[0]] if args else [])

    def __getattr__(self, name):
        def method(*args, **kwargs):
            if name == "add_trace" and args:
                self.data.append(args[0])
            return self
        return method


def _factory(*args, **kwargs):
    return Figure()
