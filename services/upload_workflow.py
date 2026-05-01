import base64
from typing import Any

from workflows import Workflow, step
from workflows.events import Event, StartEvent, StopEvent

from controllers.llm_controller import LLMController
from entities.invoice_data import InvoiceData
from entities.llm import LLM


class UploadStartEvent(StartEvent):
	image_bytes_list: list[bytes]
	mime_type: str = "image/jpeg"


class ValidatedUploadEvent(Event):
	image_bytes_list: list[bytes]
	mime_type: str


class EncodedImageEvent(Event):
	image_base64_list: list[str]
	mime_type: str


class MessagesReadyEvent(Event):
	messages: list[dict]


class KimiUploadWorkflow(Workflow):
	def __init__(
		self,
		api_key: str,
		model_name: str,
		base_url: str | None = None,
		thinking: bool = False,
		extra: dict | None = None,
		timeout: float | None = 300.0,
	):
		super().__init__(timeout=timeout)
		self.kimi_llm: LLM = LLM(
			api_key=api_key,
			model_name=model_name,
			base_url=base_url,
			thinking=thinking,
			extra=extra,
		)
		self._llm_controller = LLMController(self.kimi_llm)
		# Keep extraction fast and deterministic for large invoices.
		self._request_kwargs = {
			"max_tokens": 1500,
			"temperature": 0.0,
			"top_p": 1.0,
			"stream": False,
			"timeout": 180.0,
			"extra_body": {"chat_template_kwargs": {"thinking": False}},
		}

	@step
	async def validate_upload(self, ev: UploadStartEvent) -> ValidatedUploadEvent:
		if not ev.image_bytes_list:
			raise ValueError("image_bytes_list is required")
		if any(not image_bytes for image_bytes in ev.image_bytes_list):
			raise ValueError("image_bytes_list contains an empty image")
		if not ev.mime_type.startswith("image/"):
			raise ValueError("mime_type must start with 'image/'")
		return ValidatedUploadEvent(image_bytes_list=ev.image_bytes_list, mime_type=ev.mime_type)

	@step
	async def encode_image(self, ev: ValidatedUploadEvent) -> EncodedImageEvent:
		encoded_list = [base64.b64encode(image_bytes).decode("utf-8") for image_bytes in ev.image_bytes_list]
		return EncodedImageEvent(image_base64_list=encoded_list, mime_type=ev.mime_type)

	@step
	async def build_messages(self, ev: EncodedImageEvent) -> MessagesReadyEvent:
		target_schema = InvoiceData.prompt_schema()
		system_prompt = (
			"Tu es un moteur d'extraction de factures. "
			"Retourne uniquement un JSON valide qui respecte strictement le schema fourni. "
			"Ne rajoute aucune cle en dehors du schema. "
				"Pour tous les champs numeriques (quantite, prix_unitaire_ht, taux_tva, montant_ht, remise, total_ht, total_tva, timbre_fiscal, total_ttc), retourne des nombres JSON, pas des chaines de caracteres. "
				"Exemples: 280.000 doit devenir 280, 19 % doit devenir 19, 1,000 doit devenir 1. "
				"Ne mets jamais de guillemets autour des nombres. "
			"Si une valeur est absente, retourne chaine vide. "
			"N'ajoute pas les titres ou sous-titres de section dans lignes (ex: Refacturation a l'identique Frais TT). "
			"Pour la devise, normalise a DT (Dinar Tunisien), EUR (Euro) ou USD (Dollar US). Par exemple: TND->DT, Dinars->DT, Euro->EUR, Dollar->USD."
		)
		user_prompt = (
			"Extrais cette facture en francais selon ce schema exact:\n"
			f"{target_schema}\n"
			"Retourne uniquement le JSON final."
		)
		messages = [
			self._llm_controller.build_system_message(system_prompt),
			{
				"role": "user",
				"content": [
					{"type": "text", "text": user_prompt},
					*[
						{
							"type": "image_url",
							"image_url": {
								"url": f"data:{ev.mime_type};base64,{image_base64}",
								"detail": "low",
							},
						}
						for image_base64 in ev.image_base64_list
					],
				],
			},
		]
		return MessagesReadyEvent(messages=messages)

	@step
	async def extract_invoice_json(self, ev: MessagesReadyEvent) -> StopEvent:
		try:
			invoice_data = self._llm_controller.call_api_for_json(
				ev.messages,
				**self._request_kwargs,
			)
		except Exception:
			target_schema = InvoiceData.prompt_schema()
			# Fallback with shorter prompt to reduce input tokens and response latency.
			fallback_messages = [
				self._llm_controller.build_system_message(
					"Parse facture. Retourne uniquement un JSON valide conforme au schema."
				),
				{
					"role": "user",
					"content": [
						{"type": "text", "text": f"Schema:\n{target_schema}\nRetourne seulement ce JSON."},
						ev.messages[1]["content"][1],
					],
				},
			]
			invoice_data = self._llm_controller.call_api_for_json(
				fallback_messages,
				**self._request_kwargs,
			)
		return StopEvent(result=invoice_data)

	async def run_extraction(
		self,
		image_bytes: bytes | None = None,
		mime_type: str = "image/jpeg",
		image_bytes_list: list[bytes] | None = None,
	) -> InvoiceData:
		payload_image_bytes_list = image_bytes_list if image_bytes_list is not None else ([image_bytes] if image_bytes else [])
		result = await self.run(image_bytes_list=payload_image_bytes_list, mime_type=mime_type)
		if not isinstance(result, InvoiceData):
			raise TypeError("Workflow returned an unexpected result type")
		return result
