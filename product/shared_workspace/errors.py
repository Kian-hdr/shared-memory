"""Stable operational errors for the JSON CLI boundary."""


class ProductError(Exception):
    def __init__(self, exit_code, code, message, *, data=None, warnings=None):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.data = data or {}
        self.warnings = warnings or []

