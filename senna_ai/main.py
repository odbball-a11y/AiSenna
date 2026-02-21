from senna_ai.ui.main_window import SennaCoachApp

import argparse
import os


def main():
    parser = argparse.ArgumentParser()

    # Base directory = senna_ai folder
    base_dir = os.path.abspath(os.path.dirname(__file__))

    default_laps_folder = os.path.join(base_dir, "opponent_laps")

    parser.add_argument(
        "--laps-folder",
        default=default_laps_folder,
        help="Folder containing reference/opponent laps",
    )

    args = parser.parse_args()

    # Ensure folder exists
    os.makedirs(args.laps_folder, exist_ok=True)

    app = SennaCoachApp(laps_folder=args.laps_folder)
    app.run()


if __name__ == "__main__":
    main()
