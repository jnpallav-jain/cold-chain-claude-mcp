"""Streamlit frontend for the shared Claude SDK runner."""

import asyncio
import hmac
import streamlit as st
import pandas as pd
from src.config import get_settings
from src.orchestrator import AgentRunner, AgentSession
from src.services.container import get_services
from src.services.database import create_sql_engine
from src.services.errors import ServiceError

st.set_page_config(page_title="Cold-Chain Claude MCP", page_icon="🧊", layout="wide")
settings = get_settings()
st.title("Cold-Chain Logistics Assistant")
st.caption("Claude Agent SDK · MCP tools · Synthetic historical fleet data")

if "agent_session" not in st.session_state:
    st.session_state.agent_session = AgentSession()
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("Dispatch workspace")
    mode = st.radio("View", ["Dispatch console", "Audit log"])
    st.caption(f"Model: {settings.claude_model}")
    st.caption(f"Conversation: {st.session_state.agent_session.id[:8]}")
    st.caption(
        "Fleet data is synthetic and historical. Weather is current; its disruption score is a demonstration heuristic."
    )
    if st.button("New conversation", use_container_width=True):
        st.session_state.agent_session.reset()
        st.session_state.messages = []
        st.rerun()

if mode == "Dispatch console":
    for entry in st.session_state.messages:
        with st.chat_message(entry["role"]):
            st.markdown(entry["content"])
            if entry.get("traces"):
                with st.expander("Execution trace"):
                    st.json(entry["traces"])
    configured = bool(
        settings.anthropic_api_key.get_secret_value() and settings.claude_model
    )
    if not configured:
        st.info(
            "Add ANTHROPIC_API_KEY and CLAUDE_MODEL to the local .env file before asking a question."
        )
    if prompt := st.chat_input(
        "Ask about fleet temperatures, weather, or SOP rules", disabled=not configured
    ):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            answer_box = st.empty()
            status_box = st.empty()
            traces = []

            async def execute():
                # Mutable result state is scoped to this request, not shared between browser sessions.
                result = {"text": "", "preview": "", "errors": []}
                runner = AgentRunner()
                async for event in runner.stream_turn(
                    st.session_state.agent_session, prompt
                ):
                    if event.kind == "text_delta":
                        result["preview"] += event.data["text"]
                        answer_box.markdown(result["preview"] + " ▌")
                    elif event.kind == "tool_start":
                        status_box.info("Retrieving evidence…")
                        traces.append({"kind": event.kind, **event.data})
                    elif event.kind == "tool_result":
                        traces.append({"kind": event.kind, **event.data})
                    elif event.kind == "complete":
                        result["text"] = event.data["text"]
                        status_box.caption(
                            f"Complete · {event.data['turns']} model turns"
                        )
                    elif event.kind in {"error", "audit_warning"}:
                        result["errors"].append(event.data["message"])
                return result

            result = asyncio.run(execute())
            content = (
                result["text"]
                or "Request did not complete. Start a new conversation or try again."
            )
            answer_box.markdown(content)
            for message in result["errors"]:
                st.warning(message)
            with st.expander("Execution trace"):
                st.json(traces)
            st.session_state.messages.append(
                {"role": "assistant", "content": content, "traces": traces}
            )
    st.divider()
    st.subheader("Human approval · simulation only")
    st.caption(
        "Creates a local simulated incident record after authenticated approval. No driver contact, external notification, or shipment change."
    )
    approvals = get_services().approvals
    if approvals is None or not approvals.configured:
        st.info(
            "Operator approval is disabled. Run python -m scripts.configure_operator in the project terminal to set a separate operator password."
        )
    else:
        try:
            proposals = approvals.list_for_session(st.session_state.agent_session.id)
            if not proposals:
                st.caption("No escalation proposals in this conversation.")
            for proposal in proposals:
                with st.expander(
                    f"{proposal['status'].upper()} · {proposal['proposal_id'][:8]}"
                ):
                    # Model-supplied text is rendered as JSON, never as a control or credential prompt.
                    st.json(proposal)
                    if proposal["status"] == "pending":
                        with st.form(
                            "decision_" + proposal["proposal_id"], clear_on_submit=True
                        ):
                            operator = st.text_input(
                                "Operator", value=settings.approval_operator
                            )
                            operator_password = st.text_input(
                                "Operator password", type="password"
                            )
                            choice = st.radio(
                                "Decision",
                                ["Reject", "Approve and create simulated incident"],
                            )
                            reviewed = st.checkbox(
                                "I reviewed this exact proposal and its supporting evidence."
                            )
                            commit = st.form_submit_button("Submit human decision")
                        if commit:
                            if not reviewed:
                                st.warning(
                                    "Review the proposal and confirm before submitting."
                                )
                            else:
                                try:
                                    outcome = approvals.decide(
                                        st.session_state.agent_session.id,
                                        proposal["proposal_id"],
                                        proposal["digest"],
                                        "approve"
                                        if choice.startswith("Approve")
                                        else "reject",
                                        operator=operator,
                                        password=operator_password,
                                    )
                                    st.success(
                                        "Human decision saved. Simulation only; no external notification."
                                    )
                                    st.json(outcome)
                                except ServiceError as error:
                                    st.error(str(error))
            if proposals:
                with st.expander("Durable approval decision trail"):
                    st.json(approvals.trail(st.session_state.agent_session.id))
        except ServiceError as error:
            st.error(str(error))
else:
    st.subheader("Administrative audit viewer")
    with st.form("audit_login"):
        username = st.text_input("Admin username", value=settings.sql_admin_user)
        password = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button("Load audit log")
    if submitted:
        expected = settings.sql_admin_password.get_secret_value()
        if (
            expected
            and hmac.compare_digest(username, settings.sql_admin_user)
            and hmac.compare_digest(password, expected)
        ):
            engine = None
            try:
                engine = create_sql_engine(settings, admin=True)
                records = get_services().audit.read_recent(engine=engine)
                if records:
                    st.dataframe(
                        pd.DataFrame(records), hide_index=True, use_container_width=True
                    )
                else:
                    st.info("No audit events recorded.")
            except ServiceError:
                st.error("Audit storage is unavailable.")
            finally:
                if engine is not None:
                    engine.dispose()
        else:
            st.error("Invalid administrative credentials.")
