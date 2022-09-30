FROM python:3.10 AS builder
RUN pip3 install poetry
WORKDIR /tmp
COPY pyproject.toml poetry.lock *.py /tmp/
RUN poetry build

FROM python:3.10
WORKDIR /tmp
COPY --from=builder /tmp/dist/*.whl .
RUN pip3 install *.whl
RUN rm *.whl

ENTRYPOINT elspot2mqtt
