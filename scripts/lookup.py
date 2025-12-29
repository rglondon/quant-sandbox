from quant_sandbox.config.settings import IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID
from quant_sandbox.data.ibkr import connect_ibkr, search_contracts


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("query")
    args = p.parse_args()

    ib = connect_ibkr(IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID)
    try:
        rows = search_contracts(ib, args.query, max_results=15)
        for r in rows:
            print(r)
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
