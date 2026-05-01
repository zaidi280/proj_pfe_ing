import os
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database


class DBController:
	"""Single responsibility: manage MongoDB connectivity and collections."""

	def __init__(self, mongo_uri: str | None = None, db_name: str | None = None):
		self._mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017")
		self._db_name = db_name or os.getenv("MONGO_DB_NAME", "invoice_pfe")
		self._default_collection = os.getenv("MONGO_COLLECTION", "invoices")
		self._extraction_collection = os.getenv("EXTRACTION_COLLECTION", "invoice_extractions")
		self._chat_default_limit = int(os.getenv("CHAT_RESULT_LIMIT", "50"))
		self._client: MongoClient | None = None
		self._db: Database | None = None

	@property
	def default_collection(self) -> str:
		return self._default_collection

	@property
	def chat_default_limit(self) -> int:
		return self._chat_default_limit

	@property
	def extraction_collection_name(self) -> str:
		return self._extraction_collection

	@property
	def db(self) -> Database:
		if self._db is None:
			self.connect()
		return self._db

	def connect(self) -> None:
		if self._client is not None and self._db is not None:
			return
		self._client = MongoClient(self._mongo_uri, serverSelectionTimeoutMS=5000)
		# Verify connectivity early so failures are explicit at startup/use time.
		self._client.admin.command("ping")
		self._db = self._client[self._db_name]

	def close(self) -> None:
		if self._client is not None:
			self._client.close()
		self._client = None
		self._db = None

	def collection(self, name: str) -> Collection:
		return self.db[name]

	def save_invoice(self, invoice_json: dict[str, Any]) -> str:
		invoices = self.collection("invoices")
		result = invoices.insert_one(invoice_json)
		return str(result.inserted_id)

	def save_extraction(self, invoice_json: dict[str, Any], fichier_json: dict[str, Any], batch_id: str | None = None) -> str:
		extractions = self.collection(self.extraction_collection_name)
		doc = {
			"invoice": invoice_json,
			"fichier": fichier_json,
			"batch_id": batch_id or "",
			"created_at": datetime.now(timezone.utc).isoformat(),
		}
		result = extractions.insert_one(doc)
		return str(result.inserted_id)

	def get_extraction(self, extraction_id: str) -> dict[str, Any] | None:
		try:
			obj_id = ObjectId(extraction_id)
		except (InvalidId, TypeError):
			return None
		extractions = self.collection(self.extraction_collection_name)
		return extractions.find_one({"_id": obj_id})

	def delete_extraction(self, extraction_id: str) -> bool:
		try:
			obj_id = ObjectId(extraction_id)
		except (InvalidId, TypeError):
			return False
		extractions = self.collection(self.extraction_collection_name)
		result = extractions.delete_one({"_id": obj_id})
		return result.deleted_count > 0
