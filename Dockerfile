FROM python:3.13 AS builder
RUN pip3 install uv
WORKDIR /tmp
ADD pyproject.toml /tmp/
ADD elspot2mqtt /tmp/elspot2mqtt/
RUN uv build

FROM python:3.13
WORKDIR /tmp
COPY --from=builder /tmp/dist/*.whl .
RUN pip3 install *.whl && rm *.whl

ENTRYPOINT elspot2mqtt
