FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

ARG TARGETARCH
WORKDIR /app

RUN test "$TARGETARCH" = "amd64" \
    && apt-get update \
    && apt-get install --no-install-recommends -y libgcc-s1 libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && python -m pip check \
    && rm /tmp/requirements.txt

COPY *.py MODEL_SOURCES.md MODEL_SHA256SUMS /app/sherpa_wyoming/
COPY providers/ /app/sherpa_wyoming/providers/

EXPOSE 10400/tcp
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "-m", "sherpa_wyoming.healthcheck", "--host", "127.0.0.1", "--port", "10400"]

CMD ["python", "-m", "sherpa_wyoming.run"]

FROM runtime AS ci-smoke

CMD ["python", "-c", "from importlib.metadata import version; import subprocess; import numpy, sherpa_onnx, wyoming; from sherpa_onnx import KeywordSpotter, OfflineRecognizer, OfflineTts; import sherpa_wyoming.run, sherpa_wyoming.healthcheck; assert version('sherpa-onnx') == '2.0.1'; assert version('wyoming') == '1.10.2'; subprocess.run(['sherpa-onnx-cli', '--help'], check=True, stdout=subprocess.DEVNULL); print('sherpa-onnx', version('sherpa-onnx'), 'wyoming', version('wyoming'), 'numpy', numpy.__version__, 'Sherpa model APIs, Wyoming service and healthcheck imports passed')"]
