# ./services/web_ui/Dockerfile

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY ./requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy Streamlit app source code
COPY ./app .

# Default API URL; override via environment variable in docker-compose or shell
ENV API_URL=http://api:8080

# Expose Streamlit port
EXPOSE 8501

# Run Streamlit
CMD ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false"]
