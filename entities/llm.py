from llama_index.llms.openai_like import OpenAILike


class LLM(OpenAILike):
	def __init__(
		self,
		api_key: str,
		model_name: str,
		base_url: str | None = None,
		thinking: bool = False,
		extra: dict | None = None,
	) -> None:
		super().__init__(
			model=model_name,
			api_key=api_key,
			api_base=base_url,
			is_chat_model=True,
		)
		# OpenAILike is a Pydantic model; store custom values in private attrs.
		object.__setattr__(self, "_thinking", thinking)
		object.__setattr__(self, "_extra", extra or {})

	@property
	def model_name(self) -> str:
		return self.model

	@property
	def base_url(self) -> str | None:
		return self.api_base

	@property
	def thinking(self) -> bool:
		return bool(getattr(self, "_thinking", False))

	@property
	def extra(self) -> dict:
		return dict(getattr(self, "_extra", {}))

	def build_params(self, messages: list[dict], response_format_json: bool = False, **overrides) -> dict:
		params = {
			"model": self.model_name,
			"messages": messages,
			**self.extra,
		}
		# Do not inject provider-specific args by default (e.g., `thinking`),
		# because many OpenAI-compatible endpoints reject unknown top-level kwargs.
		if response_format_json:
			params["response_format"] = {"type": "json_object"}
		params.update(overrides)
		return params

	def create_chat_completion(self, **params):
		"""Public wrapper around the underlying OpenAI-compatible client."""
		return self._get_client().chat.completions.create(**params)
