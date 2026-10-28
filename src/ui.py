import sys
import uuid
import json
from pathlib import Path
import streamlit as st
import pandas as pd
from langchain_core.messages import HumanMessage, ToolMessage

# ==========================================
# 1. IMMEDIATE PATH & ENVIRONMENT RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent  # points to src/
project_root = script_dir.parent  # climbs to project root

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.config import get_settings
from src.services.container import get_services
from src.services.audit import AuditEvent
from src.services.database import create_sql_engine
from src.services.errors import ServiceError
from src.orchestrator import fde_agent

settings = get_settings()
services = get_services()


def write_audit_log(session_id, node_name, tool_name, content):
    """UI compatibility wrapper; persistence lives in a framework-independent service."""
    try:
        services.audit.write(AuditEvent(session_id, node_name, tool_name, content))
    except ServiceError:
        import logging

        logging.getLogger(__name__).error(
            "Audit persistence failed; event was not stored."
        )


# ==========================================
# 3. PAGE CONFIGURATION & ENTERPRISE THEME
# ==========================================
st.set_page_config(
    page_title="FDE Supply Chain Dispatch Console",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .stApp { background-color: #0B0E14; color: #E2E8F0; }
    div[data-testid="stSidebar"] { background-color: #111622; border-right: 1px solid #1E293B; }
    .stMarkdown code { background-color: #1E293B !important; color: #38BDF8 !important; }
</style>
""",
    unsafe_allow_html=True,
)

# ==========================================
# 4. MULTI-USER STATE & THREAD MANAGEMENT
# ==========================================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "ui_messages" not in st.session_state:
    st.session_state.ui_messages = []

thread_config = {"configurable": {"thread_id": st.session_state.thread_id}}

# ==========================================
# 5. SIDEBAR NAVIGATION & METADATA
# ==========================================
with st.sidebar:
    st.image(
        str(script_dir / "image_L25X5q.png")
        if (script_dir / "image_L25X5q.png").exists()
        else "https://cdn-icons-png.flaticon.com/512/2830/2830305.png",
        width=65,
    )
    st.title("FDE Command Center")

    app_mode = st.radio(
        "System Mode", ["🧊 Dispatch Console", "🛡️ Security & Audit Logs"]
    )

    st.markdown("---")
    st.caption(f"Session Token: `{st.session_state.thread_id[:8]}...`")
    st.markdown(f"**Reasoning Architecture:** `{settings.agent_llm}`")

    st.markdown("---")
    if st.button("🗑️ Purge Dispatch Workspace Session", use_container_width=True):
        st.session_state.ui_messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

# ==========================================
# 6. VIEW ROUTING (DISPATCH VS AUDIT)
# ==========================================

if app_mode == "🧊 Dispatch Console":
    # ------------------------------------------
    # TAB 1: CHAT UI & AGENT EXECUTION
    # ------------------------------------------
    st.title("Cold-Chain Incident Control Dashboard")
    st.caption(
        "Production Data Engineering Pipeline • Real-Time Decision Optimization Platform"
    )

    for entry in st.session_state.ui_messages:
        with st.chat_message(
            entry["role"], avatar="👤" if entry["role"] == "user" else "🤖"
        ):
            if "traces" in entry:
                for trace in entry["traces"]:
                    if trace["type"] == "tool_input":
                        st.markdown(f"**⚡ Intent Recognized:** `{trace['name']}`")
                        with st.expander(
                            f"📥 View Generated Input ({trace['name']})", expanded=False
                        ):
                            st.json(trace["args"])
                    elif trace["type"] == "tool_output":
                        with st.expander(
                            f"📤 View Raw Output ({trace['name']})", expanded=False
                        ):
                            st.code(trace["content"], language="text")
            st.markdown(entry["content"])

    if user_input := st.chat_input(
        "Query fleet telemetry, corridor updates, or compliance thresholds..."
    ):
        st.session_state.ui_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            final_response = ""
            current_traces = []

            with st.status(
                "🧠 Initializing Core Reasoner Node...", expanded=True
            ) as status:
                events = fde_agent.stream(
                    {"messages": [HumanMessage(content=user_input)]},
                    config=thread_config,
                    stream_mode="updates",
                )

                for event in events:
                    for node_name, node_state in event.items():
                        if node_name == "reasoner":
                            latest_msg = node_state["messages"][-1]

                            # A. Intercept Tool Call Requests (Inputs)
                            if (
                                hasattr(latest_msg, "tool_calls")
                                and latest_msg.tool_calls
                            ):
                                status.update(
                                    label="🧠 Agent generated tool parameters..."
                                )
                                for tool_call in latest_msg.tool_calls:
                                    st.markdown(
                                        f"**⚡ Intent Recognized:** `{tool_call['name']}`"
                                    )
                                    with st.expander(
                                        f"📥 View Generated Input ({tool_call['name']})",
                                        expanded=False,
                                    ):
                                        st.json(tool_call["args"])

                                    current_traces.append(
                                        {
                                            "type": "tool_input",
                                            "name": tool_call["name"],
                                            "args": tool_call["args"],
                                        }
                                    )

                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="reasoner",
                                        tool_name=tool_call["name"],
                                        content=json.dumps(tool_call["args"]),
                                    )

                            # B. Intercept Final Generation
                            if latest_msg.content:
                                final_response = latest_msg.content
                                status.update(
                                    label="📝 Generating Operational Resolution Report..."
                                )

                                write_audit_log(
                                    session_id=st.session_state.thread_id,
                                    node_name="reasoner_final",
                                    tool_name="LLM Text Synthesis",
                                    content=final_response,
                                )

                        elif node_name == "tools":
                            status.update(
                                label="🔧 Executing Enterprise Subsystem Tools..."
                            )
                            for msg in node_state.get("messages", []):
                                if isinstance(msg, ToolMessage):
                                    with st.expander(
                                        f"📤 View Raw Output ({msg.name})",
                                        expanded=False,
                                    ):
                                        st.code(msg.content, language="text")

                                    current_traces.append(
                                        {
                                            "type": "tool_output",
                                            "name": msg.name,
                                            "content": msg.content,
                                        }
                                    )

                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="tools",
                                        tool_name=msg.name,
                                        content=msg.content,
                                    )

                status.update(
                    label="Incident Matrix Evaluation Complete",
                    state="complete",
                    expanded=False,
                )

            if final_response:
                st.markdown(final_response)
                st.session_state.ui_messages.append(
                    {
                        "role": "assistant",
                        "content": final_response,
                        "traces": current_traces,
                    }
                )
            else:
                error_fallback = "⚠️ Execution Timeout: System engine encountered an unresolved processing edge case."
                st.error(error_fallback)


elif app_mode == "🛡️ Security & Audit Logs":
    # ------------------------------------------
    # TAB 2: AUDIT LOG VIEWER (REQUIRES ADMIN CREDENTIALS FROM .ENV OR INPUT)
    # ------------------------------------------
    st.title("🛡️ Enterprise Agent Audit Trail")
    st.caption("Secure database inspection of FDE_VIEWS.AgentAuditLog")

    st.markdown("### Database Authorization Gate")
    st.markdown(
        "Enter high-privilege administrative credentials (defined in `.env` as `SQL_ADMIN_USER`) to query audit logs."
    )

    with st.form("admin_auth_form"):
        col1, col2 = st.columns(2)
        with col1:
            input_user = st.text_input("Admin Username", value=settings.sql_admin_user)
        with col2:
            input_pass = st.text_input("Admin Password", type="password", value="")

        submit_admin = st.form_submit_button(
            "Authenticate & Load Logs", use_container_width=True
        )

    if submit_admin:
        expected_admin_user = settings.sql_admin_user
        expected_admin_pass = settings.sql_admin_password.get_secret_value()

        if (
            expected_admin_pass
            and input_user == expected_admin_user
            and input_pass == expected_admin_pass
        ):
            try:
                admin_engine = create_sql_engine(settings, admin=True)
                try:
                    df = pd.DataFrame(services.audit.read_recent(engine=admin_engine))
                finally:
                    admin_engine.dispose()

                st.success("✅ Authenticated successfully as Admin.")

                if not df.empty:
                    st.dataframe(
                        df,
                        column_config={
                            "LogID": st.column_config.NumberColumn("ID", format="%d"),
                            "Timestamp": st.column_config.DatetimeColumn(
                                "Execution Time", format="DD/MM/YYYY-h:mm a"
                            ),
                            "SessionID": "Session Token",
                            "NodeExecuted": "Graph Node",
                            "ToolName": "Tool Triggered",
                            "Content": "Raw Payload Data",
                        },
                        hide_index=True,
                        use_container_width=True,
                        height=600,
                    )
                else:
                    st.info(
                        "No audit logs found in the database. Run a query in the Dispatch Console first."
                    )

            except Exception:
                st.error("Audit database unavailable.")
        else:
            st.error("❌ Invalid Administrator Credentials.")
