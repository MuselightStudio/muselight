# Build from the project folder (the server uses the app's providers package):  docker build -f muselight_cloud/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY providers /app/providers
COPY muselight_cloud/server.py /app/muselight_cloud/server.py
ENV DATA_DIR=/data PORT=8080 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
CMD ["python", "/app/muselight_cloud/server.py"]
