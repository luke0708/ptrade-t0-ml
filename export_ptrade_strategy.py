from ptrade_t0_ml.ptrade_strategy_export import export_ptrade_strategy
from ptrade_t0_ml.minute_foundation import configure_logging


def main() -> None:
    configure_logging()
    export_ptrade_strategy()


if __name__ == "__main__":
    main()
