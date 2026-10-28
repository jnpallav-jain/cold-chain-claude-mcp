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
from src.services.demo import get_demo_control
from src.web import stream_web_turn
from src.presentation import evidence_cards

st.set_page_config(page_title="Cold-Chain Claude MCP", page_icon="🧊", layout="wide")
settings = get_settings()
if settings.demo_mode:
    control = get_demo_control()
    token = st.session_state.get("_demo_token")
    authenticated = False
    if token:
        try:
            control.validate(token)
            authenticated = True
        except ServiceError:
            st.session_state.pop("_demo_token", None)
            st.session_state.pop("agent_session", None)
            st.session_state.pop("messages", None)
    if not authenticated:
        st.title("Cold-chain operations demo")
        st.caption(
            "Invite-only access · synthetic fleet records · no external dispatch actions"
        )
        if not control.configured:
            st.info("Demo access is not configured. Contact the demo owner.")
            st.stop()
        with st.form("demo_login", clear_on_submit=True):
            demo_username = st.text_input("Demo username")
            demo_password = st.text_input("Demo password", type="password")
            sign_in = st.form_submit_button("Sign in")
        if sign_in:
            try:
                st.session_state["_demo_token"] = control.login(
                    demo_username, demo_password
                )
                st.rerun()
            except ServiceError as error:
                st.error(str(error))
        st.stop()

st.title("Cold-chain operations workspace")
st.caption("Claude Agent SDK · MCP tools · Synthetic historical fleet data")

if "agent_session" not in st.session_state:
    st.session_state.agent_session = AgentSession()
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("Dispatch workspace")
    mode = st.radio(
        "View",
        ["Dispatch console"]
        if settings.demo_mode
        else ["Dispatch console", "Audit log"],
    )
    st.caption(f"Model: {settings.claude_model}")
    st.caption(f"Conversation: {st.session_state.agent_session.id[:8]}")
    st.caption(
        "Fleet data is synthetic and historical. Weather is current; its disruption score is a demonstration heuristic."
    )
    if st.button("New conversation", use_container_width=True):
        st.session_state.agent_session.reset()
        st.session_state.messages = []
        st.rerun()
    if settings.demo_mode and st.button("Sign out"):
        try:
            control.logout(st.session_state.pop("_demo_token", ""))
        except ServiceError:
            st.warning(
                "Sign-out could not update storage; this browser session was cleared."
            )
        st.session_state.agent_session.reset()
        st.session_state.messages = []
        st.rerun()


def render_evidence(traces):
    cards = evidence_cards(traces)
    if not cards:
        return
    with st.expander("Evidence and sources", expanded=True):
        for card in cards:
            data = card["data"]
            if card["tool"] == "query_telemetry_db":
                st.caption(
                    "Fleet evidence · fabricated historical observations, not live shipments"
                )
                if data.get("rows"):
                    st.dataframe(
                        pd.DataFrame(data["rows"], columns=data["columns"]),
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.info("No matching historical observations were returned.")
                if data.get("normalized_sql"):
                    st.code(data["normalized_sql"], language="sql")
            elif card["tool"] == "fetch_corridor_conditions":
                st.caption(
                    "Weather observation · "
                    + str(data.get("observed_at", "timestamp unavailable"))
                )
                st.write(
                    {
                        key: data.get(key)
                        for key in (
                            "temperature_c",
                            "wind_kmh",
                            "latitude",
                            "longitude",
                        )
                    }
                )
                st.caption(
                    "Wind-based disruption score is a demo heuristic. Current weather does not establish a cause for historical cargo readings."
                )
            elif card["tool"] == "search_compliance_sop":
                for passage in data.get("passages", []):
                    metadata = passage.get("metadata", {})
                    st.caption(
                        "SOP source · "
                        + metadata.get("source_file", "unknown")
                        + " · "
                        + metadata.get("Header_3", "section unavailable")
                    )
                    st.text(passage.get("text", ""))
            elif card["tool"] == "propose_incident_escalation":
                st.caption(
                    "Simulation proposal · "
                    + data.get("status", "unknown")
                    + " · no external notification"
                )


if mode == "Dispatch console":
    for entry in st.session_state.messages:
        with st.chat_message(entry["role"]):
            st.markdown(entry["content"])
            if entry.get("traces"):
                render_evidence(entry["traces"])
                with st.expander("Execution trace"):
                    st.json(entry["traces"])
    configured = bool(
        settings.anthropic_api_key.get_secret_value() and settings.claude_model
    )
    if not configured:
        st.info(
            "Add ANTHROPIC_API_KEY and CLAUDE_MODEL to the local .env file before asking a question."
        )
    st.caption(
        "Start with a sample question, then inspect the evidence behind the answer."
    )
    selected_prompt = None
    samples = [
        (
            "Temperature policy",
            "What is the fresh-perishables temperature range, and is exactly 4 C a breach? Cite the SOP.",
        ),
        (
            "Assess fleet readings",
            "Assess the synthetic historical fleet observations above 4 C. Check weather at a returned location and retrieve the relevant SOP. Distinguish current weather from historical records.",
        ),
        (
            "Propose a simulation",
            "Assess the synthetic historical temperature breaches with telemetry and SOP, then propose one simulated escalation for human review. Do not execute it.",
        ),
    ]
    for column, (label, question) in zip(st.columns(3), samples):
        if column.button(label, disabled=not configured, use_container_width=True):
            selected_prompt = question
    typed_prompt = st.chat_input(
        "Ask about fleet temperatures, weather, or SOP rules", disabled=not configured
    )
    if prompt := selected_prompt or typed_prompt:
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
                events = (
                    stream_web_turn(
                        st.session_state.agent_session,
                        prompt,
                        st.session_state["_demo_token"],
                    )
                    if settings.demo_mode
                    else AgentRunner().stream_turn(
                        st.session_state.agent_session, prompt
                    )
                )
                async for event in events:
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
            render_evidence(traces)
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
    previous_decision = st.session_state.pop("_approval_outcome", None)
    if (
        previous_decision
        and previous_decision["session_id"] == st.session_state.agent_session.id
    ):
        st.success("Human decision saved. Simulation only; no external notification.")
        st.json(previous_decision["outcome"])
    approvals = get_services().approvals
    if approvals is None or not approvals.configured:
        st.info(
            "Operator approval is disabled. Contact the demo owner."
            if settings.demo_mode
            else "Operator approval is disabled. Run python -m scripts.configure_operator in the project terminal to set a separate operator password."
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
                                    st.session_state["_approval_outcome"] = {
                                        "session_id": st.session_state.agent_session.id,
                                        "outcome": outcome,
                                    }
                                    st.rerun()
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
