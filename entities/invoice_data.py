import json
import unicodedata
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any


class InvoiceData:
	def __init__(self, json_data: dict[str, Any], raw_text: str | None = None):
		self.json = json_data
		self.raw_text = raw_text

	@staticmethod
	def _strip_code_fences(text: str) -> str:
		return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

	@staticmethod
	def _empty_schema() -> dict[str, Any]:
		return {
			"vendeur": {
				"nom": "",
				"adresse": "",
				"telephone": "",
				"email": "",
				"matricule_fiscale": "",
			},
			"client": {
				"nom": "",
				"adresse": "",
				"matricule_fiscale": "",
			},
			"facture": {
				"numero": "",
				"date": "",
				"date_echeance": "",
				"type": "",
			},
			"lignes": [],
			"totaux": {
				"total_ht": None,
				"total_tva": None,
				"timbre_fiscal": None,
				"total_ttc": None,
				"devise": "",
			},
			"paiement": {
				"montant_en_lettres": "",
				"mode_paiement": "",
				"statu_paiement": "",
				"conditions_paiement": "",
				"date_reglement": "",
			},
			"fichier": {
				"_source_file": "",
				"image_path": "",
				"json_brut": "",
				"cree_le": "",
			},
		}

	@staticmethod
	def prompt_schema() -> str:
		schema = InvoiceData._empty_schema()
		schema["totaux"] = {
			"total_ht": 0.0,
			"total_tva": 0.0,
			"timbre_fiscal": 0.0,
			"total_ttc": 0.0,
			"devise": "",
		}
		schema["lignes"] = [
			{
				"quantite": 0.0,
				"unite": "",
				"code_article": "",
				"designation": "",
				"prix_unitaire_ht": 0.0,
				"taux_tva": 0.0,
				"montant_ht": 0.0,
				"remise": 0.0,
			}
		]
		return json.dumps(schema, ensure_ascii=False, indent=2)

	@staticmethod
	def _to_dict(value: Any) -> dict[str, Any]:
		return value if isinstance(value, dict) else {}

	@staticmethod
	def _to_list(value: Any) -> list[Any]:
		return value if isinstance(value, list) else []

	@staticmethod
	def _pick(data: dict[str, Any], keys: list[str], default: Any = None) -> Any:
		for key in keys:
			if key in data and data[key] is not None:
				return data[key]
		return default

	@staticmethod
	def _as_string(value: Any) -> str:
		if value is None:
			return ""
		if isinstance(value, str):
			return value.strip()
		return str(value).strip()

	@staticmethod
	def _to_numeric(value: Any) -> float | None:
		if value is None:
			return None
		if isinstance(value, str):
			value = value.strip()
		elif isinstance(value, Decimal):
			value = str(value)
		else:
			value = str(value)
		try:
			clean = value.strip().rstrip("%").replace(" ", "").replace("\u00A0", "").replace(",", ".")
			if clean.count(".") > 1:
				head, tail = clean.rsplit(".", 1)
				clean = f"{head.replace('.', '')}.{tail}"
			return float(Decimal(clean))
		except (InvalidOperation, ValueError, TypeError, AttributeError):
			return None

	@staticmethod
	def _normalize_text(text: str) -> str:
		"""Normalize text by removing accents and diacritics."""
		if not text:
			return ""
		normalized = unicodedata.normalize("NFD", text)
		return "".join(c for c in normalized if unicodedata.category(c) != "Mn")

	@staticmethod
	def _to_rate_numeric(value: str | None) -> float | None:
		"""Normalize TVA rate as numeric."""
		return InvoiceData._to_numeric(value)

	@staticmethod
	def _normalize_devise(value: str | None) -> str:
		"""Normalize currency code from various formats to standard codes."""
		if not value:
			return "DT"
		norm = InvoiceData._normalize_text(value).lower().strip()
		if norm in ("dt", "dinar", "dinars", "dinar tunisien", "dinar tunisiens", "tnd"):
			return "DT"
		if norm in ("eur", "euro", "euros"):
			return "EUR"
		if norm in ("usd", "dollar", "dollars", "us dollar", "us dollars"):
			return "USD"
		return "DT"

	@classmethod
	def _is_title_line(cls, designation: str) -> bool:
		norm = cls._normalize_text(designation)
		if not norm:
			return True
		title_prefixes = [
			"refacturation a l'identique",
			"observations",
			
		]
		return any(norm.startswith(prefix) for prefix in title_prefixes)

	@classmethod
	def parse_json_object(cls, text: str) -> dict[str, Any]:
		cleaned = cls._strip_code_fences(text)
		try:
			obj = json.loads(cleaned, parse_float=Decimal, parse_int=Decimal)
			if isinstance(obj, dict):
				return obj
		except json.JSONDecodeError:
			pass

		start = cleaned.find("{")
		end = cleaned.rfind("}")
		if start != -1 and end != -1 and end > start:
			candidate = cleaned[start:end + 1]
			obj = json.loads(candidate, parse_float=Decimal, parse_int=Decimal)
			if isinstance(obj, dict):
				return obj

		raise ValueError("LLM did not return valid JSON object")

	@classmethod
	def normalize(cls, raw_json: dict[str, Any]) -> dict[str, Any]:
		normalized = cls._empty_schema()

		vendeur_raw = cls._to_dict(cls._pick(raw_json, ["vendeur", "fournisseur", "seller", "vendor"], {}))
		client_value = cls._pick(raw_json, ["client", "buyer", "customer"], {})
		client_raw = cls._to_dict(client_value)
		facture_raw = cls._to_dict(cls._pick(raw_json, ["facture", "invoice"], {}))
		totaux_raw = cls._to_dict(cls._pick(raw_json, ["totaux", "totals"], {}))
		paiement_raw = cls._to_dict(cls._pick(raw_json, ["paiement", "payment"], {}))

		normalized["vendeur"]["nom"] = cls._as_string(
			cls._pick(vendeur_raw, ["nom", "raison_sociale", "name"], cls._pick(raw_json, ["fournisseur", "vendeur"], ""))
		)
		normalized["vendeur"]["adresse"] = cls._as_string(
			cls._pick(vendeur_raw, ["adresse", "address"], cls._pick(raw_json, ["adresse_fournisseur"], ""))
		)
		normalized["vendeur"]["telephone"] = cls._as_string(cls._pick(vendeur_raw, ["telephone", "tel", "phone"], ""))
		normalized["vendeur"]["email"] = cls._as_string(cls._pick(vendeur_raw, ["email", "mail"], ""))
		normalized["vendeur"]["matricule_fiscale"] = cls._as_string(
			cls._pick(vendeur_raw, ["matricule_fiscale", "nif", "ice", "rc", "tax_id"], "")
		)

		client_name = client_value if isinstance(client_value, str) else cls._pick(client_raw, ["nom", "raison_sociale", "name"], "")
		normalized["client"]["nom"] = cls._as_string(client_name)
		normalized["client"]["adresse"] = cls._as_string(
			cls._pick(client_raw, ["adresse", "address"], cls._pick(raw_json, ["adresse_client", "adresse"], ""))
		)
		normalized["client"]["matricule_fiscale"] = cls._as_string(
			cls._pick(client_raw, ["matricule_fiscale", "nif", "ice", "rc", "tax_id", "code_client"], cls._pick(raw_json, ["code_client"], ""))
		)

		normalized["facture"]["numero"] = cls._as_string(
			cls._pick(facture_raw, ["numero", "numero_facture", "facture_numero", "reference", "invoice_number"], cls._pick(raw_json, ["numero_facture", "facture_numero", "numero", "reference"], ""))
		)
		normalized["facture"]["date"] = cls._as_string(
			cls._pick(facture_raw, ["date", "date_facture", "date_creation", "invoice_date"], cls._pick(raw_json, ["date_facture", "date_creation", "date"], ""))
		)
		normalized["facture"]["date_echeance"] = cls._as_string(
			cls._pick(facture_raw, ["date_echeance", "due_date"], cls._pick(raw_json, ["date_echeance"], ""))
		)
		normalized["facture"]["type"] = cls._as_string(
			cls._pick(facture_raw, ["type", "invoice_type"], cls._pick(raw_json, ["type"], ""))
		)

		lignes_raw = cls._to_list(cls._pick(raw_json, ["lignes", "lines", "items", "produits", "prestations"], []))
		normalized_lignes: list[dict[str, Any]] = []
		for row in lignes_raw:
			if not isinstance(row, dict):
				continue
			line = {
				"quantite": cls._to_numeric(cls._pick(row, ["quantite", "qte", "quantity"], None)),
				"unite": cls._as_string(cls._pick(row, ["unite", "unit"], "")),
				"code_article": cls._as_string(cls._pick(row, ["code_article", "sku", "code"], "")),
				"designation": cls._as_string(cls._pick(row, ["designation", "description", "libelle"], "")),
				"prix_unitaire_ht": cls._to_numeric(cls._pick(row, ["prix_unitaire_ht", "prix_unitaire", "pu", "unit_price"], None)),
				"taux_tva": cls._to_rate_numeric(cls._pick(row, ["taux_tva", "tva_pourcentage", "tax_rate"], None)),
				"montant_ht": cls._to_numeric(cls._pick(row, ["montant_ht", "montant", "total", "line_total"], None)),
				"remise": cls._to_numeric(cls._pick(row, ["remise", "discount"], None)),
			}
			if cls._is_title_line(line["designation"]):
				continue
			normalized_lignes.append(line)
		normalized["lignes"] = normalized_lignes

		normalized["totaux"]["total_ht"] = cls._to_numeric(cls._pick(
			totaux_raw, ["total_ht", "montant_ht", "sous_total"], cls._pick(raw_json, ["total_ht", "montant_ht"], None)
		))
		normalized["totaux"]["total_tva"] = cls._to_numeric(cls._pick(
			totaux_raw, ["total_tva", "montant_tva", "tva"], cls._pick(raw_json, ["total_tva", "montant_tva", "tva"], None)
		))
		
		normalized["totaux"]["timbre_fiscal"] = cls._to_numeric(cls._pick(
			totaux_raw, ["timbre_fiscal"], cls._pick(raw_json, ["timbre_fiscal"], None)
		))
		normalized["totaux"]["total_ttc"] = cls._to_numeric(cls._pick(
			totaux_raw, ["total_ttc", "montant_ttc", "total"], cls._pick(raw_json, ["total_ttc", "montant_ttc", "total"], None)
		))
		devise_raw = cls._as_string(
			cls._pick(totaux_raw, ["devise", "currency"], cls._pick(raw_json, ["devise", "currency"], ""))
		)
		normalized["totaux"]["devise"] = cls._normalize_devise(devise_raw)

		normalized["paiement"]["montant_en_lettres"] = cls._as_string(
			cls._pick(paiement_raw, ["montant_en_lettres", "amount_in_words"], cls._pick(raw_json, ["montant_en_lettres"], ""))
		)
		normalized["paiement"]["mode_paiement"] = cls._as_string(
			cls._pick(paiement_raw, ["mode_paiement", "mode_reglement", "payment_method"], cls._pick(raw_json, ["mode_paiement", "mode_reglement"], ""))
		)
		normalized["paiement"]["statu_paiement"] = cls._as_string(
			cls._pick(paiement_raw, ["statu_paiement", "statut_paiement", "payment_status"], cls._pick(raw_json, ["statu_paiement", "statut_paiement"], ""))
		)
		normalized["paiement"]["conditions_paiement"] = cls._as_string(
			cls._pick(paiement_raw, ["conditions_paiement", "payment_terms"], cls._pick(raw_json, ["conditions_paiement"], ""))
		)
		normalized["paiement"]["date_reglement"] = cls._as_string(
			cls._pick(paiement_raw, ["date_reglement", "payment_date"], cls._pick(raw_json, ["date_reglement"], ""))
		)

		fichier_raw = cls._to_dict(cls._pick(raw_json, ["fichier", "file"], {}))
		normalized["fichier"]["_source_file"] = cls._as_string(cls._pick(fichier_raw, ["_source_file", "source_file"], ""))
		normalized["fichier"]["image_path"] = cls._as_string(cls._pick(fichier_raw, ["image_path"], ""))
		normalized["fichier"]["json_brut"] = cls._as_string(cls._pick(fichier_raw, ["json_brut"], ""))
		normalized["fichier"]["cree_le"] = cls._as_string(cls._pick(fichier_raw, ["cree_le", "created_at"], ""))

		return normalized

	@classmethod
	def from_raw_text(cls, raw: str) -> "InvoiceData":
		if not isinstance(raw, str) or not raw.strip():
			raise ValueError("LLM returned empty content")
		try:
			raw_json = cls.parse_json_object(raw)
		except Exception as e:
			raise ValueError(f"LLM did not return valid JSON: {e}\\nRaw response: {raw}")
		return cls(cls.normalize(raw_json), raw_text=raw)

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "InvoiceData":
		return cls(cls.normalize(data), raw_text=None)

	def with_file_metadata(self, source_file: str | None = None, image_path: str | None = None) -> "InvoiceData":
		if source_file:
			self.json["fichier"]["_source_file"] = source_file
		if image_path:
			self.json["fichier"]["image_path"] = image_path
		if self.raw_text:
			self.json["fichier"]["json_brut"] = self.raw_text
		if not self.json["fichier"].get("cree_le"):
			self.json["fichier"]["cree_le"] = datetime.now(timezone.utc).isoformat()
		return self

	def as_dict(self) -> dict[str, Any]:
		return self.json
