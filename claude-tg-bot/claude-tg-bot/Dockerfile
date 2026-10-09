FROM python:3.12-slim

WORKDIR /srv
# LibreOffice нужен для точного перевода Word/Excel/PowerPoint в PDF и PNG (образ станет тяжелее)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-calc libreoffice-impress \
        fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
CMD ["python", "-m", "app.main"]
