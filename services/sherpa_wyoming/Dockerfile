FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY __init__.py config.py model_utils.py models.py MODEL_SOURCES.md MODEL_SHA256SUMS /app/sherpa_wyoming/
COPY providers/ /app/sherpa_wyoming/providers/

# Model weights are provided by the persistent /models volume at deployment.
# The application server entry point is added in the later runtime-integration batch.

FROM runtime AS ci-smoke

CMD ["python", "-c", "import subprocess; from importlib.metadata import version; import numpy, sherpa_onnx, wyoming; from sherpa_onnx import KeywordSpotter, OfflineRecognizer, OfflineTts; import sherpa_wyoming; assert version('sherpa-onnx') == '2.0.1'; assert version('wyoming') == '1.10.2'; subprocess.run(['sherpa-onnx-cli', '--help'], check=True, stdout=subprocess.DEVNULL); print('sherpa-onnx', version('sherpa-onnx'), 'wyoming', version('wyoming'), 'numpy', numpy.__version__, 'model APIs and CLI smoke passed')"]
