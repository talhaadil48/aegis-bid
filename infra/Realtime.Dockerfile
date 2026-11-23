FROM golang:1.24-alpine AS build
RUN apk add --no-cache gcc musl-dev
WORKDIR /src
COPY services/realtime/go.mod ./
RUN go mod download github.com/gorilla/websocket
COPY services/realtime ./
RUN gofmt -w gateway load stress && go test -race ./... && CGO_ENABLED=0 go build -o /gateway ./gateway && CGO_ENABLED=0 go build -o /load ./load && CGO_ENABLED=0 go build -o /stress ./stress
FROM alpine:3.21
RUN apk add --no-cache ca-certificates
COPY --from=build /gateway /load /stress /usr/local/bin/
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/gateway"]
