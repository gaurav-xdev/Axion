"""Central typed domain exception hierarchy for the Axion autonomous business agent.
Ensures fail-closed operations and explicit, typed error reporting without synthetic fallbacks.
"""

class AxionBaseException(Exception):
    """Root base exception for all Axion agent and business runtime errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message


class MissingRequiredContextError(AxionBaseException):
    """Raised when a procedure step or business workflow lacks mandatory runtime context."""
    def __init__(self, missing_key: str, step_id: str = None, details: dict = None):
        msg = f"Missing required context key '{missing_key}'"
        if step_id:
            msg += f" for step '{step_id}'"
        super().__init__(msg, details)
        self.missing_key = missing_key
        self.step_id = step_id


class ProviderNotConfiguredError(AxionBaseException):
    """Raised when an external provider (LLM, Payment, SMTP, etc.) is unconfigured or placeholder."""
    def __init__(self, provider_name: str, missing_config: str = None, details: dict = None):
        msg = f"External provider '{provider_name}' is not configured"
        if missing_config:
            msg += f" (missing: {missing_config})"
        msg += ". Synthetic success is strictly prohibited in production paths."
        super().__init__(msg, details)
        self.provider_name = provider_name
        self.missing_config = missing_config


class UnsupportedActionError(AxionBaseException):
    """Raised when a skill or worker encounters an unhandled or invalid action type."""
    def __init__(self, action_type: str, step_id: str = None, details: dict = None):
        msg = f"Unsupported or unhandled action type '{action_type}'"
        if step_id:
            msg += f" in step '{step_id}'"
        super().__init__(msg, details)
        self.action_type = action_type
        self.step_id = step_id


class ExternalVerificationRequiredError(AxionBaseException):
    """Raised when an operation cannot proceed without verifiable external confirmation."""
    def __init__(self, entity_id: str, reason: str, details: dict = None):
        msg = f"External verification required for entity '{entity_id}': {reason}"
        super().__init__(msg, details)
        self.entity_id = entity_id
        self.reason = reason


class InvalidStateTransitionError(AxionBaseException):
    """Raised when an invalid state transition is attempted on a project or run."""
    def __init__(self, current_state: str, target_state: str, entity_name: str = "Entity", details: dict = None):
        msg = f"Invalid state transition for {entity_name} from '{current_state}' to '{target_state}'"
        super().__init__(msg, details)
        self.current_state = current_state
        self.target_state = target_state
        self.entity_name = entity_name


class SandboxExecutionError(AxionBaseException):
    """Raised when an isolated sandbox test or verification execution fails."""
    def __init__(self, exit_code: int, stdout: str, stderr: str, details: dict = None):
        msg = f"Sandbox execution failed with exit code {exit_code}: {stderr or stdout}"
        super().__init__(msg, details)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class SecurityViolationError(AxionBaseException):
    """Raised when an operation violates security policy, sandbox confinement, or SSRF rules."""
    def __init__(self, violation_type: str, message: str, details: dict = None):
        super().__init__(f"Security policy violation [{violation_type}]: {message}", details)
        self.violation_type = violation_type
