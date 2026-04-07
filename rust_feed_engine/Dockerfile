# Builder Stage
FROM rust:1.85 as builder

WORKDIR /usr/src/app
COPY . .

# Build release binary
RUN cargo build --release --bin rust_feed_engine

# Runtime Stage
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/src/app/target/release/rust_feed_engine /usr/local/bin/rust_feed_engine

ENV RUST_LOG=info
ENV REDIS_URL=redis://redis:6379

CMD ["rust_feed_engine"]
