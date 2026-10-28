class ServiceError(RuntimeError):
    """Safe public error; underlying exceptions must not be shown to the model/UI."""
