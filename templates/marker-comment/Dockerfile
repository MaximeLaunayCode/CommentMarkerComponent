FROM python:3.13-alpine3.22

RUN apk add --no-cache git

WORKDIR /opt/marker-comment
COPY marker_comment ./marker_comment
COPY templates/marker-comment/marker-comment-process /usr/local/bin/marker-comment-process
RUN chmod 0555 /usr/local/bin/marker-comment-process
