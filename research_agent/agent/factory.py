from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from research_agent.agent.model import ChatDeepSeek

from research_agent.agent.middleware import StructuredOutputRepairMiddleware
from research_agent.agent.prompts import build_system_prompt
from research_agent.config import Settings
from research_agent.schemas.design import ExtractionResult


def create_extraction_agent(settings: Settings, reference: str, material: str,
                            model_calls: list[dict] | None = None):
    model = ChatDeepSeek(**settings.model_params)
    return create_deep_agent(
        model=model,
        system_prompt=build_system_prompt(reference),
        response_format=ToolStrategy(
            ExtractionResult, tool_message_content="已接收完整候选，宿主将执行全量检查。"
        ),
        skills=["/skills/"],
        middleware=[StructuredOutputRepairMiddleware(
            max_rounds=settings.max_structured_repair_rounds,
            model_calls=model_calls,
        )],
    )
