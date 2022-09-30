FROM python:3.10 AS builder
RUN pip3 install poetry
WORKDIR /tmp
ADD pyproject.toml poetry.lock /tmp/
ADD elspot2mqtt /tmp/elspot2mqtt/
RUN poetry build

FROM python:3.10
WORKDIR /tmp
COPY --from=builder /tmp/dist/*.whl .
RUN pip3 install *.whl
RUN rm *.whl

ENTRYPOINT elspot2mqtt
