FROM python:3.11-slim
WORKDIR /app
#instala dependências
RUN apt-get update && apt-get install -y --no-install-recommends \
build-essential \
libpq-dev \
&& rm -rf /var/lib/apt/lists/*
# Copia e instala os requirements primeiro (aproveita o cache de camadas do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copia o restante do código da aplicação
COPY . .
# Expõe a porta que o FastAPI vai rodar (ex: 8000)
EXPOSE 8000
# Comando para iniciar a aplicação com Uvicorn
CMD ["uvicorn", "scrapping:app", "--host", "0.0.0.0", "--port", "8000"]