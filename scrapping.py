from fastapi import FastAPI, Query
import requests
from bs4 import BeautifulSoup
import pandas as pd
from io import StringIO 
from pymongo import MongoClient
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import certifi
import math

load_dotenv(override=True)
app = FastAPI(title="API Cotações de Café Integrada")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo-db:27017/")
cliente_mongo = MongoClient(MONGO_URI)
db = cliente_mongo["cafe_db"]
colecao = db["historico_cotacoes"]


def _serializar_documento(documento):
    documento_serializado = dict(documento)
    documento_serializado["_id"] = str(documento_serializado.get("_id"))
    return documento_serializado


def _parsear_valor_cotacao(texto):
    valor = texto.replace(".", "").replace(",", ".").strip()
    if valor in ("", "-", "--", "N/A"):
        return None
    try:
        return float(valor)
    except ValueError:
        return None


def _coletar_cccv(headers):
    url_cccv = "https://www.cccv.org.br/cotacao/"
    resposta = requests.get(url_cccv, headers={
        "User-Agent": headers["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/",
        "Upgrade-Insecure-Requests": "1",
    }, timeout=20)
    resposta.raise_for_status()

    soup = BeautifulSoup(resposta.text, "html.parser")
    tabela = soup.find("table")
    if not tabela:
        return None

    linhas_preenchidas = []
    for linha in tabela.select("tr"):
        celulas = linha.find_all("td")
        if len(celulas) != 4:
            continue

        valores = [
            _parsear_valor_cotacao(celula.get_text(" ", strip=True))
            for celula in celulas[1:4]
        ]

        if any(valor is not None for valor in valores):
            linhas_preenchidas.append({
                "identificador": celulas[0].get_text(" ", strip=True),
                "valores": valores,
            })

    if len(linhas_preenchidas) < 2:
        return None

    linha_dia = linhas_preenchidas[-2]
    linha_media = linhas_preenchidas[-1]
    identificador_dia = linha_dia["identificador"]
    try:
        identificador_dia = int(identificador_dia)
    except ValueError:
        pass

    return {
        "fonte": "cccv",
        "cotacao_dia": {
            "dia": identificador_dia,
            "arabica_dura": linha_dia["valores"][0],
            "arabica_rio": linha_dia["valores"][1],
            "conilon": linha_dia["valores"][2],
        },
        "media_mensal": {
            "arabica_dura": linha_media["valores"][0],
            "arabica_rio": linha_media["valores"][1],
            "conilon": linha_media["valores"][2],
        },
    }


def _coletar_cotacoes_do_sites():
    resposta = {
        "data_coleta": datetime.now(timezone.utc).isoformat(),
        "cooabriel": None,
        "painel_do_cafe": None,
        "cccv": None,
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

    try:
        resposta["cccv"] = _coletar_cccv(headers)
        if not resposta["cccv"]:
            resposta["erros"].append("CCCV indisponível ou sem dados para a cotação.")
    except Exception as e:
        resposta["erros"].append(f"CCCV falhou: {str(e)}")

    return resposta


@app.get("/index")
def index_response():
    return {"response": "online"}


@app.api_route("/coletar-cotacoes", methods=["GET", "POST"])
def coletar_cotacoes():
    resposta = _coletar_cotacoes_do_sites()
    resultado_insert = colecao.insert_one(resposta)
    resposta["_id"] = str(resultado_insert.inserted_id)
    return resposta


@app.get("/cotacoes")
def obter_cotacoes():
    ultimo_registro = colecao.find_one(sort=[("data_coleta", -1)])
    if not ultimo_registro:
        return {
            "data_coleta": None,
            "cooabriel": None,
            "painel_do_cafe": None,
            "erros": ["Nenhuma cotação encontrada no histórico."],
        }

    return _serializar_documento(ultimo_registro)


@app.get("/historico")
def ver_historico(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    pagina: int | None = Query(None, ge=1),
    limite: int | None = Query(None, ge=1, le=100),
    limit: int | None = Query(None, ge=1, le=100),
):
    pagina_atual = page if pagina is None else pagina
    limite_atual = per_page if limite is None and limit is None else (limite if limite is not None else limit)

    total_documentos = colecao.count_documents({})
    total_paginas = math.ceil(total_documentos / limite_atual) if total_documentos else 0
    pagina_atual = min(pagina_atual, total_paginas) if total_paginas else 1

    documentos = list(
        colecao.find()
        .sort("data_coleta", -1)
        .skip((pagina_atual - 1) * limite_atual)
        .limit(limite_atual)
    )

    return {
        "pagina": pagina_atual,
        "limite": limite_atual,
        "total": total_documentos,
        "total_paginas": total_paginas,
        "itens": [_serializar_documento(doc) for doc in documentos],
    }