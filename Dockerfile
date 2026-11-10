# The upstream image is Alpine but does not include timezone data, so TZ is
# silently ignored and Autotune runs in UTC. Add tzdata so the pump/Loop
# timezone is actually used for the 4am day boundaries and hour grouping.
ARG BASE_IMAGE=docker.io/houthacker42/nightscout-autotune:latest
FROM ${BASE_IMAGE}

RUN apk add --no-cache tzdata
