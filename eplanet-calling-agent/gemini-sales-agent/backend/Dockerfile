FROM python:3.12-slim

WORKDIR /app

<<<<<<< HEAD
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
=======
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev docker.io && rm -rf /var/lib/apt/lists/*
>>>>>>> newImp

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
