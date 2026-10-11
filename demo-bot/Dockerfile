FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY booking*.json ./
ENV DATA_DIR=/srv/data
CMD ["python", "-m", "app.main"]
