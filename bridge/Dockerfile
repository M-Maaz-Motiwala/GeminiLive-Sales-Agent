FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# libsamplerate0 is the runtime shared library used by the `samplerate`
# Python package (high-quality polyphase resampler). Google's own
# Gemini-Live-telephony reference uses libsamplerate rather than
# audioop.ratecv because the latter is just a one-tap digital filter
# which leaves audible artefacts and weakens Gemini's VAD detection on
# narrow-band telephony audio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsamplerate0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

EXPOSE 8000
EXPOSE 40000/udp

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
