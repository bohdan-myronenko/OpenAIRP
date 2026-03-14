# services/admin_dashboard/Dockerfile

FROM python:3.10

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y python3-tk && \
    rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt .

# Install Python dependencies, including PySimpleGUI from its private index
# requirements.txt should contain "PySimpleGUI" (no version pin is fine)
RUN python -m pip install --no-cache-dir --extra-index-url https://PySimpleGUI.net/install -r requirements.txt

COPY ./app .

ENV API_URL=http://api:8080

CMD ["python", "main.py"]
