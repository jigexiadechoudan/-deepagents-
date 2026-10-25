from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_deepseek import ChatDeepSeek

from research_agent.agent.middleware import StructuredOutputRepairMiddleware
from research_agent.agent.prompts import build_system_prompt
from research_agent.config import Settings
from research_agent.schemas.design import ExtractionResult


def create_extraction_agent(settings: Settings, reference: str, material: str):
    model = ChatDeepSeek(**settings.model_params)
    return create_deep_agent(
        model=model,
        system_prompt=build_system_prompt(reference),
        response_format=ToolStrategy(ExtractionResult),
        skills=["/skills/"],
        middleware=[StructuredOutputRepairMiddleware(
            max_rounds=settings.max_structured_repair_rounds,
            material=material,
            max_check_rounds=settings.max_check_rounds,
        )],
    )
