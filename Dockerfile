FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Database lives on a mounted volume so it survives image rebuilds.
ENV FASTMSR_DB=/data/fastmsr.sqlite
ENV FASTMSR_PORT=5008
EXPOSE 5008

# Seed on first boot if the DB is missing, then serve.
CMD ["sh", "-c", "python -c 'import db,seed; seed.build() if not db.db_exists() else None' && python web_app.py"]
