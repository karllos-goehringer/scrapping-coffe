from fastapi import FastAPI
import requests
from bs4 import BeautifulSoup
import pandas as pd
from io import StringIO 
from pymongo import MongoClient
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import certifi

load_dotenv(override=True)
app = FastAPI(title="API Cotações de Café Integrada")

usuario = os.getenv("DB_USERNAME")
senha = os.getenv("DB_PASSWORD")
MONGO_URI = f"mongodb+srv://{usuario}:{senha}@cluster0.ygc5xht.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

cliente_mongo = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = cliente_mongo["cafe_db"]          
colecao = db["historico_cotacoes"]

@app.get("/index")
def index_response():
    return {"response": "online"}

@app.get("/cotacoes")
def obter_cotacoes():
    resposta = {
        "data_coleta": datetime.now(timezone.utc).isoformat(),
        "cooabriel": None,
        "painel_do_cafe": None,
        "erros": []
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    cooabriel_sucesso = False

    try:
        url_cooabriel = "https://cooabriel.coop.br/cotacao-do-dia"
        res_cooabriel = requests.get(url_cooabriel, headers=headers, timeout=10)
        res_cooabriel.raise_for_status()
        soup = BeautifulSoup(res_cooabriel.text, 'html.parser')
        tabela = soup.find('table') 
        
        if tabela:
            df_cotacao = pd.read_html(StringIO(str(tabela)))[0]
            resposta["cooabriel"] = df_cotacao.to_dict(orient="records")
            cooabriel_sucesso = True
        else:
            resposta["erros"].append("Tabela da Cooabriel não encontrada.")
    except Exception as e:
        resposta["erros"].append(f"Cooabriel falhou: {str(e)}")

    if not cooabriel_sucesso or not resposta["cooabriel"]:
        ultimo_registro = colecao.find_one(
            {"cooabriel": {"$ne": None}}, 
            sort=[("data_coleta", -1)]
        )
        if ultimo_registro and ultimo_registro.get("cooabriel"):
            resposta["cooabriel"] = ultimo_registro["cooabriel"]
            resposta["erros"].append("Cooabriel indisponível. Utilizando o último valor salvo no histórico.")

    try:
        url_painel = "https://api.coffee-panel.mitrix.online/api/home/information"
        res_painel = requests.get(url_painel, headers=headers, timeout=10)
        res_painel.raise_for_status()    
        dados_api = res_painel.json()
        resposta["painel_do_cafe"] = dados_api.get("values", [])
    except Exception as e:
        resposta["erros"].append(f"Painel falhou: {str(e)}")

    colecao.insert_one(resposta)
    
    if "_id" in resposta:
        resposta["_id"] = str(resposta["_id"])
        
    return resposta

@app.get("/historico")
def ver_historico(limite: int = 10):
    documentos = list(colecao.find().sort("data_coleta", -1).limit(limite))
    for doc in documentos:
        doc["_id"] = str(doc["_id"])
    return documentos