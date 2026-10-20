FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/scu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
COPY start.sh .
RUN chmod +x start.sh

ENV SCU_DATA_DIR=/data
VOLUME /data
EXPOSE 8000
CMD ["./start.sh"]
