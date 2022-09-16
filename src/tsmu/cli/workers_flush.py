#!/usr/bin/env python3

from tsmu.workers import SetupBroker


def main() -> None:
    """
    Flush all pending jobs in tsmu-workers job queue.
    """
    b = SetupBroker()
    b.flush_all()


if __name__ == "__main__":
    main()
