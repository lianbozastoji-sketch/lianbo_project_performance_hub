class GSpreadException(Exception):
    pass


class APIError(GSpreadException):
    pass


class WorksheetNotFound(GSpreadException):
    pass


class SpreadsheetNotFound(GSpreadException):
    pass
