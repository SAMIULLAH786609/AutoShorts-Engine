import argparse

from pipeline import create_short


STYLE_OPTIONS = {
    "1": "funny",
    "2": "facts",
    "3": "story",
    "4": "educational",
    "5": "motivational",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate complete short videos."
    )

    parser.add_argument("--topic")
    parser.add_argument("--style", default="funny")
    parser.add_argument("--language", default="English")
    parser.add_argument("--gender", default="female")

    args = parser.parse_args()

    topic = args.topic
    style = args.style

    if not topic:
        topic = input("Enter topic: ").strip()

        print("\n1. Funny")
        print("2. Facts")
        print("3. Story")
        print("4. Educational")
        print("5. Motivational")

        style = STYLE_OPTIONS.get(
            input("Select style: ").strip(),
            "funny",
        )

    create_short(
        topic=topic,
        style=style,
        language=args.language,
        gender=args.gender,
    )


if __name__ == "__main__":
    main()