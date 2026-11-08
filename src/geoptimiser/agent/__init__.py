"""Day 5: a bounded ReAct agent (LangGraph + OpenRouter) over the existing pipeline.

Importing this package does not import LangGraph or LangChain; they are loaded when a
graph is built or a model is first called (``pip install 'geoptimiser[agent]'``).
"""

from geoptimiser.agent.config import (
    DEFAULT_MODEL_ID,
    AgentConfig,
    AgentConfigError,
    ModelConfig,
    load_agent_config,
)
from geoptimiser.agent.graph import AgentRequest, build_graph, run_agent, write_trace
from geoptimiser.agent.models import (
    AgentModel,
    ChatMessage,
    ModelError,
    ModelUnavailable,
    OpenRouterModel,
)
from geoptimiser.agent.runtime import AgentRuntime, initial_state
from geoptimiser.agent.state import ActionRecord, AgentResult, AgentState
from geoptimiser.agent.tools import (
    AgentContext,
    ToolError,
    ToolRegistry,
    ToolSpec,
    default_registry_tools,
)

__all__ = [
    "DEFAULT_MODEL_ID",
    "ActionRecord",
    "AgentConfig",
    "AgentConfigError",
    "AgentContext",
    "AgentModel",
    "AgentRequest",
    "AgentResult",
    "AgentRuntime",
    "AgentState",
    "ChatMessage",
    "ModelConfig",
    "ModelError",
    "ModelUnavailable",
    "OpenRouterModel",
    "ToolError",
    "ToolRegistry",
    "ToolSpec",
    "build_graph",
    "default_registry_tools",
    "initial_state",
    "load_agent_config",
    "run_agent",
    "write_trace",
]
