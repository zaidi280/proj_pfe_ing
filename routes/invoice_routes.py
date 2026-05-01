import os
import uuid
import base64
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from bson import ObjectId
import pymupdf as fitz

from controllers.db_controller import DBController
from entities.invoice_data import InvoiceData
from services.auth_service import AuthUser, require_permissions, require_roles
from services.audit_service import compute_changes, log_audit_event
from services.upload_workflow import KimiUploadWorkflow


router = APIRouter(
	prefix="/invoices",
	tags=["Invoices"],
	dependencies=[Depends(require_roles("admin", "comptable"))],
)
_kimi_upload_workflow: KimiUploadWorkflow | None = None
_db_controller: DBController | None = None
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_UPLOADS_DIR = os.path.join(_BASE_DIR, "uploads")


class SaveInvoiceRequest(BaseModel):
	invoice: dict[str, Any] = Field(default_factory=dict)
	extraction_id: str | None = None


def _parse_bool(value: str | None, default: bool = False) -> bool:
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_pdf_upload(file: UploadFile) -> bool:
	filename = (file.filename or "").strip().lower()
	content_type = (file.content_type or "").strip().lower()
	return content_type == "application/pdf" or filename.endswith(".pdf")


def _render_pdf_to_images(pdf_bytes: bytes) -> list[bytes]:
	if not pdf_bytes:
		raise HTTPException(status_code=400, detail="Uploaded PDF is empty")

	try:
		doc = fitz.open(stream=pdf_bytes, filetype="pdf")
	except Exception as exc:
		raise HTTPException(status_code=400, detail=f"Invalid PDF file: {exc}")

	images: list[bytes] = []
	try:
		for page in doc:
			pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
			images.append(pixmap.tobytes("png"))
	finally:
		doc.close()

	if not images:
		raise HTTPException(status_code=400, detail="PDF contains no pages")

	return images


def _build_kimi_workflow() -> KimiUploadWorkflow:
	api_key = os.getenv("KIMI_API_KEY")
	model_name = os.getenv("KIMI_MODEL")
	base_url = os.getenv("KIMI_BASE_URL")
	thinking = _parse_bool(os.getenv("KIMI_THINKING"), default=False)

	if not api_key:
		raise RuntimeError("KIMI_API_KEY is missing in environment")
	if not model_name:
		raise RuntimeError("KIMI_MODEL is missing in environment")

	return KimiUploadWorkflow(
		api_key=api_key,
		model_name=model_name,
		base_url=base_url,
		thinking=thinking,
		timeout=600.0,
	)


def _get_kimi_workflow() -> KimiUploadWorkflow:
	global _kimi_upload_workflow
	if _kimi_upload_workflow is None:
		_kimi_upload_workflow = _build_kimi_workflow()
	return _kimi_upload_workflow


def _get_db_controller() -> DBController:
	global _db_controller
	if _db_controller is None:
		_db_controller = DBController()
	return _db_controller


def _serialize_extraction(doc: dict[str, Any]) -> dict[str, Any]:
	return {
		"extraction_id": str(doc.get("_id")),
		"invoice": doc.get("invoice", {}),
		"fichier": doc.get("fichier", {}),
		"created_at": doc.get("created_at", ""),
	}


def _serialize_saved_invoice(doc: dict[str, Any]) -> dict[str, Any]:
	invoice = doc.get("invoice", {}) if isinstance(doc.get("invoice"), dict) else {}
	vendeur = invoice.get("vendeur", {}) if isinstance(invoice.get("vendeur"), dict) else {}
	client = invoice.get("client", {}) if isinstance(invoice.get("client"), dict) else {}
	facture = invoice.get("facture", {}) if isinstance(invoice.get("facture"), dict) else {}
	totaux = invoice.get("totaux", {}) if isinstance(invoice.get("totaux"), dict) else {}
	paiement = invoice.get("paiement", {}) if isinstance(invoice.get("paiement"), dict) else {}

	return {
		"id": str(doc.get("_id")),
		"numero_facture": facture.get("numero", ""),
		"type_document": facture.get("type", ""),
		"date_facture": facture.get("date", ""),
		"date_echeance": facture.get("date_echeance", ""),
		"vendeur_nom": vendeur.get("nom", ""),
		"vendeur_mf": vendeur.get("matricule_fiscale", ""),
		"client_nom": client.get("nom", ""),
		"client_mf": client.get("matricule_fiscale", ""),
		"total_ht": totaux.get("total_ht"),
		"total_ttc": totaux.get("total_ttc"),
		"devise": totaux.get("devise", ""),
		"mode_paiement": paiement.get("mode_paiement", ""),
		"statut_paiement": paiement.get("statu_paiement", paiement.get("statut_paiement", "")),
		"status": doc.get("status", ""),
		"saved_at": doc.get("saved_at", ""),
		"invoice": invoice,
		"fichier": doc.get("fichier", {}),
		"extraction_id": doc.get("extraction_id", ""),
	}


def _serialize_saved_invoice_detail(doc: dict[str, Any]) -> dict[str, Any]:
	base = _serialize_saved_invoice(doc)
	invoice = doc.get("invoice", {}) if isinstance(doc.get("invoice"), dict) else {}
	vendeur = invoice.get("vendeur", {}) if isinstance(invoice.get("vendeur"), dict) else {}
	client = invoice.get("client", {}) if isinstance(invoice.get("client"), dict) else {}
	facture = invoice.get("facture", {}) if isinstance(invoice.get("facture"), dict) else {}
	totaux = invoice.get("totaux", {}) if isinstance(invoice.get("totaux"), dict) else {}
	paiement = invoice.get("paiement", {}) if isinstance(invoice.get("paiement"), dict) else {}
	fichier = doc.get("fichier", {}) if isinstance(doc.get("fichier"), dict) else {}

	lignes_raw = invoice.get("lignes", []) if isinstance(invoice.get("lignes"), list) else []
	lignes: list[dict[str, Any]] = []
	for row in lignes_raw:
		if not isinstance(row, dict):
			continue
		lignes.append(
			{
				"quantite": row.get("quantite"),
				"unite": row.get("unite", ""),
				"code_article": row.get("code_article", ""),
				"designation": row.get("designation", ""),
				"prix_unitaire_ht": row.get("prix_unitaire_ht"),
				"taux_tva": row.get("taux_tva"),
				"montant_ht": row.get("montant_ht"),
				"remise_pct": row.get("remise", row.get("remise_pct")),
			}
		)

	base.update(
		{
			"source_file": fichier.get("_source_file", ""),
			"image_path": fichier.get("image_path", ""),
			"cree_le": fichier.get("cree_le", doc.get("saved_at", "")),
			"numero_bc": facture.get("numero_bc", ""),
			"vendeur_adresse": vendeur.get("adresse", ""),
			"vendeur_telephone": vendeur.get("telephone", ""),
			"vendeur_email": vendeur.get("email", ""),
			"vendeur_rib": vendeur.get("rib", ""),
			"client_adresse": client.get("adresse", ""),
			"taux_tva": totaux.get("taux_tva"),
			"montant_tva": totaux.get("total_tva"),
			"timbre_fiscal": totaux.get("timbre_fiscal"),
			"montant_en_lettres": paiement.get("montant_en_lettres", ""),
			"conditions_paiement": paiement.get("conditions_paiement", ""),
			"lignes": lignes,
		}
	)
	return base


def _build_invoice_payload_from_flat(payload: dict[str, Any], existing_doc: dict[str, Any]) -> dict[str, Any]:
	existing_invoice = existing_doc.get("invoice", {}) if isinstance(existing_doc.get("invoice"), dict) else {}
	existing_vendeur = existing_invoice.get("vendeur", {}) if isinstance(existing_invoice.get("vendeur"), dict) else {}
	existing_client = existing_invoice.get("client", {}) if isinstance(existing_invoice.get("client"), dict) else {}
	existing_facture = existing_invoice.get("facture", {}) if isinstance(existing_invoice.get("facture"), dict) else {}
	existing_totaux = existing_invoice.get("totaux", {}) if isinstance(existing_invoice.get("totaux"), dict) else {}
	existing_paiement = existing_invoice.get("paiement", {}) if isinstance(existing_invoice.get("paiement"), dict) else {}

	lignes_payload = payload.get("lignes", existing_invoice.get("lignes", []))
	if not isinstance(lignes_payload, list):
		lignes_payload = []

	normalized_lignes: list[dict[str, Any]] = []
	for row in lignes_payload:
		if not isinstance(row, dict):
			continue
		normalized_lignes.append(
			{
				"quantite": row.get("quantite"),
				"unite": row.get("unite", ""),
				"code_article": row.get("code_article", ""),
				"designation": row.get("designation", ""),
				"prix_unitaire_ht": row.get("prix_unitaire_ht"),
				"taux_tva": row.get("taux_tva"),
				"montant_ht": row.get("montant_ht"),
				"remise": row.get("remise", row.get("remise_pct")),
			}
		)

	return {
		"vendeur": {
			"nom": payload.get("vendeur_nom", existing_vendeur.get("nom", "")),
			"adresse": payload.get("vendeur_adresse", existing_vendeur.get("adresse", "")),
			"telephone": payload.get("vendeur_telephone", existing_vendeur.get("telephone", "")),
			"email": payload.get("vendeur_email", existing_vendeur.get("email", "")),
			"matricule_fiscale": payload.get("vendeur_mf", existing_vendeur.get("matricule_fiscale", "")),
			"rib": payload.get("vendeur_rib", existing_vendeur.get("rib", "")),
		},
		"client": {
			"nom": payload.get("client_nom", existing_client.get("nom", "")),
			"adresse": payload.get("client_adresse", existing_client.get("adresse", "")),
			"matricule_fiscale": payload.get("client_mf", existing_client.get("matricule_fiscale", "")),
		},
		"facture": {
			"numero": payload.get("numero_facture", existing_facture.get("numero", "")),
			"date": payload.get("date_facture", existing_facture.get("date", "")),
			"date_echeance": payload.get("date_echeance", existing_facture.get("date_echeance", "")),
			"type": payload.get("type_document", existing_facture.get("type", "")),
			"numero_bc": payload.get("numero_bc", existing_facture.get("numero_bc", "")),
		},
		"lignes": normalized_lignes,
		"totaux": {
			"total_ht": payload.get("total_ht", existing_totaux.get("total_ht")),
			"total_tva": payload.get("montant_tva", existing_totaux.get("total_tva")),
			"taux_tva": payload.get("taux_tva", existing_totaux.get("taux_tva")),
			"timbre_fiscal": payload.get("timbre_fiscal", existing_totaux.get("timbre_fiscal")),
			"total_ttc": payload.get("total_ttc", existing_totaux.get("total_ttc")),
			"devise": payload.get("devise", existing_totaux.get("devise", "DT")),
		},
		"paiement": {
			"montant_en_lettres": payload.get("montant_en_lettres", existing_paiement.get("montant_en_lettres", "")),
			"mode_paiement": payload.get("mode_paiement", existing_paiement.get("mode_paiement", "")),
			"statu_paiement": payload.get(
				"statut_paiement", existing_paiement.get("statu_paiement", existing_paiement.get("statut_paiement", ""))
			),
			"conditions_paiement": payload.get("conditions_paiement", existing_paiement.get("conditions_paiement", "")),
			"date_reglement": payload.get("date_reglement", existing_paiement.get("date_reglement", "")),
		},
		"fichier": {
			"_source_file": payload.get("source_file", ""),
			"image_path": payload.get("image_path", ""),
			"json_brut": "",
			"cree_le": payload.get("cree_le", ""),
		},
	}


async def _extract_and_store(file: UploadFile, batch_id: str | None = None) -> dict[str, Any]:
	is_pdf = _is_pdf_upload(file)
	is_image = bool(file.content_type and file.content_type.startswith("image/"))
	if not is_pdf and not is_image:
		raise HTTPException(status_code=400, detail=f"Only image or PDF uploads are supported: {file.filename}")

	file_bytes = await file.read()
	if not file_bytes:
		raise HTTPException(status_code=400, detail=f"Uploaded file is empty: {file.filename}")

	original_name = (file.filename or "invoice_image").strip()
	if is_pdf:
		image_bytes_list = _render_pdf_to_images(file_bytes)
		mime_type = "image/png"
	else:
		image_bytes_list = [file_bytes]
		mime_type = file.content_type or "image/jpeg"

	invoice_data = await _get_kimi_workflow().run_extraction(
		image_bytes_list=image_bytes_list,
		mime_type=mime_type,
	)
	invoice_data.with_file_metadata(source_file=original_name, image_path="")
	invoice_dict = invoice_data.as_dict()
	invoice_doc = {k: v for k, v in invoice_dict.items() if k != "fichier"}
	fichier_doc = dict(invoice_dict.get("fichier", {}))
	fichier_doc["_temp_image_b64"] = base64.b64encode(image_bytes_list[0]).decode("ascii")
	fichier_doc["_temp_image_mime"] = mime_type
	fichier_doc["_source_mime_type"] = file.content_type or mime_type
	if is_pdf:
		fichier_doc["_temp_page_count"] = len(image_bytes_list)
	extraction_id = _get_db_controller().save_extraction(invoice_doc, fichier_doc, batch_id=batch_id)

	return {
		"extraction_id": extraction_id,
		"filename": file.filename,
		"mime_type": file.content_type,
		"invoice": invoice_doc,
	}


@router.post("/extract/batch")
async def extract_invoices_batch(
	request: Request,
	files: list[UploadFile] = File(...),
	current_user: AuthUser = Depends(require_roles("admin", "comptable")),
):
	if not files:
		raise HTTPException(status_code=400, detail="At least one file is required")

	batch_id = str(uuid.uuid4())
	successes: list[dict[str, Any]] = []
	errors: list[dict[str, Any]] = []

	for file in files:
		try:
			successes.append(await _extract_and_store(file, batch_id=batch_id))
		except HTTPException as exc:
			errors.append({"filename": file.filename, "detail": exc.detail, "status_code": exc.status_code})
		except Exception as exc:
			errors.append({"filename": file.filename, "detail": f"Invoice extraction failed: {exc}", "status_code": 500})

	log_audit_event(
		actor=current_user,
		action="invoice_extract_batch",
		request_method=request.method,
		request_path=request.url.path,
		client_ip=request.client.host if request.client else None,
		entity_type="invoice_extraction_batch",
		entity_id=batch_id,
		summary=f"Extraction de {len(successes)} facture(s), {len(errors)} erreur(s)",
		metadata={
			"batch_id": batch_id,
			"total": len(files),
			"success_count": len(successes),
			"error_count": len(errors),
		},
	)

	return {
		"batch_id": batch_id,
		"total": len(files),
		"success_count": len(successes),
		"error_count": len(errors),
		"items": successes,
		"errors": errors,
	}


@router.get("/extractions")
async def list_extractions(limit: int = 50, batch_id: str | None = None):
	if limit < 1 or limit > 500:
		raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

	try:
		effective_batch_id = (batch_id or "").strip()

		query: dict[str, Any] = {}
		if effective_batch_id:
			query["batch_id"] = effective_batch_id

		docs = list(
			_get_db_controller()
			.collection(_get_db_controller().extraction_collection_name)
			.find(query)
			.sort("created_at", -1)
			.limit(limit)
		)
		return {
			"batch_id": effective_batch_id,
			"count": len(docs),
			"items": [_serialize_extraction(doc) for doc in docs],
		}
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Failed to list extractions: {exc}")


@router.get("/extractions/{extraction_id}")
async def get_extraction(extraction_id: str):
	if not extraction_id or not extraction_id.strip():
		raise HTTPException(status_code=400, detail="extraction_id is required")

	try:
		doc = _get_db_controller().collection(_get_db_controller().extraction_collection_name).find_one(
			{"_id": ObjectId(extraction_id.strip())}
		)
		if doc is None:
			raise HTTPException(status_code=404, detail="extraction_id not found")
		return _serialize_extraction(doc)
	except HTTPException:
		raise
	except Exception:
		raise HTTPException(status_code=400, detail="invalid extraction_id")


@router.delete("/extractions/{extraction_id}")
async def delete_extraction(
	extraction_id: str,
	_: dict[str, Any] = Depends(require_roles("admin", "comptable")),
):
	if not extraction_id or not extraction_id.strip():
		raise HTTPException(status_code=400, detail="extraction_id is required")

	try:
		deleted = _get_db_controller().delete_extraction(extraction_id.strip())
		if not deleted:
			raise HTTPException(status_code=404, detail="extraction_id not found")
		return {"status": "deleted", "extraction_id": extraction_id.strip()}
	except HTTPException:
		raise
	except Exception:
		raise HTTPException(status_code=400, detail="invalid extraction_id")


@router.get("")
async def list_invoices(limit: int = 500):
	if limit < 1 or limit > 5000:
		raise HTTPException(status_code=400, detail="limit must be between 1 and 5000")

	try:
		docs = list(
			_get_db_controller()
			.collection(_get_db_controller().default_collection)
			.find({})
			.sort("saved_at", -1)
			.limit(limit)
		)
		return [_serialize_saved_invoice(doc) for doc in docs]
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Failed to list invoices: {exc}")


@router.get("/{invoice_id}")
async def get_invoice(invoice_id: str):
	if not invoice_id or not invoice_id.strip():
		raise HTTPException(status_code=400, detail="invoice_id is required")

	try:
		obj_id = ObjectId(invoice_id.strip())
		doc = _get_db_controller().collection(_get_db_controller().default_collection).find_one({"_id": obj_id})
		if doc is None:
			raise HTTPException(status_code=404, detail="invoice_id not found")
		return _serialize_saved_invoice_detail(doc)
	except HTTPException:
		raise
	except Exception:
		raise HTTPException(status_code=400, detail="invalid invoice_id")


@router.put("/{invoice_id}")
async def update_invoice(
	invoice_id: str,
	payload: dict[str, Any],
	request: Request,
	current_user: AuthUser = Depends(require_permissions("modify_invoice")),
):
	if not invoice_id or not invoice_id.strip():
		raise HTTPException(status_code=400, detail="invoice_id is required")

	try:
		obj_id = ObjectId(invoice_id.strip())
		coll = _get_db_controller().collection(_get_db_controller().default_collection)
		existing = coll.find_one({"_id": obj_id})
		if existing is None:
			raise HTTPException(status_code=404, detail="invoice_id not found")

		normalized = InvoiceData.from_dict(_build_invoice_payload_from_flat(payload, existing)).as_dict()
		invoice_doc = {k: v for k, v in normalized.items() if k != "fichier"}

		existing_fichier = existing.get("fichier", {}) if isinstance(existing.get("fichier"), dict) else {}
		incoming_fichier = normalized.get("fichier", {}) if isinstance(normalized.get("fichier"), dict) else {}
		fichier_doc = {
			"_source_file": incoming_fichier.get("_source_file") or existing_fichier.get("_source_file", ""),
			"image_path": incoming_fichier.get("image_path") or existing_fichier.get("image_path", ""),
			"json_brut": existing_fichier.get("json_brut", ""),
			"cree_le": existing_fichier.get("cree_le", existing.get("saved_at", "")),
		}

		coll.update_one(
			{"_id": obj_id},
			{
				"$set": {
					"invoice": invoice_doc,
					"fichier": fichier_doc,
					"updated_at": datetime.now(timezone.utc).isoformat(),
				}
			},
		)

		updated = coll.find_one({"_id": obj_id})
		if updated is None:
			raise HTTPException(status_code=500, detail="invoice update failed")

		old_invoice = existing.get("invoice", {}) if isinstance(existing.get("invoice"), dict) else {}
		new_invoice = updated.get("invoice", {}) if isinstance(updated.get("invoice"), dict) else {}
		changes = compute_changes(old_invoice, new_invoice)
		log_audit_event(
			actor=current_user,
			action="invoice_updated",
			request_method=request.method,
			request_path=request.url.path,
			client_ip=request.client.host if request.client else None,
			entity_type="invoice",
			entity_id=str(obj_id),
			summary=f"Facture {str(obj_id)} mise a jour avec {len(changes)} changement(s)",
			changes=changes,
			metadata={
				"invoice_number": new_invoice.get("facture", {}).get("numero", "") if isinstance(new_invoice.get("facture"), dict) else "",
			},
		)
		return _serialize_saved_invoice_detail(updated)
	except HTTPException:
		raise
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Failed to update invoice: {exc}")


@router.get("/{invoice_id}/image")
async def get_invoice_image(invoice_id: str):
	if not invoice_id or not invoice_id.strip():
		raise HTTPException(status_code=400, detail="invoice_id is required")

	try:
		obj_id = ObjectId(invoice_id.strip())
		doc = _get_db_controller().collection(_get_db_controller().default_collection).find_one({"_id": obj_id})
		if doc is None:
			raise HTTPException(status_code=404, detail="invoice_id not found")

		fichier = doc.get("fichier", {}) if isinstance(doc.get("fichier"), dict) else {}
		image_path = str(fichier.get("image_path", "") or "").strip()
		source_file = str(fichier.get("_source_file", "") or "").strip()

		candidate_paths: list[str] = []
		if image_path:
			candidate_paths.append(image_path)
		if source_file:
			candidate_paths.append(os.path.join("uploads", source_file))

		for path in candidate_paths:
			if os.path.isabs(path):
				resolved = path
			else:
				resolved = os.path.join(_BASE_DIR, path)
			if os.path.exists(resolved) and os.path.isfile(resolved):
				return FileResponse(resolved)

		raise HTTPException(status_code=404, detail="invoice image not found")
	except HTTPException:
		raise
	except Exception:
		raise HTTPException(status_code=400, detail="invalid invoice_id")


@router.delete("/{invoice_id}")
async def delete_invoice(
	invoice_id: str,
	request: Request,
	current_user: AuthUser = Depends(require_roles("admin")),
):
	if not invoice_id or not invoice_id.strip():
		raise HTTPException(status_code=400, detail="invoice_id is required")

	try:
		obj_id = ObjectId(invoice_id.strip())
		coll = _get_db_controller().collection(_get_db_controller().default_collection)
		
		# Fetch invoice first to get image path
		doc = coll.find_one({"_id": obj_id})
		if doc is None:
			raise HTTPException(status_code=404, detail="invoice_id not found")
		
		# Delete associated image file from uploads if it exists
		fichier = doc.get("fichier", {}) if isinstance(doc.get("fichier"), dict) else {}
		image_path = str(fichier.get("image_path", "") or "").strip()
		if image_path:
			if os.path.isabs(image_path):
				resolved = image_path
			else:
				resolved = os.path.join(_BASE_DIR, image_path)
			if os.path.exists(resolved) and os.path.isfile(resolved):
				try:
					os.remove(resolved)
				except Exception:
					pass  # Log silently if file deletion fails
		
		# Delete invoice from database
		result = coll.delete_one({"_id": obj_id})
		if result.deleted_count == 0:
			raise HTTPException(status_code=404, detail="invoice_id not found")

		log_audit_event(
			actor=current_user,
			action="invoice_deleted",
			request_method=request.method,
			request_path=request.url.path,
			client_ip=request.client.host if request.client else None,
			entity_type="invoice",
			entity_id=str(obj_id),
			summary=f"Facture {str(obj_id)} supprimee",
			metadata={
				"invoice_number": (
					doc.get("invoice", {}).get("facture", {}).get("numero", "")
					if isinstance(doc.get("invoice"), dict) and isinstance(doc.get("invoice", {}).get("facture"), dict)
					else ""
				),
			},
		)

		return {"status": "deleted", "invoice_id": invoice_id.strip()}
	except HTTPException:
		raise
	except Exception:
		raise HTTPException(status_code=400, detail="invalid invoice_id")


@router.post("/save")
async def save_invoice(
	payload: SaveInvoiceRequest,
	request: Request,
	current_user: AuthUser = Depends(require_permissions("save_invoice")),
):
	invoice_payload = payload.invoice
	if not invoice_payload:
		raise HTTPException(status_code=400, detail="invoice is required")
	if not payload.extraction_id or not payload.extraction_id.strip():
		raise HTTPException(status_code=400, detail="extraction_id is required")

	try:
		extraction_id = payload.extraction_id.strip()
		extraction = _get_db_controller().get_extraction(extraction_id)
		if extraction is None:
			raise HTTPException(status_code=404, detail="extraction_id not found")

		invoice_data = InvoiceData.from_dict(invoice_payload)
		invoice_dict = invoice_data.as_dict()
		invoice_doc = {k: v for k, v in invoice_dict.items() if k != "fichier"}
		fichier_doc = dict(extraction.get("fichier", {}))

		# Persist image only on final save to keep unsaved extractions temporary.
		temp_b64 = str(fichier_doc.get("_temp_image_b64", "") or "").strip()
		temp_mime = str(fichier_doc.get("_temp_image_mime", "") or "").strip().lower()
		source_file = str(fichier_doc.get("_source_file", "") or "invoice_image").strip() or "invoice_image"
		if temp_b64:
			content_ext_map = {
				"image/jpeg": ".jpg",
				"image/jpg": ".jpg",
				"image/png": ".png",
				"image/webp": ".webp",
				"image/gif": ".gif",
				"image/bmp": ".bmp",
			}
			base_name, source_ext = os.path.splitext(source_file)
			ext = source_ext.lower() if source_ext else content_ext_map.get(temp_mime, ".img")
			safe_base = "".join(ch for ch in (base_name or "invoice_image") if ch.isalnum() or ch in ("-", "_"))
			safe_base = safe_base or "invoice_image"
			stored_name = f"{uuid.uuid4().hex}_{safe_base}{ext}"
			os.makedirs(_UPLOADS_DIR, exist_ok=True)
			stored_abs_path = os.path.join(_UPLOADS_DIR, stored_name)
			with open(stored_abs_path, "wb") as fp:
				fp.write(base64.b64decode(temp_b64))
			fichier_doc["image_path"] = os.path.join("uploads", stored_name)

		fichier_doc.pop("_temp_image_b64", None)
		fichier_doc.pop("_temp_image_mime", None)

		doc = {
			"invoice": invoice_doc,
			"fichier": fichier_doc,
			"extraction_id": extraction_id,
			"status": "validated",
			"saved_at": datetime.now(timezone.utc).isoformat(),
		}
		inserted_id = _get_db_controller().save_invoice(doc)
		extraction_deleted = _get_db_controller().delete_extraction(extraction_id)

		log_audit_event(
			actor=current_user,
			action="invoice_saved",
			request_method=request.method,
			request_path=request.url.path,
			client_ip=request.client.host if request.client else None,
			entity_type="invoice",
			entity_id=inserted_id,
			summary=f"Facture {inserted_id} enregistree depuis l'extraction {extraction_id}",
			metadata={
				"extraction_id": extraction_id,
				"invoice_number": invoice_doc.get("facture", {}).get("numero", "") if isinstance(invoice_doc.get("facture"), dict) else "",
			},
		)
	except HTTPException:
		raise
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Failed to save invoice: {exc}")

	return {
		"status": "saved",
		"invoice_id": inserted_id,
		"extraction_deleted": extraction_deleted,
	}
