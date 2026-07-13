import random
import time
from typing import Any

from google import genai

from config import GEMINI_API_KEY


DEFAULT_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
]


def is_temporary_error(error: Exception) -> bool:
    message = str(error).upper()

    temporary_terms = (
        "503",
        "UNAVAILABLE",
        "HIGH DEMAND",
        "429",
        "RESOURCE_EXHAUSTED",
        "11001",
        "GETADDRINFO FAILED",
        "CONNECTERROR",
        "CONNECTION ERROR",
        "TIMED OUT",
        "TIMEOUT",
        "TEMPORARY FAILURE",
    )

    return any(term in message for term in temporary_terms)


def generate_with_retry(
    prompt: str,
    models: list[str] | None = None,
    attempts_per_model: int = 2,
) -> Any:
    """
    Try multiple Gemini models.

    For each model:
    - Retry temporary API/network errors.
    - Move to the next fallback model if still unavailable.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing from .env.")

    selected_models = models or DEFAULT_MODELS
    client = genai.Client(api_key=GEMINI_API_KEY)
    last_error: Exception | None = None

    for model in selected_models:
        print(f"\nTrying Gemini model: {model}")

        for attempt in range(1, attempts_per_model + 1):
            try:
                print(
                    f"Request attempt {attempt}/"
                    f"{attempts_per_model}..."
                )

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )

                if not response.text:
                    raise RuntimeError(
                        f"{model} returned an empty response."
                    )

                print(f"Success with model: {model}")
                return response

            except Exception as error:
                last_error = error

                if not is_temporary_error(error):
                    print(
                        f"Model {model} failed permanently: "
                        f"{error}"
                    )
                    break

                if attempt < attempts_per_model:
                    wait_seconds = (
                        4 * (2 ** (attempt - 1))
                        + random.uniform(0, 2)
                    )

                    print(
                        f"{model} is temporarily unavailable. "
                        f"Retrying in {wait_seconds:.1f} seconds..."
                    )

                    time.sleep(wait_seconds)
                else:
                    print(
                        f"{model} is still unavailable. "
                        "Trying the next fallback model..."
                    )

    raise RuntimeError(
        "All Gemini models failed. "
        "This is likely a temporary Google API capacity, "
        "network, or quota issue. Try again later."
    ) from last_error