FROM python:3.12-slim
ARG SERVICE_NAME
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "Flask>=3.0,<4.0"
COPY servicios/${SERVICE_NAME}/app.py /app/app.py
COPY crear_datos_demo.py /app/crear_datos_demo.py
RUN python crear_datos_demo.py /seed/lago.db
CMD ["python", "app.py"]
