from pymongo import MongoClient
import requests
import re
import ast

# MongoDB configuration
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB_NAME = "invoice_pfe"

# LLaMA API configuration
LLAMA_API_KEY = "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"
LLAMA_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
LLAMA_MODEL = "openai/gpt-oss-120b"

def parse_llm_query(llm_response):
    try:
        match = re.search(r"```(?:python|json)?\s*(.*?)\s*```", llm_response, re.DOTALL)
        query_str = match.group(1).strip() if match else llm_response.strip()

        query_str = re.sub(r"^\w+\s*=\s*", "", query_str).strip()

        query_str = query_str.replace("true", "True").replace("false", "False").replace("null", "None")

        query_data = ast.literal_eval(query_str)

        if isinstance(query_data, dict) and "$match" in query_data:
            return query_data["$match"]

        return query_data

    except Exception as e:
        print(f"Erreur de parsing : {e}")
        return None

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db["invoices"]

# Get user query
user_prompt = input("Enter your query: ")

# System prompt for LLM
system_prompt = f"""You are a MongoDB query translator.
The database "invoice_pfe" has documents structured as follows:
{{
  "_id" : ObjectId,
  "invoice": {{
    "vendeur": {{
      "nom": "",
      "adresse": "",
      "telephone": "",
      "email": "",
      "matricule_fiscale": ""
    }},
    "client": {{
      "nom": "",
      "adresse": "",
      "matricule_fiscale": ""
    }},
    "facture": {{
      "numero": "",
      "date": "",
      "date_echeance":"",
      "type": ""
    }},
    "lignes": [{{"quantite": , "unite": "", "code_article" :"", "designation": "", "prix_unitaire_ht": , "taux_tva": , "montant_ht": , "remise" :}} ],
    "totaux": {{"total_ht": , "total_tva": , "base_tva" : , "timbre_fiscal": , "total_ttc": , "devise" : ""}},
    "paiement": {{"montant_en_lettres": "", "mode_paiement" : "" , "statu_paiement" : "" , "conditions_paiement" : "", "date_reglement" : ""}},
    
  }},
  "fichier" : {{"_source_file": "", "image_path" : "", "json_brut" :"", "cree_le" : ""}}
  "extraction_id" : "",
  "status" : "",
  "saved_at" :""
}}

Translate the following user query into a MongoDB find query:
<user query>
{user_prompt}
</user query>
IMPORTANT : note that the provided fields by users should be searched with tolerance , means could be uppercase or substring and mongo should find it
Respond **only** with the Python MongoDB query dictionary (do not include explanation or text).
the response should be a valid dict ( no variable assigning for example don't do query = {{}} give me directly the dict) 
"""

# Make the LLM call

response = requests.post(
    LLAMA_BASE_URL,
    headers={
        "Authorization": f"Bearer {LLAMA_API_KEY}",
        "Content-Type": "application/json"
    },
    json={
        "model": LLAMA_MODEL,
        "messages": [
        {"role": "user", "content": system_prompt}
    ],
        "temperature" : 0.7
    }
)

llm_query = response.json()['choices'][0]['message']['content']
print(llm_query)
parsed = parse_llm_query(llm_query)
print(parsed)

# Execute query
factures = collection.find(parsed)  # careful: eval only if you trust the LLM

# Print results
for facture in factures:
    print(facture)