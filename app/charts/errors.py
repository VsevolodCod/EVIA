class ChartError(Exception):
    code = "chart_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }


class InvalidDashboardError(ChartError):
    code = "invalid_dashboard"


class UnknownSourceError(ChartError):
    code = "unknown_source"


class UnknownFieldError(ChartError):
    code = "unknown_field"


class UnsupportedTypeError(ChartError):
    code = "unsupported_type"


class UnsupportedJoinError(ChartError):
    code = "unsupported_join"


class InvalidFilterError(ChartError):
    code = "invalid_filter"


class ChartExecutionError(ChartError):
    code = "execution_error"
