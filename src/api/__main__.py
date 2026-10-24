"""Run the fixture API: ``python -m src.api``."""

import uvicorn


def main() -> None:
    uvicorn.run("src.api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
