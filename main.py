import json
from datetime import datetime

from config import (
    CHANNEL_NICHE,
    DAILY_VIDEO_COUNT,
    METADATA_DIR,
    REGION_CODE,
)
from modules.optimizer import (
    generate_original_daily_topics,
)
from modules.script_generator import (
    generate_content_plan,
)
from modules.trend_finder import (
    get_youtube_trends,
)


def save_metadata(
    plan: dict,
    index: int,
) -> None:
    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    path = (
        METADATA_DIR
        / f"plan_{timestamp}_{index}.json"
    )

    path.write_text(
        json.dumps(
            plan,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("Saved plan:", path)


def manual_mode() -> None:
    topic = input("Enter topic: ").strip()

    print("\nStyles:")
    print("1. Funny")
    print("2. Facts")
    print("3. Story")
    print("4. Educational")
    print("5. Motivational")

    style_map = {
        "1": "funny",
        "2": "facts",
        "3": "story",
        "4": "educational",
        "5": "motivational",
    }

    choice = input("Select style: ").strip()
    style = style_map.get(choice, "funny")

    plan = generate_content_plan(
        topic=topic,
        style=style,
    )

    save_metadata(plan, 1)

    print("\nGenerated title:")
    print(plan["title_options"][0])

    print("\nHook:")
    print(plan["hook"])

    print("\nScript:")
    print(plan["script"])


def daily_mode() -> None:
    print("\nFetching current YouTube trends...")

    trends = get_youtube_trends(
        region_code=REGION_CODE,
        max_results=25,
    )

    print(
        f"Generating {DAILY_VIDEO_COUNT} "
        f"original ideas for {CHANNEL_NICHE}..."
    )

    ideas = generate_original_daily_topics(
        trend_items=trends,
        count=DAILY_VIDEO_COUNT,
        niche=CHANNEL_NICHE,
    )

    for index, idea in enumerate(
        ideas,
        start=1,
    ):
        print(
            f"\nCreating plan {index}: "
            f"{idea['topic']}"
        )

        plan = generate_content_plan(
            topic=idea["topic"],
            style=idea.get(
                "style",
                "funny",
            ),
        )

        plan["trend_reason"] = idea.get(
            "trend_reason",
            "",
        )

        plan["original_angle"] = idea.get(
            "original_angle",
            "",
        )

        save_metadata(plan, index)


def main() -> None:
    print("\n=== AutoShorts Engine v2 ===")
    print("1. Manual content")
    print("2. Daily trend-based content")

    choice = input("Select mode: ").strip()

    if choice == "2":
        daily_mode()
    else:
        manual_mode()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as exc:
        print("\nERROR:", exc)