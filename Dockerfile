FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY auto_dl.py cli.py .

RUN mkdir -p /app/downloads

CMD ["python3", "auto_dl.py"]
