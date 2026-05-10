FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker source code
COPY ./app .

# Expose worker port
EXPOSE 8081

# Run worker service
# Note: Since we copy ./app to /app, the files are in /app directly
# So we use "main:app" instead of "app.main:app"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
