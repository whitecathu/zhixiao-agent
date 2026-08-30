"""Built-in plugin module specifiers. Composition order is resolved by inject."""

BUILTIN_MODULES = (
    "zhixiao_agent.plugins.core_tools",
    "zhixiao_agent.plugins.core_commands",
    "zhixiao_agent.plugins.core_skills",
    "zhixiao_agent.plugins.mcp_store",
    "zhixiao_agent.plugins.workspace_extensions",
)
