class ServiceError(RuntimeError):
    """Safe public error; underlying exceptions must not be shown to the model/UI."""


class TransientServiceError(ServiceError):
    """Completed read request failed transiently; a bounded retry can be safe."""
