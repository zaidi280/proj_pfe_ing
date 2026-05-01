import json
import os
import time
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import requests

# ================= CONFIGURATION =================
BASE_URL = os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8082")
LOGIN_USERNAME = os.getenv("EVAL_USERNAME", "admin")
LOGIN_PASSWORD = os.getenv("EVAL_PASSWORD", "admin123")

REQUEST_DELAY_FAST = float(os.getenv("EVAL_REQUEST_DELAY_FAST", "0.2"))
REQUEST_DELAY_SLOW = float(os.getenv("EVAL_REQUEST_DELAY_SLOW", "1.5"))
MAX_RETRIES = int(os.getenv("EVAL_MAX_RETRIES", "2"))
RETRY_BASE_DELAY_SECONDS = float(os.getenv("EVAL_RETRY_BASE_DELAY_SECONDS", "1.5"))
CHECKPOINT_INTERVAL = int(os.getenv("EVAL_CHECKPOINT_INTERVAL", "5"))
MAX_CASES_PER_RUN = int(os.getenv("EVAL_MAX_CASES_PER_RUN", "10"))

CHECKPOINT_DIR = Path(os.getenv("EVAL_CHECKPOINT_DIR", "evaluation/checkpoints"))
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_FILE = CHECKPOINT_DIR / "chat_eval_checkpoint.json"

# ================= DATA CLASSES =================
@dataclass(frozen=True)
class TestCase:
    name: str
    prompt: str
    session_id: str
    setup_prompt: Optional[str] = None
    expected_count: Optional[int] = None
    expected_markers: tuple[str, ...] = ()
    allow_clarification: bool = False
    expect_error: bool = False
    expected_status: Optional[int] = None

# ================= HELPER FUNCTIONS =================
class RateLimitError(RuntimeError):
    pass

def _is_rate_limit_response(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    try:
        payload = response.json()
        return "rate limit" in str(payload.get("detail", "")).lower()
    except Exception:
        return False

def load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            broken = CHECKPOINT_FILE.with_suffix(".broken.json")
            CHECKPOINT_FILE.replace(broken)
    return {
        "completed_indices": [],
        "rows": [],
        "measured_times": [],
        "passes": 0,
        "hard_failures": 0,
        "total_attempts": 0,
        "total_rate_limit_hits": 0,
        "start_time": time.time(),
        "case_times": {},  # historical per-case times
    }

# ================= TEST CASES =================
TEST_CASES: list[TestCase] = [
    # Original 70 test cases, fixed for clarification
    # === ROBUSTESSE CASSE (CASE INSENSITIVITY) ===
    TestCase(
        name="case lowercase vendor",
        prompt="factures du vendeur topnet",
        session_id="case-1",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
    TestCase(
        name="case mixedcase vendor",
        prompt="factures de TopNet",
        session_id="case-2",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
    TestCase(
        name="case lowercase client",
        prompt="factures du client clinique les jasmins",
        session_id="case-3",
        expected_count=1,
        expected_markers=("FA24-00000213", "Digital Medical"),
    ),
    TestCase(
        name="case mixed client variant",
        prompt="factures du client Clinique Les Jasmins",
        session_id="case-4",
        expected_count=1,
        expected_markers=("FA24-00000213",),
    ),
    TestCase(
        name="insufficient info bare",
        prompt="la facture",
        session_id="insufficient-1",
        expected_count=None,
        allow_clarification=True,
    ),
    TestCase(
        name="insufficient info client",
        prompt="le client",
        session_id="insufficient-3",
        expected_count=None,
        allow_clarification=True,
    ),
    TestCase(
        name="insufficient info with context",
        prompt="celle de topnet",
        session_id="insufficient-2",
        setup_prompt="factures de TOPNET",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
    # === QUESTIONS NATURELLES UTILISATEUR ===
    TestCase(
    name="all invoices natural",
    prompt="montre moi toutes les factures",
    session_id="all-2",
    expected_count=4,
),
    TestCase(
        name="natural question vendor 1",
        prompt="tu connais la facture de topnet ?",
        session_id="natural-1",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
    TestCase(
        name="natural question amount",
        prompt="celle de proactis elle vaut combien ?",
        session_id="natural-2",
        setup_prompt="factures du vendeur ProActis Consulting",
        expected_count=1,
        expected_markers=("ProActis", "786.4"),
    ),
    TestCase(
        name="natural question context usage",
        prompt="montant de celle d'avant",
        session_id="natural-3",
        setup_prompt="facture 2017104306",
        expected_count=1,
        expected_markers=("2017104306", "31.984"),
    ),
    # === NOUVELLES VARIATIONS LINGUISTIQUES & TYPOS ===
    TestCase(
        name="typo facture 1 - missing e",
        prompt="factur FAC-250001",
        session_id="typo-1",
        expected_count=1,
        expected_markers=("FAC-250001", "ProActis"),
    ),
    TestCase(
        name="typo facture 2 - swap letters",
        prompt="facutre A/171769",
        session_id="typo-2",
        expected_count=1,
        expected_markers=("A/171769",),
    ),
    TestCase(
        name="typo vendeur - misspell",
        prompt="factures du venduer TOPNET",
        session_id="typo-3",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
     # === AMBIGUÏTÉS & DÉSAMBIGUÏSATION ===
  
    TestCase(
        name="ambiguity client name variant 2",
        prompt="factures du client Univers Logiciel UNILOG",
        session_id="ambig-2",
        expected_count=1,
        expected_markers=("Univers Logiciel UNILOG", "ProActis"),
    ),
    TestCase(
        name="ambiguous short reference",
        prompt="factures du client unilog",
        session_id="ambig-3",
        expected_count=2,
        expected_markers=("UNILOG",),
    ),
  
    # Partial invoice / fuzzy match
    TestCase(
        name="partial invoice number",
        prompt="facture FAC-25",
        session_id="fuzzy-1",
        expected_count=1,
        expected_markers=("FAC-250001",),
    ),
    # Follow-up multi-turn example
    TestCase(
        name="follow-up multi-turn",
        prompt="quel est le montant de celle du client TOPNET ?",
        session_id="followup-long-1",
        setup_prompt="factures du client TOPNET",
        expected_count=1,
        expected_markers=("2017104306", "31.984"),
    ),
    # Typos handled with context
    TestCase(
        name="typo with context",
        prompt="factur du venduer topnet",
        session_id="typo-context-1",
        setup_prompt="factures du client boussmina bodhra",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
    # === SALUTATIONS & CONVERSATIONNELS ===
    TestCase(
        name="greeting hello",
        prompt="bonjour",
        session_id="greeting-1",
        expected_count=1,
    ),
    TestCase(
        name="greeting thank you",
        prompt="merci",
        session_id="greeting-2",
        expected_count=1,
    ),
    TestCase(
        name="greeting how are you",
        prompt="comment ça va ?",
        session_id="greeting-3",
        expected_count=1,
    ),
    # === PROMPT INJECTION / MALICIOUS CONTENT ===
    TestCase(
    name="injection attempt 1",
    prompt="facture FAC-250001; DROP TABLE invoices; --",
    session_id="injection-1",
    expect_error=True,
    expected_status=422,
    ),
     TestCase(
        name="injection attempt 2",
        prompt="factures\"><script>alert('xss')</script>",
        session_id="injection-2",
        expect_error=True,
        expected_status=422,
    ),
     # === ULTRA-LONG PROMPT (500+ chars) ===
    TestCase(
        name="prompt too long",
        prompt="factures du vendeur " + "X" * 500,
        session_id="toolong-1",
        expect_error=True,
        expected_status=422,
    ),

    # === CONTEXTUAL FOLLOW-UP WITH AMBIGUITY ===
    TestCase(
        name="follow-up disambiguation needed",
        prompt="et ses autres factures ?",
        session_id="followup-7",
        setup_prompt="factures de l'année",
        expected_count=None,
        allow_clarification=True,
    ),
    # Cas additionnels pour atteindre 50 tests
    TestCase(
        name="filtre vendeur et client proactis",
        prompt="factures du vendeur ProActis Consulting pour le client Univers Logiciel UNILOG",
        session_id="single-33",
        expected_count=1,
        expected_markers=("ProActis Consulting", "Univers Logiciel UNILOG"),
    ),
    TestCase(
        name="filtre vendeur et client maalej",
        prompt="factures du vendeur MAALEJ AUDIO pour le client STE UNILOG",
        session_id="single-34",
        expected_count=1,
        expected_markers=("MAALEJ AUDIO", "STE UNILOG"),
    ),
    TestCase(
        name="filtre vendeur et client digital",
        prompt="factures du vendeur Digital Medical Systems pour le client clinique les jasmins",
        session_id="single-35",
        expected_count=1,
        expected_markers=("Digital Medical Systems", "clinique les jasmins"),
    ),
    TestCase(
        name="filtre vendeur et client topnet",
        prompt="factures du vendeur TOPNET pour le client boussmina bodhra",
        session_id="single-36",
        expected_count=1,
        expected_markers=("TOPNET", "boussmina bodhra"),
    ),
    TestCase(
        name="question vendeur topnet",
        prompt="montre moi les factures du vendeur topnet stp",
        session_id="single-37",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
    TestCase(
        name="question vendeur proactis",
        prompt="peux-tu afficher les factures de ProActis Consulting ?",
        session_id="single-38",
        expected_count=1,
        expected_markers=("ProActis Consulting", "FAC-250001"),
    ),
    TestCase(
        name="question client jasmins",
        prompt="je veux les factures du client clinique les jasmins",
        session_id="single-39",
        expected_count=1,
        expected_markers=("clinique les jasmins", "FA24-00000213"),
    ),
    TestCase(
        name="question client boussmina",
        prompt="je veux les factures du client boussmina bodhra",
        session_id="single-40",
        expected_count=1,
        expected_markers=("boussmina bodhra", "2017104306"),
    ),
    TestCase(
        name="negatif combinaison inconnue 1",
        prompt="factures du vendeur TOPNET pour le client Univers Logiciel UNILOG",
        session_id="single-41",
        expected_count=0,
    ),
    TestCase(
        name="negatif combinaison inconnue 2",
        prompt="factures du vendeur ProActis Consulting pour le client clinique les jasmins",
        session_id="single-42",
        expected_count=0,
    ),
    TestCase(
        name="negatif combinaison inconnue 3",
        prompt="factures du vendeur MAALEJ AUDIO pour le client boussmina bodhra",
        session_id="single-43",
        expected_count=0,
    ),
    TestCase(
        name="negatif numero inconnu 3",
        prompt="facture NOPE-2026-999",
        session_id="single-44",
        expected_count=0,
    ),
    TestCase(
        name="suivi topnet montant",
        prompt="et son montant ?",
        session_id="follow-up-5",
        setup_prompt="factures de TOPNET",
        expected_count=1,
        expected_markers=("TOPNET", "31.984"),
    ),
    TestCase(
        name="suivi proactis montant",
        prompt="et son montant ?",
        session_id="follow-up-6",
        setup_prompt="factures du vendeur ProActis Consulting",
        expected_count=1,
        expected_markers=("ProActis Consulting", "786.4"),
    ),
    # 2017104306 / TOPNET / boussmina bodhra
    TestCase(
        name="topnet numero direct",
        prompt="facture 2017104306",
        session_id="single-22",
        expected_count=1,
        expected_markers=("2017104306", "TOPNET"),
    ),
    TestCase(
        name="topnet numero reformulation",
        prompt="cherche la facture numero 2017104306",
        session_id="single-23",
        expected_count=1,
        expected_markers=("2017104306", "boussmina bodhra"),
    ),
    TestCase(
        name="topnet client",
        prompt="qui est le client de 2017104306 ?",
        session_id="single-24",
        expected_count=1,
        expected_markers=("2017104306", "boussmina bodhra"),
    ),
    TestCase(
        name="topnet vendeur",
        prompt="quel est le vendeur de la facture 2017104306 ?",
        session_id="single-25",
        expected_count=1,
        expected_markers=("2017104306", "TOPNET"),
    ),
    TestCase(
        name="topnet montant",
        prompt="combien vaut la facture 2017104306 ?",
        session_id="single-26",
        expected_count=1,
        expected_markers=("2017104306", "31.984"),
    ),
    TestCase(
        name="vendeur topnet",
        prompt="factures de TOPNET",
        session_id="single-27",
        expected_count=1,
        expected_markers=("TOPNET", "2017104306"),
    ),
    TestCase(
        name="client boussmina",
        prompt="factures du client boussmina bodhra",
        session_id="single-28",
        expected_count=1,
        expected_markers=("boussmina bodhra", "2017104306"),
    ),
    # Cas negatifs
    TestCase(
        name="negatif numero inconnu 1",
        prompt="facture ZZZ-000000",
        session_id="single-29",
        expected_count=0,
    ),
    TestCase(
        name="negatif numero inconnu 2",
        prompt="facture INV-404-NOTFOUND",
        session_id="single-30",
        expected_count=0,
    ),
    TestCase(
        name="negatif vendeur inconnu",
        prompt="factures du vendeur Mega Corp Inexistante",
        session_id="single-31",
        expected_count=0,
    ),
    TestCase(
        name="negatif client inconnu",
        prompt="factures du client Client Fantome",
        session_id="single-32",
        expected_count=0,
    ),
    # Suivi conversationnel
    TestCase(
        name="suivi topnet client",
        prompt="et son client ?",
        session_id="follow-up-1",
        setup_prompt="factures de TOPNET",
        expected_count=1,
        expected_markers=("TOPNET", "boussmina bodhra"),
    ),
    TestCase(
        name="suivi proactis client",
        prompt="et son client ?",
        session_id="follow-up-2",
        setup_prompt="factures du vendeur ProActis Consulting",
        expected_count=1,
        expected_markers=("ProActis Consulting", "Univers Logiciel UNILOG"),
    ),
    TestCase(
        name="suivi maalej client",
        prompt="et son client ?",
        session_id="follow-up-3",
        setup_prompt="factures du vendeur MAALEJ AUDIO",
        expected_count=1,
        expected_markers=("MAALEJ AUDIO", "STE UNILOG"),
    ),
    TestCase(
        name="suivi digital client",
        prompt="et son client ?",
        session_id="follow-up-4",
        setup_prompt="factures du vendeur Digital Medical Systems",
        expected_count=1,
        expected_markers=("Digital Medical Systems", "clinique les jasmins"),
    ),
    # FAC-250001 / ProActis / Univers Logiciel UNILOG
    TestCase(
        name="fac250001 numero direct",
        prompt="facture FAC-250001",
        session_id="single-1",
        expected_count=1,
        expected_markers=("FAC-250001", "ProActis Consulting"),
    ),
    TestCase(
        name="fac250001 numero reformulation",
        prompt="je cherche la facture numero FAC-250001",
        session_id="single-2",
        expected_count=1,
        expected_markers=("FAC-250001", "Univers Logiciel UNILOG"),
    ),
    TestCase(
        name="fac250001 client",
        prompt="quel est le client de la facture FAC-250001 ?",
        session_id="single-3",
        expected_count=1,
        expected_markers=("FAC-250001", "Univers Logiciel UNILOG"),
    ),
    TestCase(
        name="fac250001 vendeur",
        prompt="qui est le vendeur de la facture FAC-250001 ?",
        session_id="single-4",
        expected_count=1,
        expected_markers=("FAC-250001", "ProActis Consulting"),
    ),
    TestCase(
        name="fac250001 montant",
        prompt="montant total ttc de la facture FAC-250001",
        session_id="single-5",
        expected_count=1,
        expected_markers=("FAC-250001", "786.4"),
    ),
    TestCase(
        name="vendeur proactis",
        prompt="factures du vendeur ProActis Consulting",
        session_id="single-6",
        expected_count=1,
        expected_markers=("ProActis Consulting", "FAC-250001"),
    ),
    TestCase(
        name="client univers logiciel",
        prompt="factures du client Univers Logiciel UNILOG",
        session_id="single-7",
        expected_count=1,
        expected_markers=("Univers Logiciel UNILOG", "FAC-250001"),
    ),
    # A/171769 / MAALEJ AUDIO / STE UNILOG
    TestCase(
        name="a171769 numero direct",
        prompt="facture A/171769",
        session_id="single-8",
        expected_count=1,
        expected_markers=("A/171769", "MAALEJ AUDIO"),
    ),
    TestCase(
        name="a171769 numero reformulation",
        prompt="peux-tu retrouver la facture numero A/171769 ?",
        session_id="single-9",
        expected_count=1,
        expected_markers=("A/171769", "STE UNILOG"),
    ),
    TestCase(
        name="a171769 client",
        prompt="c est qui le client de A/171769 ?",
        session_id="single-10",
        expected_count=1,
        expected_markers=("A/171769", "STE UNILOG"),
    ),
    TestCase(
        name="a171769 vendeur",
        prompt="donne le vendeur de la facture A/171769",
        session_id="single-11",
        expected_count=1,
        expected_markers=("A/171769", "MAALEJ AUDIO"),
    ),
    TestCase(
        name="a171769 montant",
        prompt="combien est le total ttc de A/171769 ?",
        session_id="single-12",
        expected_count=1,
        expected_markers=("A/171769", "66.0"),
    ),
    TestCase(
        name="vendeur maalej audio",
        prompt="factures du vendeur MAALEJ AUDIO",
        session_id="single-13",
        expected_count=1,
        expected_markers=("MAALEJ AUDIO", "A/171769"),
    ),
    TestCase(
        name="client ste unilog",
        prompt="factures du client STE UNILOG",
        session_id="single-14",
        expected_count=1,
        expected_markers=("STE UNILOG", "A/171769"),
    ),
    # FA24-00000213 / Digital Medical Systems / clinique les jasmins
    TestCase(
        name="fa24 numero direct",
        prompt="facture FA24-00000213",
        session_id="single-15",
        expected_count=1,
        expected_markers=("FA24-00000213", "Digital Medical Systems"),
    ),
    TestCase(
        name="fa24 numero reformulation",
        prompt="je veux les infos de la facture numero FA24-00000213",
        session_id="single-16",
        expected_count=1,
        expected_markers=("FA24-00000213", "clinique les jasmins"),
    ),
    TestCase(
        name="fa24 client",
        prompt="qui est le client de la facture FA24-00000213 ?",
        session_id="single-17",
        expected_count=1,
        expected_markers=("FA24-00000213", "clinique les jasmins"),
    ),
    TestCase(
        name="fa24 vendeur",
        prompt="donne le vendeur de la facture FA24-00000213",
        session_id="single-18",
        expected_count=1,
        expected_markers=("FA24-00000213", "Digital Medical Systems"),
    ),
    TestCase(
        name="fa24 montant",
        prompt="montant ttc de la facture FA24-00000213",
        session_id="single-19",
        expected_count=1,
        expected_markers=("FA24-00000213", "5115.6"),
    ),
    TestCase(
        name="vendeur digital medical",
        prompt="factures du vendeur Digital Medical Systems",
        session_id="single-20",
        expected_count=1,
        expected_markers=("Digital Medical Systems", "FA24-00000213"),
    ),
    TestCase(
        name="client clinique jasmins",
        prompt="factures du client clinique les jasmins",
        session_id="single-21",
        expected_count=1,
        expected_markers=("clinique les jasmins", "FA24-00000213"),
    ),
    # Numeric reasoning tests
    TestCase(
    name="amount comparison",
    prompt="quelle facture est la plus chère ?",
    session_id="reasoning-1",
    expected_count=1,
),
   # Multilingual tests
   TestCase(
    name="mixed language",
    prompt="show me facture FAC-250001",
    session_id="lang-1",
    expected_count=1,
),
TestCase(
    name="english follow up",
    prompt="what is its amount?",
    session_id="english-2",
    setup_prompt="show me invoice FAC-250001",
    expected_count=1,
    expected_markers=("FAC-250001", "786.4"),
),
TestCase(
    name="arabic invoice lookup",
    prompt="اعرض الفاتورة FAC-250001",
    session_id="arabic-1",
    expected_count=1,
    expected_markers=("FAC-250001", "ProActis Consulting"),
),
TestCase(
    name="arabic vendor query",
    prompt="ما هي فواتير TOPNET ؟",
    session_id="arabic-2",
    expected_count=1,
    expected_markers=("TOPNET", "2017104306"),
),
TestCase(
    name="arabic follow up",
    prompt="وكم المبلغ ؟",
    session_id="arabic-3",
    setup_prompt="فواتير TOPNET",
    expected_count=1,
    expected_markers=("TOPNET", "31.984"),
),
  # Out-of-domain test
  TestCase(
    name="out of domain",
    prompt="quel temps fait-il aujourd'hui ?",
    session_id="ood-1",
    expected_count=None,
    allow_clarification=True,
),
TestCase(
    name="all invoices",
    prompt="donner toutes les factures",
    session_id="all-1",
    expected_count=4,
    expected_markers=(
        "FAC-250001",
        "2017104306",
        "A/171769",
        "FA24-00000213",
    ),
),
    

]

# ================= HELPER FUNCTIONS =================
class RateLimitError(RuntimeError):
    pass

def _is_rate_limit_response(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    try:
        payload = response.json()
        return "rate limit" in str(payload.get("detail","")).lower()
    except Exception:
        return False

def load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            broken = CHECKPOINT_FILE.with_suffix(".broken.json")
            CHECKPOINT_FILE.replace(broken)
    return {
        "completed_indices": [],
        "rows": [],
        "measured_times": [],
        "passes": 0,
        "hard_failures": 0,
        "total_attempts": 0,
        "total_rate_limit_hits": 0,
        "start_time": time.time(),
    }

def save_checkpoint(checkpoint: dict[str, Any]):
    checkpoint["last_saved"] = time.time()
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=True)
    print(f"[OK] Checkpoint saved ({len(checkpoint['completed_indices'])} completed).")

def login(session: requests.Session) -> str:
    response = session.post(
        f"{BASE_URL}/auth/login",
        json={"username": LOGIN_USERNAME, "password": LOGIN_PASSWORD},
        timeout=30
    )
    response.raise_for_status()
    return response.json()["access_token"]

def call_chat(session: requests.Session, token: str, prompt: str, session_id: str) -> tuple[dict[str, Any], float, int]:
    start = time.perf_counter()
    response = session.post(
        f"{BASE_URL}/chat/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": prompt, "session_id": session_id},
        timeout=300,
    )
    elapsed = time.perf_counter() - start
    if _is_rate_limit_response(response):
        raise RateLimitError(response.text)
    response.raise_for_status()
    return response.json(), elapsed, response.status_code

def call_chat_with_retry(session: requests.Session, token: str, prompt: str, session_id: str):
    attempts, rate_limit_hits, total_elapsed = 0, 0, 0.0
    last_error = None
    while attempts <= MAX_RETRIES:
        attempts += 1
        try:
            result, elapsed, status = call_chat(session, token, prompt, session_id)
            total_elapsed += elapsed
            return result, total_elapsed, attempts, rate_limit_hits, status
        except RateLimitError as exc:
            rate_limit_hits += 1
            last_error = exc
            if attempts > MAX_RETRIES:
                break
            delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempts - 1))
            time.sleep(delay)
    raise RateLimitError(f"Rate-limited after {attempts} attempts for session={session_id}") from last_error

def evaluate_case(result: dict[str, Any], case: TestCase, status_code: int = 200) -> tuple[bool, str]:
    if case.expect_error:
        if status_code == case.expected_status:
            return True, "expected error"
        return False, f"expected error {case.expected_status} got {status_code}"

    count = result.get("count")
    answer = str(result.get("answer",""))
    results = result.get("results", [])
    mongo_filter = json.dumps(result.get("mongo_filter", {}), ensure_ascii=False).lower()

    if case.expected_count is not None and count != case.expected_count:
        if not (case.allow_clarification and "clarification" in answer.lower()):
            return False, f"count={count} expected={case.expected_count}"

    for marker in case.expected_markers:
        marker_l = marker.lower()
        found = (
            marker_l in answer.lower() or
            marker_l in mongo_filter or
            any(marker_l in json.dumps(doc, ensure_ascii=False).lower() for doc in results)
        )
        if not found:
            if not (case.allow_clarification and "clarification" in answer.lower()):
                return False, f"missing marker={marker}"
    return True, "ok"

# ================= MAIN EVALUATION LOOP =================
def run_case(session: requests.Session, token: str, case_idx: int, case: TestCase, request_delay: float, checkpoint: dict[str, Any]):
    try:
        if case.setup_prompt:
            _, _, setup_attempts, setup_rate_limit_hits, _ = call_chat_with_retry(session, token, case.setup_prompt, case.session_id)
            checkpoint["total_attempts"] += setup_attempts
            checkpoint["total_rate_limit_hits"] += setup_rate_limit_hits

        result, elapsed, attempts, rate_limit_hits, status = call_chat_with_retry(session, token, case.prompt, case.session_id)
        checkpoint["total_attempts"] += attempts
        checkpoint["total_rate_limit_hits"] += rate_limit_hits
        checkpoint["measured_times"].append(elapsed)
        passed, reason = evaluate_case(result, case, status)

    except RateLimitError as exc:
        print(f"[!] Rate limit hit at case {case_idx} ({case.name}). Saving checkpoint.")
        save_checkpoint(checkpoint)
        return None
    except Exception as exc:
        checkpoint["hard_failures"] += 1
        passed = False
        reason = f"request failed: {exc}"
        elapsed = 0.0
        result = {}

    if passed:
        checkpoint["passes"] += 1

    checkpoint["rows"].append({
        "idx": case_idx,
        "name": case.name,
        "prompt": case.prompt,
        "session_id": case.session_id,
        "elapsed_seconds": round(elapsed, 4),
        "passed": passed,
        "reason": reason,
    })
    checkpoint["completed_indices"].append(case_idx)
    status_text = "OK" if passed else "FAIL"
    print(f"[{case_idx+1}/{len(TEST_CASES)}] {status_text} {case.name} ({elapsed:.2f}s)")
    time.sleep(request_delay)
    return True

def main():
    checkpoint = load_checkpoint()
    session = requests.Session()
    token = login(session)

    completed = set(checkpoint["completed_indices"])
    cases_to_run = [i for i in range(len(TEST_CASES)) if i not in completed]
    if MAX_CASES_PER_RUN > 0:
        cases_to_run = cases_to_run[:MAX_CASES_PER_RUN]

    print(f"[=] Running {len(cases_to_run)} cases (total: {len(TEST_CASES)})")

    # Estimate slow vs fast
    measured_times = checkpoint.get("measured_times", [])
    avg_time = statistics.mean(measured_times) if measured_times else 5.0
    slow_threshold = avg_time * 2  # heuristic: more than twice avg time is "slow"

    slow_cases = []
    fast_cases = []

    for idx in cases_to_run:
        # fallback heuristic: use previous elapsed times if available
        prev = next((r for r in checkpoint["rows"] if r["idx"] == idx), None)
        prev_elapsed = prev["elapsed_seconds"] if prev else 0
        if prev_elapsed > slow_threshold:
            slow_cases.append(idx)
        else:
            fast_cases.append(idx)

    # Run fast cases sequentially
    for idx in fast_cases:
        case = TEST_CASES[idx]
        run_case(session, token, idx, case, REQUEST_DELAY_FAST, checkpoint)
        if len(checkpoint["completed_indices"]) % CHECKPOINT_INTERVAL == 0:
            save_checkpoint(checkpoint)

    # Run slow cases in parallel
    if slow_cases:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SLOW) as executor:
            futures = {executor.submit(run_case, session, token, idx, TEST_CASES[idx], REQUEST_DELAY_SLOW, checkpoint): idx for idx in slow_cases}
            for f in as_completed(futures):
                _ = f.result()
                if len(checkpoint["completed_indices"]) % CHECKPOINT_INTERVAL == 0:
                    save_checkpoint(checkpoint)

    save_checkpoint(checkpoint)

    measured_times = checkpoint["measured_times"]
    accuracy = checkpoint["passes"] / len(TEST_CASES) if TEST_CASES else 0
    avg_time = statistics.mean(measured_times) if measured_times else 0
    median_time = statistics.median(measured_times) if measured_times else 0

    report = {
        "cases_total": len(TEST_CASES),
        "cases_completed": len(checkpoint["completed_indices"]),
        "passes": checkpoint["passes"],
        "accuracy": round(accuracy,4),
        "average_time": round(avg_time,4),
        "median_time": round(median_time,4),
        "rate_limit_hits": checkpoint["total_rate_limit_hits"],
        "total_attempts": checkpoint["total_attempts"],
        "hard_failures": checkpoint["hard_failures"],
        "request_delay_fast": REQUEST_DELAY_FAST,
        "request_delay_slow": REQUEST_DELAY_SLOW,
        "max_retries": MAX_RETRIES,
        "checkpoint_interval": CHECKPOINT_INTERVAL,
        "elapsed_total_seconds": round(time.time() - checkpoint["start_time"], 2),
    }

    print("\nFINAL REPORT\n", json.dumps(report, indent=2, ensure_ascii=True))

if __name__ == "__main__":
    main()