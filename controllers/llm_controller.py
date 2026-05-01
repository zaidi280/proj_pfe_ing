"""
Controller: LLMController
Responsibility: All communication with OpenAI-compatible APIs via LLM entity.
"""

from entities.invoice_data import InvoiceData
from entities.llm import LLM


class LLMRateLimitError(RuntimeError):
    """Raised when the upstream LLM provider returns a rate-limit response."""


class LLMProviderAccessError(RuntimeError):
    """Raised when the upstream LLM provider rejects access/authentication."""


class LLMProviderConfigError(RuntimeError):
    """Raised when upstream provider rejects the configured model/endpoint."""


class LLMController:
    def __init__(self, llm: LLM):
        self.llm = llm

    def call_api(self, messages: list[dict], **kwargs) -> str:
        return self._execute(messages=messages, **kwargs)

    def call_api_for_json(self, messages: list[dict], **kwargs) -> InvoiceData:
        raw = self._execute(messages=messages, response_format_json=True, **kwargs)
        return InvoiceData.from_raw_text(raw)

    def build_system_message(self, content: str) -> dict:
        return {"role": "system", "content": content}

    def build_user_message(self, content: str) -> dict:
        return {"role": "user", "content": content}
    def _extract_text(self, content) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text")
                else:
                    text = getattr(block, "text", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            return "\n".join(parts).strip()
        return ""

    def _execute(self, messages: list[dict], response_format_json: bool = False, **kwargs) -> str:
        try:
            params = self.llm.build_params(
                messages=messages,
                response_format_json=response_format_json,
                **kwargs,
            )
            response = self.llm.create_chat_completion(**params)
            return self._extract_text(response.choices[0].message.content)
        except Exception as exc:
            err_text = str(exc)
            err_text_l = err_text.lower()
            if (
                "429" in err_text
                or "rate limit" in err_text_l
                or "rate_limit" in err_text_l
                or "too many requests" in err_text_l
            ):
                raise LLMRateLimitError(f"LLM rate limit reached: {err_text}") from exc
            if (
                "401" in err_text
                or "403" in err_text
                or "forbidden" in err_text_l
                or "unauthorized" in err_text_l
                or "invalid api key" in err_text_l
                or "permission denied" in err_text_l
            ):
                raise LLMProviderAccessError(f"LLM provider access denied: {err_text}") from exc
            if (
                "404" in err_text
                or "model not found" in err_text_l
                or "not found" in err_text_l
            ):
                raise LLMProviderConfigError(f"LLM provider/model configuration error: {err_text}") from exc
            raise RuntimeError(f"LLM request failed: {exc}") from exc

   
