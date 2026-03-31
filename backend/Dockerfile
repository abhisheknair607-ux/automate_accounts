FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace/backend

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /workspace/backend
COPY ["Invoice_598527_Account_64876_Division_MRPI_Full_unlocked.pdf", "/workspace/"]
COPY ["Delivery Docket.jpeg", "/workspace/"]
COPY ["Accounting Template.png", "/workspace/"]

RUN mkdir -p /workspace/backend/storage

EXPOSE 8000

# Render (and most PaaS) inject $PORT at runtime; fall back to 8000 for local use.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
