from fastapi import FastAPI, HTTPException
import requests
from bs4 import BeautifulSoup
import pandas as pd
from io import StringIO 

app = FastAPI(title="API Cotação Cooabriel")

@app.get("/cotacao")
def obter_cotacao():
    url = "https://cooabriel.coop.br/cotacao-do-dia"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        tabela = soup.find('table') 
        
        if tabela:
            df_cotacao = pd.read_html(StringIO(str(tabela)))[0]
            
            return {
                "status": "sucesso", 
                "dados": df_cotacao.to_dict(orient="records")
            }
        else:
            raise HTTPException(status_code=404, detail="Dados de cotação não encontrados.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar dados: {str(e)}")