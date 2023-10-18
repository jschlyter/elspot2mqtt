FROM python:3.11 AS builder
RUN pip3 install poetry
WORKDIR /tmp
ADD pyproject.toml poetry.lock /tmp/
ADD elspot2mqtt /tmp/elspot2mqtt/
RUN poetry build

FROM python:3.11
WORKDIR /tmp
COPY --from=builder /tmp/dist/*.whl .
RUN pip3 install *.whl && rm *.whl

ENTRYPOINT elspot2mqtt
