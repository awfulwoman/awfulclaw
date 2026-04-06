FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt
COPY . .
ENV HOST=0.0.0.0
ENV PORT=3000
ENV AGENT_URL=http://localhost:8080
CMD ["python", "app.py"]
