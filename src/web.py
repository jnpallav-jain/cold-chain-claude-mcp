"""Authenticated website entry point. Rejected admission cannot construct an SDK runner."""

from src.orchestrator import AgentEvent, AgentRunner
from src.services.demo import get_demo_control
from src.services.errors import ServiceError


async def stream_web_turn(
    session, prompt, token, *, control=None, runner_factory=AgentRunner
):
    control = control if control is not None else get_demo_control()
    try:
        request_id = control.admit(token)
    except ServiceError as error:
        yield AgentEvent("error", {"message": str(error)})
        return
    try:
        runner = runner_factory()
        # A fresh admission reserves a whole request allowance; never refund from cumulative SDK costs.
        runner.settings = runner.settings.model_copy(
            update={
                "claude_max_budget_usd": min(
                    runner.settings.claude_max_budget_usd,
                    control.settings.demo_request_budget_cents / 100,
                )
            }
        )
        async for event in runner.stream_turn(session, prompt):
            yield event
    finally:
        try:
            control.finish(request_id)
        except ServiceError:
            # Lease remains active until expiry, failing toward less capacity rather than unbounded calls.
            import logging

            logging.getLogger(__name__).error(
                "Demo admission completion could not be saved request=%s", request_id
            )
