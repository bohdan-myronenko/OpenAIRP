FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Streamlit port
EXPOSE 8502

# Run streamlit
CMD ["streamlit", "run", "main.py", "--server.port=8502", "--server.address=0.0.0.0", "--server.baseUrlPath=/admin/", "--server.headless=true"]
