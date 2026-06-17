FROM python:3.11-slim

WORKDIR /app
ENV PORT=8080

COPY server.py style.css app.js index.html ./

RUN mkdir -p saves

EXPOSE 8080
CMD ["python", "server.py"]
