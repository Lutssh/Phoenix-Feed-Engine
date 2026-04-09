# Builder Stage
FROM rust:1.85 as builder

WORKDIR /usr/src/app
COPY . .

# Build release binary
RUN cargo build --release --bin rust_feed_engine

# Runtime Stage
FROM debian:bookworm-slim

# libssl3 = runtime library; libssl-dev is build headers (only needed in builder stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/src/app/target/release/rust_feed_engine /usr/local/bin/rust_feed_engine

EXPOSE 3000

ENV RUST_LOG=info
ENV REDIS_URL=redis://redis:6379

CMD ["rust_feed_engine"]
