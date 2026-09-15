import argparse
import logging
import signal
import socket
import sys
from datetime import datetime


def parse_args():
    parser = argparse.ArgumentParser(description="WeMail UDP echo test server")
    parser.add_argument("--host", default="0.0.0.0", help="listen address")
    parser.add_argument("--port", type=int, default=18500, help="UDP listen port")
    parser.add_argument("--buffer-size", type=int, default=65535, help="maximum datagram size")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))

    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False
        server.close()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    logging.info("UDP echo server listening on %s:%s", args.host, args.port)

    while running:
        try:
            data, client = server.recvfrom(args.buffer_size)
        except OSError:
            break

        received_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        preview = data[:200].decode("utf-8", errors="replace")
        logging.info(
            "received bytes=%d from=%s:%d payload=%r",
            len(data),
            client[0],
            client[1],
            preview,
        )

        try:
            sent = server.sendto(data, client)
            logging.info(
                "echoed bytes=%d to=%s:%d at=%s",
                sent,
                client[0],
                client[1],
                received_at,
            )
        except OSError as error:
            logging.error("send failed to %s:%d: %s", client[0], client[1], error)

    logging.info("UDP echo server stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
