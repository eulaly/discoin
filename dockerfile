# syntax=docker/dockerfile:1
FROM python:3.7-alpine
WORKDIR /app
COPY requirements.txt /
RUN pip install -r /requirements.txt
COPY discoin-mongo.py discoin-mongo.py
ENV api_token=""
ENV mongodb_url=""
CMD [ "python3", "./discoin-mongo.py"]