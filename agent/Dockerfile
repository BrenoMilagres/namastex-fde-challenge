FROM python:3.12-slim

WORKDIR /srv

# uv pra instalar as deps do pyproject/uv.lock
RUN pip install --no-cache-dir uv

# --extra index inclui pandas/pyarrow: a mesma imagem serve o agente E o
# servico indexer (que le o parquet). O runtime do agente nao usa pandas.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --extra index

COPY app ./app
COPY eval ./eval

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
