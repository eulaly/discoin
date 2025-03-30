# syntax=docker/dockerfile:1
FROM python:3.11
WORKDIR /app
COPY requirements.txt /requirements.txt
RUN python3 -m pip install --no-cache-dir -r /requirements.txt
COPY discoin.py discoin.py
ENV api_token=""
ENV mongodb_url=""
CMD [ "python3", "./discoin.py"]