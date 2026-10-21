from langchain_core.messages import HumanMessage, SystemMessage

from modules.ai.prompts.loader import PromptDir

from ..dto import FormGenerateRequest


prompts = PromptDir(__file__)


def build_messages(request: FormGenerateRequest) -> list:
    constraints = [f"Use at most {request.max_questions} questions."]
    if request.type:
        constraints.append(f'The form type must be "{request.type}".')
    if request.submitter_type:
        constraints.append(f"Submitter types: {', '.join(request.submitter_type)}.")
    if request.language:
        constraints.append(f"Write the form in {request.language}.")

    return [
        SystemMessage(content=prompts.render("system")),
        HumanMessage(
            content=prompts.render(
                "user",
                prompt=request.prompt,
                constraints="\n".join(f"- {c}" for c in constraints),
            )
        ),
    ]
