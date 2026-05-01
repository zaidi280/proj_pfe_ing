import os

from fastapi import APIRouter, Depends, Request
from fastapi import HTTPException
from pydantic import BaseModel

from controllers.llm_controller import LLMProviderAccessError, LLMProviderConfigError, LLMRateLimitError
from services.chat_workflow import GptChatWorkflow
from services.auth_service import AuthUser, require_permissions, require_roles
from services.audit_service import log_audit_event

router = APIRouter(
	prefix="/chat",
	tags=["Chat"],
	dependencies=[Depends(require_roles("admin", "comptable"))],
)
_chat_workflow: GptChatWorkflow | None = None


class ChatAskRequest(BaseModel):
	prompt: str
	session_id: str | None = None


def _build_chat_workflow() -> GptChatWorkflow:
	api_key = os.getenv("LLAMA_API_KEY")
	model_name = os.getenv("LLAMA_MODEL")
	base_url = os.getenv("LLAMA_BASE_URL", "https://api.groq.com/openai/v1")
	fallback_api_key = os.getenv("SAMBANOVA_API_KEY")
	fallback_model_name = os.getenv("SAMBANOVA_MODEL")
	fallback_base_url = os.getenv("SAMBANOVA_BASE_URL")

	if not api_key:
		raise RuntimeError("LLAMA_API_KEY is missing in environment")
	if not model_name:
		raise RuntimeError("LLAMA_MODEL is missing in environment")
	if fallback_api_key and not fallback_base_url:
		raise RuntimeError("SAMBANOVA_BASE_URL is missing in environment")

	return GptChatWorkflow(
		api_key=api_key,
		model_name=model_name,
		base_url=base_url,
		fallback_api_key=fallback_api_key,
		fallback_model_name=fallback_model_name,
		fallback_base_url=fallback_base_url,
		timeout=300.0,
	)


def _get_chat_workflow() -> GptChatWorkflow:
	global _chat_workflow
	if _chat_workflow is None:
		_chat_workflow = _build_chat_workflow()
	return _chat_workflow


@router.get("/health")
def chat_health():
	return {"status": "ok", "service": "chat"}


@router.post("/ask")
async def ask_chat(
	payload: ChatAskRequest,
	request: Request,
	current_user: AuthUser = Depends(require_permissions("ask_chat")),
):
	if not payload.prompt or not payload.prompt.strip():
		raise HTTPException(status_code=400, detail="prompt is required")

	try:
		result = await _get_chat_workflow().ask(
			payload.prompt,
			session_id=(payload.session_id or "default").strip() or "default",
		)
	except LLMProviderConfigError as exc:
		raise HTTPException(
			status_code=503,
			detail=(
				"LLM provider/model configuration failed for all configured providers. "
				f"Details: {exc}"
			),
		)
	except LLMProviderAccessError as exc:
		raise HTTPException(
			status_code=503,
			detail=(
				"LLM provider authentication/authorization failed for all configured providers. "
				f"Details: {exc}"
			),
		)
	except LLMRateLimitError as exc:
		raise HTTPException(
			status_code=429,
			detail=(
				"LLM provider rate limit reached. Please retry in a few minutes. "
				f"Details: {exc}"
			),
		)
	except ValueError as exc:
		raise HTTPException(status_code=422, detail=str(exc))
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Chat workflow failed: {exc}")

	log_audit_event(
		actor=current_user,
		action="chat_ask",
		request_method=request.method,
		request_path=request.url.path,
		client_ip=request.client.host if request.client else None,
		entity_type="chat_session",
		entity_id=(payload.session_id or "default").strip() or "default",
		summary="Question envoyee a l'agent IA",
		metadata={
			"prompt_preview": (payload.prompt or "")[:120],
		},
	)

	return result
