ARG BASE_IMAGE=docker.io/houthacker42/nightscout-autotune:latest
FROM ${BASE_IMAGE}

RUN apk add --no-cache tzdata
