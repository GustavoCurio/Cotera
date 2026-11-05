FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY cotera ./cotera
COPY app.py ./
COPY .streamlit ./.streamlit
COPY data ./data
COPY evals ./evals
COPY reports ./reports
RUN useradd --create-home cotera && mkdir -p /app/storage && chown -R cotera:cotera /app
USER cotera
EXPOSE 8505 8005
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.port", "8505", "--server.address", "0.0.0.0", "--server.headless", "true", "--server.showEmailPrompt", "false"]
